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

THIS_DIR = Path(__file__).resolve().parent
SERVER_ROOT = THIS_DIR.parents[1]
DEFAULT_SENSORMAP_RULES_PATH = (
    SERVER_ROOT / "config" / "sensormap_sensor_rules.json"
)

INERTIAL_FAMILIES = ("SMA", "SMB", "SMI", "SMG")
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
    "PPS": ("L", "C", "R"),
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
        r"(?i)\b(UFS|RCS|PCS|PPS)\s*[_-]\s*([LCR])\b",
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
    elif family in {"UFS", "RCS", "PCS", "PPS"}:
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
        positions = entry.positions
        if not positions:
            count = _default_count(entry, rules, fallback=2)
            positions = _three_position_set_from_count(
                1 if count <= 1 else 2
            )
        return _format_three_positions(positions, "Front door")

    if family == "PTS":
        return "Front bumper"

    return "N/A"


def build_sensor_overview_rows(
    profile: dict[str, Any],
    *,
    sensormap_rules_path: str | Path = DEFAULT_SENSORMAP_RULES_PATH,
) -> list[tuple[str, str]]:
    """Build Sensor Overview rows for the first two Word table columns.

    Explicit position descriptions take precedence over numeric quantities:
        3*UFS / 3UFS            -> Left, Center and Right
        UFSL+UFSR+UFSC          -> Left, Center and Right
        4*PAS                   -> B- and C-pillar pairs
        PASBL+PASBR+PASCL+PASCR -> B- and C-pillar pairs
    """

    rules = _load_sensormap_rules(sensormap_rules_path)

    inertial_entries = _merge_sensor_entries(
        profile.get("internal_sensor_configuration"),
        force_inertial=True,
    )
    peripheral_entries = _merge_sensor_entries(
        profile.get("peripheral_sensor_configuration"),
        force_inertial=False,
    )

    rows: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for entry in [*inertial_entries, *peripheral_entries]:
        row = (
            entry.display_name,
            _sensor_location(entry, rules),
        )
        key = (row[0].casefold(), row[1].casefold())
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)

    return rows


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
        sensor_type
        for sensor_type, _ in build_sensor_overview_rows(profile)
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
    text_nodes[0].text = updated_text
    for node in text_nodes[1:]:
        node.text = ""


def _find_sensor_template_rows(document) -> list[tuple[Any, Any]]:
    matches: list[tuple[Any, Any]] = []

    for table in _iter_tables(document):
        for row in list(table.rows):
            if len(row.cells) < 2:
                continue

            first_text = str(row.cells[0].text or "")
            second_text = str(row.cells[1].text or "")

            if (
                SENSOR_TYPE_ROWS_PLACEHOLDER in first_text
                and SENSOR_LOCATION_ROWS_PLACEHOLDER in second_text
            ):
                matches.append((table, row))

    return matches


def _expand_template_row(
    table,
    template_row,
    rows: list[tuple[str, str]],
) -> int:
    template_xml = template_row._tr
    values = rows or [("N/A", "N/A")]

    for sensor_type, sensor_location in values:
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

        template_xml.addprevious(copied_row_xml)

    table._tbl.remove(template_xml)
    return len(values)


def fill_tcd09_sensor_type_rows(
    profile: dict[str, Any],
    source: str | Path | io.BytesIO,
) -> io.BytesIO:
    """Fill Sensor Overview Sensor Type and Sensor Location columns.

    The Word template row must contain:
        column 1: <TCD09_SENSOR_TYPE_ROWS>
        column 2: <TCD09_SENSOR_LOCATION_ROWS>

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
                "Place <TCD09_SENSOR_TYPE_ROWS> in column 1 and "
                "<TCD09_SENSOR_LOCATION_ROWS> in column 2 of the same row."
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
