from __future__ import annotations

# 本文件负责解析前端保存的传感器字符串。
# 统一处理数量、连接符、型号与安装位置后缀，供 Overview 和布局模型复用。

import re
from typing import Any

from services.tcd09.sensor_models import (
    INERTIAL_FAMILIES,
    KNOWN_FAMILIES,
    SensorEntry,
)


EMPTY_VALUES = {"", "N/A", "NA", "NULL", "NONE", "0"}
SENSOR_CONNECTOR_PATTERN = re.compile(
    r"\s*(?:[+_\-\uFF0B\uFF0D,;，；/\\\\|]+)\s*"
)
QUANTITY_PATTERN = re.compile(r"^\s*(\d+)\s*\*?\s*(?=[A-Za-z])")


def as_sensor_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return "+".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def normalize_positional_compounds(text: str) -> str:
    """Keep position suffixes such as ``UFS_L`` intact before splitting."""

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
    return re.sub(
        r"(?i)\b(PAS)\s*[_-]\s*(BL|BR|CL|CR)\b",
        lambda match: f"{match.group(1)}{match.group(2)}",
        normalized,
    )


def split_sensor_text(value: Any) -> list[str]:
    raw_text = as_sensor_text(value)
    if raw_text.upper() in EMPTY_VALUES:
        return []
    return [
        part.strip()
        for part in SENSOR_CONNECTOR_PATTERN.split(
            normalize_positional_compounds(raw_text)
        )
        if part.strip()
    ]


def _extract_quantity(token: str) -> tuple[int | None, str]:
    match = QUANTITY_PATTERN.match(token)
    if not match:
        return None, token.strip()
    return int(match.group(1)), token[match.end():].strip()


def _detect_family(token: str) -> tuple[str | None, str]:
    cleaned = re.sub(r"\s+", "", str(token or ""))
    upper = cleaned.upper()
    for family in KNOWN_FAMILIES:
        if upper.startswith(family):
            return family, cleaned[len(family):]
    return None, cleaned


def _remove_position_suffix(family: str, remainder: str) -> tuple[str | None, str]:
    raw = str(remainder or "")
    upper = raw.upper()
    if family == "PAS":
        candidates = ("BL", "BR", "CL", "CR")
    elif family == "PPS":
        candidates = ("FL", "FR", "RL", "RR", "L", "C", "R")
    elif family in {"UFS", "RCS", "PCS"}:
        candidates = ("L", "C", "R")
    else:
        return None, raw

    for position in candidates:
        if upper.startswith(position):
            return position, raw[len(position):]
    for position in candidates:
        if upper.endswith(position) and len(raw) > len(position):
            return position, raw[:-len(position)]
    return None, raw


def _parse_sensor_token(
    raw_token: str,
    *,
    force_inertial: bool,
) -> tuple[str, str, int | None, str | None, bool] | None:
    quantity, token = _extract_quantity(raw_token)
    family, remainder = _detect_family(token)
    if family is None:
        return None
    position, model_remainder = _remove_position_suffix(family, remainder)
    return (
        family,
        f"{family}{model_remainder}".strip() or family,
        quantity,
        position,
        force_inertial or family in INERTIAL_FAMILIES,
    )


def merge_sensor_entries(
    value: Any,
    *,
    force_inertial: bool,
) -> list[SensorEntry]:
    """Parse front-end sensor text into deduplicated family/model entries."""

    entries: dict[tuple[str, str], SensorEntry] = {}
    order: list[tuple[str, str]] = []
    for raw_token in split_sensor_text(value):
        parsed = _parse_sensor_token(raw_token, force_inertial=force_inertial)
        if parsed is None:
            continue
        family, display_name, quantity, position, is_inertial = parsed
        key = (family, display_name.casefold())
        if key not in entries:
            entries[key] = SensorEntry(family, display_name, is_inertial)
            order.append(key)
        entry = entries[key]
        entry.occurrence_count += 1
        if quantity is not None:
            entry.declared_count = max(entry.declared_count, quantity)
        if position:
            entry.positions.add(position)
    return [entries[key] for key in order]


def default_count(entry: SensorEntry, rules: dict[str, Any], fallback: int) -> int:
    if entry.effective_count > 0:
        if (
            entry.effective_count == 1
            and not entry.positions
            and entry.declared_count == 0
        ):
            configured = rules.get(entry.family, {}).get("default_count")
            return configured if isinstance(configured, int) and configured > 0 else fallback
        return entry.effective_count
    configured = rules.get(entry.family, {}).get("default_count")
    return configured if isinstance(configured, int) and configured > 0 else fallback


def three_position_set_from_count(count: int) -> set[str]:
    if count <= 1:
        return {"C"}
    if count == 2:
        return {"L", "R"}
    return {"L", "C", "R"}


def pas_positions_from_count(count: int, rules: dict[str, Any]) -> set[str]:
    selected = rules.get("PAS", {}).get("positions_by_count", {}).get(str(count))
    if isinstance(selected, list) and selected:
        return {str(position).upper() for position in selected if str(position).strip()}
    return {"BL", "BR"} if count <= 2 else {"BL", "BR", "CL", "CR"}


def normalize_pps_position(position: str) -> str:
    return {"L": "FL", "R": "FR", "C": "FL"}.get(
        str(position or "").upper(), str(position or "").upper()
    )


def pps_positions_from_count(count: int) -> set[str]:
    if count <= 1:
        return {"FL"}
    if count == 2:
        return {"FL", "FR"}
    if count == 3:
        return {"FL", "FR", "RL"}
    return {"FL", "FR", "RL", "RR"}
