from __future__ import annotations

# 本文件负责把传感器配置转换为汽车底图所需的 slot、标签和 marker 数据。
# 包含 ECU/UFS 方向及外围传感器朝外规则，不直接操作 Word。

import re
from pathlib import Path
from typing import Any

from services.tcd09.sensor_models import POSITION_ORDER
from services.tcd09.sensor_parser import (
    default_count,
    merge_sensor_entries,
    normalize_pps_position,
    pas_positions_from_count,
    pps_positions_from_count,
    three_position_set_from_count,
)
THIS_DIR = Path(__file__).resolve().parent
SERVER_ROOT = THIS_DIR.parents[1]
DEFAULT_SENSORMAP_RULES_PATH = SERVER_ROOT / "config" / "sensormap_sensor_rules.json"


def _load_sensormap_rules(
    rules_path: str | Path = DEFAULT_SENSORMAP_RULES_PATH,
) -> dict[str, Any]:
    path = Path(rules_path)
    if not path.is_file():
        return {}
    try:
        import json

        with path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _normalized_profile_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _profile_value(profile: dict[str, Any], *candidate_keys: str) -> str:
    wanted = {_normalized_profile_key(candidate) for candidate in candidate_keys}
    for key, value in profile.items() if isinstance(profile, dict) else ():
        if _normalized_profile_key(key) not in wanted:
            continue
        if isinstance(value, dict) and "value" in value:
            value = value.get("value")
        if isinstance(value, (list, tuple, set)):
            value = next((str(item).strip() for item in value if str(item).strip()), "")
        return str(value or "").strip()
    return ""


def _normalize_direction(value: Any, *, allowed: set[str], default: str) -> str:
    aliases = {
        "front": "forward",
        "rear": "backward",
        "back": "backward",
        "normal direction": "normal",
        "reverse direction": "reverse",
    }
    normalized = aliases.get(str(value or "").strip().casefold(), str(value or "").strip().casefold())
    return normalized if normalized in allowed else default


def _three_position_layout_slots(family: str, positions: set[str]) -> list[str]:
    normalized = {str(position or "").upper() for position in positions}
    return [f"{family}_{position}" for position in ("L", "C", "R") if position in normalized]


def _pas_layout_slots(positions: set[str]) -> list[str]:
    mapping = {"BL": "PAS_B_L", "BR": "PAS_B_R", "CL": "PAS_C_L", "CR": "PAS_C_R"}
    normalized = {str(position or "").upper() for position in positions}
    return [mapping[position] for position in POSITION_ORDER["PAS"] if position in normalized]


def _pps_layout_slots(positions: set[str]) -> list[str]:
    mapping = {"FL": "PPS_FRONT_L", "FR": "PPS_FRONT_R", "RL": "PPS_REAR_L", "RR": "PPS_REAR_R"}
    normalized = {normalize_pps_position(position) for position in positions}
    return [mapping[position] for position in POSITION_ORDER["PPS"] if position in normalized]


def _pts_layout_slots(count: int) -> list[str]:
    """Convert PTS quantity into left/center/right drawing slots.

    1 PTS -> center
    2 PTS -> right and left
    3+ PTS -> right, center and left
    """

    normalized_count = max(1, int(count or 1))
    if normalized_count == 1:
        return ["PTS_C"]
    if normalized_count == 2:
        return ["PTS_R", "PTS_L"]
    return ["PTS_R", "PTS_C", "PTS_L"]


def _layout_text(display_name: str, slot: str) -> str:
    suffixes = {
        "UFS_L": "D", "UFS_C": "C", "UFS_R": "P",
        "RCS_L": "D", "RCS_C": "C", "RCS_R": "P",
        "PCS_L": "D", "PCS_C": "C", "PCS_R": "P",
        "PTS_L": "D", "PTS_C": "C", "PTS_R": "P",
        "PAS_B_L": "B-D", "PAS_B_R": "B-P",
        "PAS_C_L": "C-D", "PAS_C_R": "C-P",
        "PPS_FRONT_L": "D", "PPS_FRONT_R": "P",
        "PPS_REAR_L": "D", "PPS_REAR_R": "P",
    }
    return f"{display_name}-{suffixes[slot]}" if slot in suffixes else display_name


def build_sensor_layout_model(
    profile: dict[str, Any],
    *,
    sensormap_rules_path: str | Path = DEFAULT_SENSORMAP_RULES_PATH,
) -> dict[str, Any]:
    """Build Word-label slots and their single directional marker metadata."""

    rules = _load_sensormap_rules(sensormap_rules_path)
    labels_by_slot: dict[str, list[str]] = {}
    marker_by_slot: dict[str, dict[str, str]] = {}
    slot_order: list[str] = []
    ecu_direction = _normalize_direction(
        _profile_value(profile, "ECU Direction", "ConnectorDirection", "ecu_direction", "ecuDirection"),
        allowed={"forward", "backward", "left", "right"},
        default="forward",
    )
    ufs_direction = _normalize_direction(
        _profile_value(profile, "UFS direction", "UFS Direction", "ufs_direction", "ufsDirection"),
        allowed={"normal", "reverse"},
        default="normal",
    )

    def add_label(
        slot: str,
        text: str,
        marker_type: str | None,
        marker_state: str,
    ) -> None:
        if slot not in labels_by_slot:
            labels_by_slot[slot] = []
            slot_order.append(slot)
        if text not in labels_by_slot[slot]:
            labels_by_slot[slot].append(text)
        if marker_type:
            marker_by_slot[slot] = {"type": marker_type, "state": marker_state}

    inertial_entries = merge_sensor_entries(
        profile.get("internal_sensor_configuration"), force_inertial=True
    )
    inertial_text = [entry.display_name for entry in inertial_entries if entry.display_name]
    if inertial_text:
        add_label("ECU", "\r".join(inertial_text), "connector", ecu_direction)

    for entry in merge_sensor_entries(
        profile.get("peripheral_sensor_configuration"), force_inertial=False
    ):
        family = entry.family
        if family in {"UFS", "RCS", "PCS"}:
            positions = entry.positions or three_position_set_from_count(
                default_count(entry, rules, fallback=1 if family == "PCS" else 2)
            )
            slots = _three_position_layout_slots(family, positions)
        elif family == "PAS":
            positions = entry.positions or pas_positions_from_count(
                default_count(entry, rules, fallback=2), rules
            )
            slots = _pas_layout_slots(positions)
        elif family == "PPS":
            positions = {normalize_pps_position(position) for position in entry.positions}
            if not positions:
                positions = pps_positions_from_count(default_count(entry, rules, fallback=2))
            slots = _pps_layout_slots(positions)
        elif family == "PTS":
            slots = _pts_layout_slots(
                default_count(entry, rules, fallback=1)
            )
        else:
            slots = []

        for slot in slots:
            add_label(
                slot,
                _layout_text(entry.display_name, slot),
                None if family in {"PPS", "PTS"} else "locator",
                ufs_direction if family == "UFS" else "outward",
            )

    return {
        "labels": [
            {
                "slot": slot,
                "text": "\r".join(labels_by_slot[slot]),
                "marker": marker_by_slot.get(slot),
            }
            for slot in slot_order
        ],
        "ecu_direction": ecu_direction,
        "ufs_direction": ufs_direction,
    }
