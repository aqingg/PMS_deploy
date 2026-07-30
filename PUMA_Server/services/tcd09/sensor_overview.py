from __future__ import annotations

import io
import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from fastapi import HTTPException

from services.datamerge import docx


SENSOR_TYPE_ROWS_PLACEHOLDER = "<TCD09_SENSOR_TYPE_ROWS>"
SENSOR_LOCATION_ROWS_PLACEHOLDER = "<TCD09_SENSOR_LOCATION_ROWS>"
SENSOR_DIRECTION_ROWS_PLACEHOLDER = "<TCD09_SENSOR_DIRECTION_ROWS>"
SENSOR_MEASUREMENT_ROWS_PLACEHOLDER = "<TCD09_SENSOR_MEASUREMENT_ROWS>"

THIS_DIR = Path(__file__).resolve().parent
SERVER_ROOT = THIS_DIR.parents[1]
DEFAULT_SENSORMAP_RULES_PATH = (
    SERVER_ROOT / "config" / "sensormap_sensor_rules.json"
)
DEFAULT_SENSOR_OVERVIEW_RULES_PATH = (
    SERVER_ROOT / "config" / "tcd09_sensor_overview_rules.json"
)

INERTIAL_FAMILIES = ("SMA", "SMB", "SMI", "SMG", "SMU")
PERIPHERAL_FAMILIES = ("UFS", "RCS", "PAS", "PCS", "PPS", "PTS")
KNOWN_FAMILIES = (*INERTIAL_FAMILIES, *PERIPHERAL_FAMILIES)

EMPTY_VALUES = {"", "N/A", "NA", "NULL", "NONE", "0"}

# Supported separators between complete sensor descriptions. Before splitting,
# known forms such as UFS-L and PAS_BL are normalized so their position suffix
# is not mistaken for a connector.
SENSOR_CONNECTOR_PATTERN = re.compile(
    r"\s*(?:[+_\-\uFF0B\uFF0D,;，；/\\|]+)\s*"
)
QUANTITY_PATTERN = re.compile(r"^\s*(\d+)\s*\*?\s*(?=[A-Za-z])")

POSITION_ORDER = {
    "UFS": ("L", "C", "R"),
    "RCS": ("L", "C", "R"),
    "PCS": ("L", "C", "R"),
    "PPS": ("FL", "FR", "RL", "RR"),
    "PAS": ("BL", "BR", "CL", "CR"),
}


@dataclass
class SensorEntry:
    family: str
    display_name: str
    is_inertial: bool
    declared_count: int = 0
    occurrence_count: int = 0
    positions: set[str] = field(default_factory=set)

    @property
    def effective_count(self) -> int:
        return max(
            int(self.declared_count or 0),
            int(self.occurrence_count or 0),
            len(self.positions),
        )


def _as_sensor_text(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, (list, tuple, set)):
        return "+".join(
            str(item).strip()
            for item in value
            if str(item).strip()
        )

    return str(value).strip()


def _normalize_positional_compounds(text: str) -> str:
    """Preserve known position suffixes before connector splitting.

    Examples:
        UFS-L / UFS_L -> UFSL
        RCS-R / RCS_R -> RCSR
        PAS-BL / PAS_BL -> PASBL
    """

    normalized = str(text or "")
    normalized = re.sub(
        r"(?i)\b(PPS)\s*[_-]\s*(FL|FR|RL|RR|L|R|C)\b",
        lambda match: f"{match.group(1)}{match.group(2)}",
        normalized,
    )
    normalized = re.sub(
        r"(?i)\b(UFS|RCS|PCS)\s*[_-]\s*([LCR])\b",
        lambda match: f"{match.group(1)}{match.group(2)}",
        normalized,
    )
    normalized = re.sub(
        r"(?i)\b(PAS)\s*[_-]\s*(BL|BR|CL|CR)\b",
        lambda match: f"{match.group(1)}{match.group(2)}",
        normalized,
    )
    return normalized


