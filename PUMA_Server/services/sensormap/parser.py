from __future__ import annotations

import re
from typing import Any, Mapping

from .models import SensorRequest


def normalize_scope(value: str | None) -> str:
    text = str(value or "").upper()
    text = text.replace("×", "*")
    text = re.sub(r"\s+", "", text)
    return text


def _sensor_present(scope: str, code: str, aliases: list[str]) -> bool:
    candidates = [code, *aliases]
    return any(
        re.search(
            rf"(?<![A-Z]){re.escape(alias.upper())}",
            scope,
        )
        for alias in candidates
        if alias
    )


def _parse_count(scope: str, code: str) -> int | None:
    match = re.search(
        rf"(?P<count>\d+)\*{re.escape(code)}",
        scope,
    )
    if match:
        return int(match.group("count"))
    return None


def _parse_axes(scope: str, code: str) -> frozenset[str]:
    # XY may appear after the code or after side notation.
    if re.search(rf"{re.escape(code)}(?:[LR])?(?:[_-]?XY)", scope):
        return frozenset({"X", "Y"})
    if re.search(rf"{re.escape(code)}(?:[LR])?(?:[_-]?Y)(?![A-Z])", scope):
        return frozenset({"Y"})
    return frozenset({"X"})


def _parse_side_hints(scope: str, code: str) -> frozenset[str]:
    sides: set[str] = set()
    if re.search(rf"{re.escape(code)}L(?:XY)?", scope):
        sides.add("LEFT")
    if re.search(rf"{re.escape(code)}R(?:XY)?", scope):
        sides.add("RIGHT")
    if re.search(rf"{re.escape(code)}C(?:XY)?", scope):
        sides.add("CENTRE")
    return frozenset(sides)


def _parse_level_hints(scope: str, code: str) -> tuple[int, ...]:
    levels = sorted({
        int(value)
        for value in re.findall(
            rf"{re.escape(code)}([1-9])",
            scope,
        )
    })
    return tuple(levels)


def parse_sensor_requests(
    peripheral_sensor_scope: str | None,
    sensor_rules: Mapping[str, Mapping[str, Any]],
) -> dict[str, SensorRequest]:
    """
    Parse user text into semantic requests.

    This layer intentionally does not decide final Excel positions. It only
    extracts count, axis, side hints and level hints. Topology resolution is
    handled separately.
    """
    raw = str(peripheral_sensor_scope or "")
    normalized = normalize_scope(raw)
    if not normalized:
        return {}

    requests: dict[str, SensorRequest] = {}

    for raw_code, rule in sensor_rules.items():
        code = str(raw_code).upper().strip()
        aliases = [
            str(item).upper().strip()
            for item in rule.get("aliases", [])
            if str(item).strip()
        ]

        if not _sensor_present(normalized, code, aliases):
            continue

        requests[code] = SensorRequest(
            sensor=code,
            raw=raw,
            count=_parse_count(normalized, code),
            axes=_parse_axes(normalized, code),
            side_hints=_parse_side_hints(normalized, code),
            level_hints=_parse_level_hints(normalized, code),
        )

    return requests