def _split_sensor_text(value: Any) -> list[str]:
    raw_text = _as_sensor_text(value)
    if raw_text.upper() in EMPTY_VALUES:
        return []

    normalized = _normalize_positional_compounds(raw_text)
    return [
        part.strip()
        for part in SENSOR_CONNECTOR_PATTERN.split(normalized)
        if part.strip()
    ]


def _extract_quantity(token: str) -> tuple[int | None, str]:
    match = QUANTITY_PATTERN.match(token)
    if not match:
        return None, token.strip()

    quantity = int(match.group(1))
    remainder = token[match.end():].strip()
    return quantity, remainder


def _detect_family(token: str) -> tuple[str | None, str]:
    cleaned = re.sub(r"\s+", "", str(token or ""))
    upper = cleaned.upper()

    for family in KNOWN_FAMILIES:
        if upper.startswith(family):
            return family, cleaned[len(family):]

    return None, cleaned


def _remove_position_suffix(
    family: str,
    remainder: str,
) -> tuple[str | None, str]:
    """Extract explicit physical position while retaining the sensor model.

    Supported examples:
        UFSL, UFSR, UFSC
        UFS6sL, UFS6sR, UFS6sC
        PASBL, PASBR, PASCL, PASCR
        PAS6sBL, PAS6sBR
        PCSL, PCSR
    """

    raw = str(remainder or "")
    upper = raw.upper()

    if family == "PAS":
        candidates = ("BL", "BR", "CL", "CR")
    elif family == "PPS":
        # Longest suffixes must be checked first.
        candidates = ("FL", "FR", "RL", "RR", "L", "C", "R")
    elif family in {"UFS", "RCS", "PCS"}:
        candidates = ("L", "C", "R")
    else:
        return None, raw

    # Prefer a position immediately after the family code.
    for position in candidates:
        if upper.startswith(position):
            return position, raw[len(position):]

    # Also support a position appended after a model name.
    for position in candidates:
        if upper.endswith(position) and len(raw) > len(position):
            return position, raw[:-len(position)]

    return None, raw


def _parse_sensor_token(
    raw_token: str,
    *,
    force_inertial: bool,
) -> tuple[str, str, int | None, str | None] | None:
    quantity, token = _extract_quantity(raw_token)
    family, remainder = _detect_family(token)
    if family is None:
        return None

    position, model_remainder = _remove_position_suffix(family, remainder)
    display_name = f"{family}{model_remainder}".strip() or family

    # The source field decides whether the row is inertial or peripheral.
    # Family detection is still used to normalize the model and location.
    is_inertial = force_inertial or family in INERTIAL_FAMILIES
    return family, display_name, quantity, position, is_inertial


def _merge_sensor_entries(
    value: Any,
    *,
    force_inertial: bool,
) -> list[SensorEntry]:
    entries: dict[tuple[str, str], SensorEntry] = {}
    order: list[tuple[str, str]] = []

    for raw_token in _split_sensor_text(value):
        parsed = _parse_sensor_token(
            raw_token,
            force_inertial=force_inertial,
        )
        if parsed is None:
            continue

        family, display_name, quantity, position, is_inertial = parsed
        key = (family, display_name.casefold())

        if key not in entries:
            entries[key] = SensorEntry(
                family=family,
                display_name=display_name,
                is_inertial=is_inertial,
            )
            order.append(key)

        entry = entries[key]
        entry.occurrence_count += 1

        if quantity is not None:
            entry.declared_count = max(entry.declared_count, quantity)

        if position:
            entry.positions.add(position)

    return [entries[key] for key in order]


def _load_sensormap_rules(
    rules_path: str | Path = DEFAULT_SENSORMAP_RULES_PATH,
) -> dict[str, Any]:
    path = Path(rules_path)
    if not path.is_file():
        return {}

    try:
        with path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}

    return data if isinstance(data, dict) else {}


def _default_count(
    entry: SensorEntry,
    rules: dict[str, Any],
    fallback: int,
) -> int:
    if entry.effective_count > 0:
        # A single generic occurrence such as "UFS6s" means the quantity was
        # not explicitly stated. In that case Sensor Map's default_count wins.
        if (
            entry.effective_count == 1
            and not entry.positions
            and entry.declared_count == 0
        ):
            family_rule = rules.get(entry.family, {})
            configured = family_rule.get("default_count")
            if isinstance(configured, int) and configured > 0:
                return configured
            return fallback

        return entry.effective_count

    family_rule = rules.get(entry.family, {})
    configured = family_rule.get("default_count")
    if isinstance(configured, int) and configured > 0:
        return configured

    return fallback


def _three_position_set_from_count(count: int) -> set[str]:
    if count <= 1:
        return {"C"}
    if count == 2:
        return {"L", "R"}
    return {"L", "C", "R"}


def _format_three_positions(
    positions: set[str],
    location_name: str,
) -> str:
    normalized = set(positions)

    phrases = {
        frozenset({"L"}): f"Left {location_name}",
        frozenset({"C"}): f"Center {location_name}",
        frozenset({"R"}): f"Right {location_name}",
        frozenset({"L", "R"}): f"Left and Right {location_name}",
        frozenset({"L", "C"}): f"Left and Center {location_name}",
        frozenset({"C", "R"}): f"Center and Right {location_name}",
        frozenset({"L", "C", "R"}): (
            f"Left, Center and Right {location_name}"
        ),
    }
    return phrases.get(
        frozenset(normalized),
        f"{', '.join(sorted(normalized))} {location_name}",
    )


def _pas_positions_from_count(
    count: int,
    rules: dict[str, Any],
) -> set[str]:
    family_rule = rules.get("PAS", {})
    configured = family_rule.get("positions_by_count", {})
    selected = configured.get(str(count))

    if isinstance(selected, list) and selected:
        return {
            str(position).upper()
            for position in selected
            if str(position).strip()
        }

    if count <= 2:
        return {"BL", "BR"}
    return {"BL", "BR", "CL", "CR"}


def _format_pas_positions(positions: set[str]) -> str:
    normalized = set(positions)

    if normalized == {"BL", "BR"}:
        return "Left and Right B-pillar"
    if normalized == {"CL", "CR"}:
        return "Left and Right C-pillar"
    if normalized == {"BL", "BR", "CL", "CR"}:
        return "Left and Right B-pillar; Left and Right C-pillar"

    names = {
        "BL": "Left B-pillar",
        "BR": "Right B-pillar",
        "CL": "Left C-pillar",
        "CR": "Right C-pillar",
    }
    ordered = [
        names[position]
        for position in POSITION_ORDER["PAS"]
        if position in normalized
    ]
    return "; ".join(ordered) if ordered else "N/A"



def _normalize_pps_position(position: str) -> str:
    """Normalize legacy PPS L/R positions to front-door positions."""

    normalized = str(position or "").upper()
    return {
        "L": "FL",
        "R": "FR",
        "C": "FL",
    }.get(normalized, normalized)


def _pps_positions_from_count(count: int) -> set[str]:
    """Expand PPS quantity into concrete door positions."""

    if count <= 1:
        return {"FL"}
    if count == 2:
        return {"FL", "FR"}
    if count == 3:
        return {"FL", "FR", "RL"}
    return {"FL", "FR", "RL", "RR"}


def _format_pps_positions(positions: set[str]) -> str:
    normalized = {
        _normalize_pps_position(position)
        for position in positions
        if str(position or "").strip()
    }

    if normalized == {"FL", "FR"}:
        return "Left and Right Front door"
    if normalized == {"RL", "RR"}:
        return "Left and Right Rear door"
    if normalized == {"FL", "FR", "RL", "RR"}:
        return "Left and Right Front and Rear door"

    names = {
        "FL": "Left Front door",
        "FR": "Right Front door",
        "RL": "Left Rear door",
        "RR": "Right Rear door",
    }
    ordered = [
        names[position]
        for position in POSITION_ORDER["PPS"]
        if position in normalized
    ]
    return "; ".join(ordered) if ordered else "N/A"


def _sensor_location(
    entry: SensorEntry,
    rules: dict[str, Any],
) -> str:
    if entry.is_inertial:
        return "ECU on tunnel"

    family = entry.family

    if family == "UFS":
        positions = entry.positions or _three_position_set_from_count(
            _default_count(entry, rules, fallback=2)
        )
        return _format_three_positions(positions, "longitudinal beam")

    if family == "RCS":
        positions = entry.positions or _three_position_set_from_count(
            _default_count(entry, rules, fallback=2)
        )
        return _format_three_positions(positions, "rear trunk")

    if family == "PAS":
        positions = entry.positions or _pas_positions_from_count(
            _default_count(entry, rules, fallback=2),
            rules,
        )
        return _format_pas_positions(positions)

    if family == "PCS":
        positions = entry.positions or _three_position_set_from_count(
            _default_count(entry, rules, fallback=1)
        )
        return _format_three_positions(positions, "front bumper")

    if family == "PPS":
        positions = {
            _normalize_pps_position(position)
            for position in entry.positions
        }
        if not positions:
            positions = _pps_positions_from_count(
                _default_count(entry, rules, fallback=2)
            )
        return _format_pps_positions(positions)

    if family == "PTS":
        return "Front bumper"

    return "N/A"



def _load_sensor_overview_rules(
    rules_path: str | Path = DEFAULT_SENSOR_OVERVIEW_RULES_PATH,
) -> dict[str, Any]:
    """Load fixed Sensor Overview mappings.

    A missing or malformed rules file is reported explicitly because silently
    writing N/A would hide a deployment/configuration error.
    """

    path = Path(rules_path)
    if not path.is_file():
        raise HTTPException(
            status_code=500,
            detail=f"TCD09 Sensor Overview rules do not exist: {path}",
        )

    try:
        with path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Invalid TCD09 Sensor Overview rules: {path}: {exc}",
        ) from exc

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=500,
            detail="TCD09 Sensor Overview rules root must be a JSON object.",
        )

    direction_rules = data.get("sensing_direction")
    if not isinstance(direction_rules, dict):
        raise HTTPException(
            status_code=500,
            detail=(
                'TCD09 Sensor Overview rules must define '
                '"sensing_direction".'
            ),
        )

    return data


def _as_rule_lines(value: Any) -> list[str]:
    """Normalize one configured value into non-empty output lines."""

    if isinstance(value, str):
        lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    elif isinstance(value, (list, tuple)):
        lines = [str(item) for item in value]
    else:
        lines = []

    return [
        str(line).strip()
        for line in lines
        if str(line).strip()
    ]


def _sensor_sensing_direction(
    entry: SensorEntry,
    overview_rules: dict[str, Any],
) -> str:
    """Resolve the fixed third-column value for one Sensor Type.

    Matching priority:
        1. exact model name, case-insensitive;
        2. parsed sensor family;
        3. configured default.

    Multiple configured values are joined with line breaks, so they remain in
    one Word table cell and do not create additional table rows.
    """

    direction_rules = overview_rules.get("sensing_direction", {})
    exact_models = direction_rules.get("exact_models", {})
    family_rules = direction_rules.get("sensor_families", {})

    exact_lookup = {
        str(model).strip().casefold(): value
        for model, value in exact_models.items()
        if str(model).strip()
    } if isinstance(exact_models, dict) else {}

    family_lookup = {
        str(family).strip().upper(): value
        for family, value in family_rules.items()
        if str(family).strip()
    } if isinstance(family_rules, dict) else {}

    configured = exact_lookup.get(entry.display_name.casefold())
    if configured is None:
        configured = family_lookup.get(entry.family.upper())
    if configured is None:
        configured = direction_rules.get("default", ["N/A"])

    lines = _as_rule_lines(configured)
    return "\n".join(lines or ["N/A"])



def _sensor_measurement(
    entry: SensorEntry,
    overview_rules: dict[str, Any],
) -> str:
    """Resolve the fixed fourth-column Measurement value.

    Matching priority:
        1. exact model name, case-insensitive;
        2. parsed sensor family;
        3. configured default.

    Multiple values are written into one Word cell with line breaks.
    """

    measurement_rules = overview_rules.get("measurement", {})
    exact_models = measurement_rules.get("exact_models", {})
    family_rules = measurement_rules.get("sensor_families", {})

    exact_lookup = {
        str(model).strip().casefold(): value
        for model, value in exact_models.items()
        if str(model).strip()
    } if isinstance(exact_models, dict) else {}

    family_lookup = {
        str(family).strip().upper(): value
        for family, value in family_rules.items()
        if str(family).strip()
    } if isinstance(family_rules, dict) else {}

    configured = exact_lookup.get(entry.display_name.casefold())
    if configured is None:
        configured = family_lookup.get(entry.family.upper())
    if configured is None:
        configured = measurement_rules.get("default", ["N/A"])

    lines = _as_rule_lines(configured)
    return "\n".join(lines or ["N/A"])


def build_sensor_overview_rows(
    profile: dict[str, Any],
    *,
    sensormap_rules_path: str | Path = DEFAULT_SENSORMAP_RULES_PATH,
    overview_rules_path: str | Path = DEFAULT_SENSOR_OVERVIEW_RULES_PATH,
) -> list[tuple[str, str, str, str]]:
    """Build Sensor Overview rows for the first four Word table columns.

    Explicit position descriptions take precedence over numeric quantities:
        3*UFS / 3UFS            -> Left, Center and Right
        UFSL+UFSR+UFSC          -> Left, Center and Right
        4*PAS                   -> B- and C-pillar pairs
        PASBL+PASBR+PASCL+PASCR -> B- and C-pillar pairs
    """

    rules = _load_sensormap_rules(sensormap_rules_path)
    overview_rules = _load_sensor_overview_rules(overview_rules_path)

    inertial_entries = _merge_sensor_entries(
        profile.get("internal_sensor_configuration"),
        force_inertial=True,
    )
    peripheral_entries = _merge_sensor_entries(
        profile.get("peripheral_sensor_configuration"),
        force_inertial=False,
    )

    rows: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()

    for entry in [*inertial_entries, *peripheral_entries]:
        row = (
            entry.display_name,
            _sensor_location(entry, rules),
            _sensor_sensing_direction(entry, overview_rules),
            _sensor_measurement(entry, overview_rules),
        )
        key = (
            row[0].casefold(),
            row[1].casefold(),
            row[2].casefold(),
            row[3].casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)

    return rows



def _three_position_layout_slots(
    family: str,
    positions: set[str],
) -> list[str]:
    order = ("L", "C", "R")
    normalized = {str(position or "").upper() for position in positions}
    return [
        f"{family}_{position}"
        for position in order
        if position in normalized
    ]


def _pas_layout_slots(positions: set[str]) -> list[str]:
    mapping = {
        "BL": "PAS_B_L",
        "BR": "PAS_B_R",
        "CL": "PAS_C_L",
        "CR": "PAS_C_R",
    }
    normalized = {str(position or "").upper() for position in positions}
    return [
        mapping[position]
        for position in POSITION_ORDER["PAS"]
        if position in normalized
    ]


def _pps_layout_slots(positions: set[str]) -> list[str]:
    mapping = {
        "FL": "PPS_FRONT_L",
        "FR": "PPS_FRONT_R",
        "RL": "PPS_REAR_L",
        "RR": "PPS_REAR_R",
    }
    normalized = {
        _normalize_pps_position(position)
        for position in positions
    }
    return [
        mapping[position]
        for position in POSITION_ORDER["PPS"]
        if position in normalized
    ]


def _layout_text(display_name: str, slot: str) -> str:
    suffixes = {
        "UFS_L": "L",
        "UFS_C": "C",
        "UFS_R": "R",
        "RCS_L": "L",
        "RCS_C": "C",
        "RCS_R": "R",
        "PCS_L": "L",
        "PCS_C": "C",
        "PCS_R": "R",
        "PAS_B_L": "B-L",
        "PAS_B_R": "B-R",
        "PAS_C_L": "C-L",
        "PAS_C_R": "C-R",
        "PPS_FRONT_L": "F-L",
        "PPS_FRONT_R": "F-R",
        "PPS_REAR_L": "R-L",
        "PPS_REAR_R": "R-R",
    }
    suffix = suffixes.get(slot)
    return f"{display_name}-{suffix}" if suffix else display_name



def _normalized_profile_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _profile_value(
    profile: dict[str, Any],
    *candidate_keys: str,
) -> str:
    """Read front-end values even if their key style differs.

    This supports keys such as:
        ECU Direction / ecu_direction / ecuDirection
        UFS direction / ufs_direction / ufsDirection
    """

    if not isinstance(profile, dict):
        return ""

    wanted = {
        _normalized_profile_key(candidate)
        for candidate in candidate_keys
    }
    for key, value in profile.items():
        if _normalized_profile_key(key) not in wanted:
            continue

        if isinstance(value, dict) and "value" in value:
            value = value.get("value")
        if isinstance(value, (list, tuple, set)):
            value = next(
                (
                    str(item).strip()
                    for item in value
                    if str(item).strip()
                ),
                "",
            )
        return str(value or "").strip()

    return ""


def _normalize_direction(
    value: Any,
    *,
    allowed: set[str],
    default: str,
) -> str:
    normalized = str(value or "").strip().casefold()
    aliases = {
        "front": "forward",
        "rear": "backward",
        "back": "backward",
        "normal direction": "normal",
        "reverse direction": "reverse",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in allowed else default


def build_sensor_layout_model(
    profile: dict[str, Any],
    *,
    sensormap_rules_path: str | Path = DEFAULT_SENSORMAP_RULES_PATH,
) -> dict[str, Any]:
    """Create editable sensor labels and their single position marker.

    Marker rules:
    - ECU / internal sensor: blue connector marker only, controlled by
      ECU Direction (forward/backward/left/right).
    - UFS: black locator marker only, controlled by UFS direction
      (normal/reverse).
    - Other peripheral sensors: black locator marker only, fixed toward
      the vehicle exterior by the layout JSON slot configuration.
    """

    rules = _load_sensormap_rules(sensormap_rules_path)
    labels_by_slot: dict[str, list[str]] = {}
    slot_order: list[str] = []

    ecu_direction = _normalize_direction(
        _profile_value(
            profile,
            "ECU Direction",
            "ConnectorDirection",
            "ecu_direction",
            "ecuDirection",
        ),
        allowed={"forward", "backward", "left", "right"},
        default="forward",
    )
    ufs_direction = _normalize_direction(
        _profile_value(
            profile,
            "UFS direction",
            "UFS Direction",
            "ufs_direction",
            "ufsDirection",
        ),
        allowed={"normal", "reverse"},
        default="normal",
    )

    def add_label(
        slot: str,
        text: str,
        *,
        marker_type: str,
        marker_state: str,
    ) -> None:
        if slot not in labels_by_slot:
            labels_by_slot[slot] = []
            slot_order.append(slot)
        if text not in labels_by_slot[slot]:
            labels_by_slot[slot].append(text)

        marker_by_slot[slot] = {
            "type": marker_type,
            "state": marker_state,
        }

    marker_by_slot: dict[str, dict[str, str]] = {}

    inertial_entries = _merge_sensor_entries(
        profile.get("internal_sensor_configuration"),
        force_inertial=True,
    )
    inertial_text = [
        entry.display_name
        for entry in inertial_entries
        if entry.display_name
    ]
    if inertial_text:
        add_label(
            "ECU",
            "\r".join(inertial_text),
            marker_type="connector",
            marker_state=ecu_direction,
        )

    peripheral_entries = _merge_sensor_entries(
        profile.get("peripheral_sensor_configuration"),
        force_inertial=False,
    )

    for entry in peripheral_entries:
        family = entry.family
        slots: list[str] = []

        if family in {"UFS", "RCS", "PCS"}:
            fallback = 1 if family == "PCS" else 2
            positions = entry.positions or _three_position_set_from_count(
                _default_count(entry, rules, fallback=fallback)
            )
            slots = _three_position_layout_slots(family, positions)

        elif family == "PAS":
            positions = entry.positions or _pas_positions_from_count(
                _default_count(entry, rules, fallback=2),
                rules,
            )
            slots = _pas_layout_slots(positions)

        elif family == "PPS":
            positions = {
                _normalize_pps_position(position)
                for position in entry.positions
            }
            if not positions:
                positions = _pps_positions_from_count(
                    _default_count(entry, rules, fallback=2)
                )
            slots = _pps_layout_slots(positions)

        elif family == "PTS":
            slots = ["PTS_C"]

        for slot in slots:
            if family == "UFS":
                marker_type = "locator"
                marker_state = ufs_direction
            else:
                marker_type = "locator"
                marker_state = "outward"

            add_label(
                slot,
                _layout_text(entry.display_name, slot),
                marker_type=marker_type,
                marker_state=marker_state,
            )

    labels = [
        {
            "slot": slot,
            "text": "\r".join(labels_by_slot[slot]),
            "marker": marker_by_slot[slot],
        }
        for slot in slot_order
    ]
    return {
        "labels": labels,
        "ecu_direction": ecu_direction,
        "ufs_direction": ufs_direction,
    }


def parse_sensor_types(value: Any) -> list[str]:
    """Backward-compatible helper used by earlier tests or imports."""

    entries = _merge_sensor_entries(
        value,
        force_inertial=False,
    )
    return [entry.display_name for entry in entries]


def build_sensor_type_rows(profile: dict[str, Any]) -> list[str]:
    """Backward-compatible first-column-only helper."""

    return [
        row[0]
        for row in build_sensor_overview_rows(profile)
    ]


def _iter_tables(container) -> Iterator[Any]:
    """Yield top-level and nested Word tables."""

    for table in container.tables:
        yield table
        for row in table.rows:
            for cell in row.cells:
                yield from _iter_tables(cell)


def _cell_xml(row_xml, cell_index: int):
    cells = [
        child
        for child in row_xml
        if str(getattr(child, "tag", "")).endswith("}tc")
    ]
    if cell_index < 0 or cell_index >= len(cells):
        return None
    return cells[cell_index]


def _replace_placeholder_in_cell_xml(
    row_xml,
    *,
    cell_index: int,
    placeholder: str,
    replacement: str,
) -> None:
    cell_xml = _cell_xml(row_xml, cell_index)
    if cell_xml is None:
        raise HTTPException(
            status_code=500,
            detail=(
                "TCD09 Sensor Overview template row does not contain "
                f"column #{cell_index + 1}."
            ),
        )

    text_nodes = [
        node
        for node in cell_xml.iter()
        if str(getattr(node, "tag", "")).endswith("}t")
    ]
    if not text_nodes:
        raise HTTPException(
            status_code=500,
            detail=(
                "TCD09 Sensor Overview template cell has no text node: "
                f"{placeholder}"
            ),
        )

    full_text = "".join(str(node.text or "") for node in text_nodes)
    if placeholder not in full_text:
        raise HTTPException(
            status_code=500,
            detail=(
                "TCD09 Sensor Overview placeholder is split or missing: "
                f"{placeholder}"
            ),
        )

    updated_text = full_text.replace(placeholder, replacement, 1)
    normalized_text = (
        updated_text
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    lines = normalized_text.split("\n")

    first_text_node = text_nodes[0]
    first_text_node.text = lines[0]

    # Clear the remaining original text nodes because the complete cell text
    # has been consolidated into the first run.
    for node in text_nodes[1:]:
        node.text = ""

    if len(lines) > 1:
        parent_run = first_text_node.getparent()
        if parent_run is None:
            raise HTTPException(
                status_code=500,
                detail=(
                    "TCD09 Sensor Overview template text node has no run: "
                    f"{placeholder}"
                ),
            )

        namespace = str(first_text_node.tag).split("}")[0].lstrip("{")
        insert_index = parent_run.index(first_text_node) + 1

        for line in lines[1:]:
            break_node = first_text_node.makeelement(
                f"{{{namespace}}}br",
            )
            line_node = first_text_node.makeelement(
                f"{{{namespace}}}t",
            )
            line_node.text = line

            parent_run.insert(insert_index, break_node)
            insert_index += 1
            parent_run.insert(insert_index, line_node)
            insert_index += 1


def _find_sensor_template_rows(document) -> list[tuple[Any, Any]]:
    matches: list[tuple[Any, Any]] = []

    for table in _iter_tables(document):
        for row in list(table.rows):
            if len(row.cells) < 4:
                continue

            first_text = str(row.cells[0].text or "")
            second_text = str(row.cells[1].text or "")
            third_text = str(row.cells[2].text or "")
            fourth_text = str(row.cells[3].text or "")

            if (
                SENSOR_TYPE_ROWS_PLACEHOLDER in first_text
                and SENSOR_LOCATION_ROWS_PLACEHOLDER in second_text
                and SENSOR_DIRECTION_ROWS_PLACEHOLDER in third_text
                and SENSOR_MEASUREMENT_ROWS_PLACEHOLDER in fourth_text
            ):
                matches.append((table, row))

    return matches


def _expand_template_row(
    table,
    template_row,
    rows: list[tuple[str, str, str, str]],
) -> int:
    template_xml = template_row._tr
    values = rows or [("N/A", "N/A", "N/A", "N/A")]

    for (
        sensor_type,
        sensor_location,
        sensor_direction,
        sensor_measurement,
    ) in values:
        copied_row_xml = deepcopy(template_xml)

        _replace_placeholder_in_cell_xml(
            copied_row_xml,
            cell_index=0,
            placeholder=SENSOR_TYPE_ROWS_PLACEHOLDER,
            replacement=sensor_type,
        )
        _replace_placeholder_in_cell_xml(
            copied_row_xml,
            cell_index=1,
            placeholder=SENSOR_LOCATION_ROWS_PLACEHOLDER,
            replacement=sensor_location,
        )
        _replace_placeholder_in_cell_xml(
            copied_row_xml,
            cell_index=2,
            placeholder=SENSOR_DIRECTION_ROWS_PLACEHOLDER,
            replacement=sensor_direction,
        )
        _replace_placeholder_in_cell_xml(
            copied_row_xml,
            cell_index=3,
            placeholder=SENSOR_MEASUREMENT_ROWS_PLACEHOLDER,
            replacement=sensor_measurement,
        )

        template_xml.addprevious(copied_row_xml)

    table._tbl.remove(template_xml)
    return len(values)


def fill_tcd09_sensor_type_rows(
    profile: dict[str, Any],
    source: str | Path | io.BytesIO,
) -> io.BytesIO:
    """Fill all four Sensor Overview columns.

    The Word template row must contain:
        column 1: <TCD09_SENSOR_TYPE_ROWS>
        column 2: <TCD09_SENSOR_LOCATION_ROWS>
        column 3: <TCD09_SENSOR_DIRECTION_ROWS>
        column 4: <TCD09_SENSOR_MEASUREMENT_ROWS>

    The whole template row is copied once per normalized sensor family/model,
    preserving borders, row height, cell width and formatting.
    """

    try:
        document = docx.Document(source)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "Unable to open TCD09 Word template for Sensor Overview: "
                f"{exc}"
            ),
        ) from exc

    template_rows = _find_sensor_template_rows(document)
    if not template_rows:
        raise HTTPException(
            status_code=400,
            detail=(
                "TCD09 Sensor Overview template row was not found. "
                "Place <TCD09_SENSOR_TYPE_ROWS> in column 1, "
                "<TCD09_SENSOR_LOCATION_ROWS> in column 2, "
                "<TCD09_SENSOR_DIRECTION_ROWS> in column 3 and "
                "<TCD09_SENSOR_MEASUREMENT_ROWS> in column 4 "
                "of the same row."
            ),
        )

    overview_rows = build_sensor_overview_rows(profile)

    for table, template_row in template_rows:
        _expand_template_row(
            table,
            template_row,
            overview_rows,
        )

    output = io.BytesIO()
    document.save(output)
    output.seek(0)
    return output
