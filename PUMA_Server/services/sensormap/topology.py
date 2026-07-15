from __future__ import annotations

from typing import Any, Mapping

from .errors import SensorMapSectionError
from .models import SensorRequest, SensorSelection


def _effective_axes(
    request: SensorRequest,
    rule: Mapping[str, Any],
) -> tuple[frozenset[str], list[str]]:
    supported = {
        str(axis).upper()
        for axis in rule.get("supported_axes", [])
    }
    default_axes = {
        str(axis).upper()
        for axis in rule.get("default_axes", ["X"])
    }

    requested = set(request.axes or default_axes)
    effective = requested & supported
    warnings: list[str] = []

    if requested - supported:
        warnings.append(
            f"{request.sensor}: unsupported axes "
            f"{sorted(requested - supported)} were ignored."
        )

    if not effective:
        effective = default_axes & supported

    if not effective:
        raise SensorMapSectionError(
            f"{request.sensor}: no usable axis remains after normalization."
        )

    return frozenset(effective), warnings


def _resolve_three_position(
    request: SensorRequest,
    rule: Mapping[str, Any],
) -> tuple[frozenset[str], str, list[str]]:
    warnings: list[str] = []

    if request.side_hints:
        positions = set(request.side_hints)
        if positions == {"LEFT", "RIGHT"}:
            normalized = f"2*{request.sensor}"
        elif positions == {"CENTRE"}:
            normalized = request.sensor
        else:
            normalized = "+".join(sorted(positions))
        return frozenset(positions), normalized, warnings

    count = request.count or int(rule.get("default_count", 1))

    if count <= 1:
        positions = {"CENTRE"}
        normalized = request.sensor
    elif count == 2:
        positions = {"LEFT", "RIGHT"}
        normalized = f"2*{request.sensor}"
    else:
        positions = {"LEFT", "CENTRE", "RIGHT"}
        normalized = f"3*{request.sensor}"
        if count > 3:
            warnings.append(
                f"{request.sensor}: count {count} exceeds three-position "
                "capacity and was clamped to 3."
            )

    return frozenset(positions), normalized, warnings


def _resolve_symmetric_levels(
    request: SensorRequest,
    rule: Mapping[str, Any],
) -> tuple[frozenset[str], str, list[str]]:
    max_level = int(rule.get("max_level", 1))
    warnings: list[str] = []

    if request.level_hints:
        positions: set[str] = set()
        valid_levels: list[int] = []
        for level in request.level_hints:
            if 1 <= level <= max_level:
                valid_levels.append(level)
                positions.update({f"L{level}", f"R{level}"})
            else:
                warnings.append(
                    f"{request.sensor}: level {level} exceeds max_level "
                    f"{max_level} and was ignored."
                )

        if positions:
            normalized = "+".join(
                f"{request.sensor}{level}"
                for level in valid_levels
            )
            return frozenset(positions), normalized, warnings

    if request.side_hints:
        # No level was supplied. Use the nearest symmetric pair.
        positions: set[str] = set()
        if "LEFT" in request.side_hints:
            positions.add("L1")
        if "RIGHT" in request.side_hints:
            positions.add("R1")
        if "CENTRE" in request.side_hints:
            positions.add("C0")

        if positions:
            warnings.append(
                f"{request.sensor}: side-only notation was mapped to the "
                "nearest available positions."
            )
            normalized = "+".join(sorted(positions))
            return frozenset(positions), normalized, warnings

    max_count = max_level * 2 + 1
    count = request.count or int(rule.get("default_count", 1))

    if count < 1:
        count = 1
    if count > max_count:
        warnings.append(
            f"{request.sensor}: count {count} exceeds capacity {max_count} "
            f"and was clamped."
        )
        count = max_count

    side_count = count // 2
    positions = {
        f"{side}{level}"
        for level in range(1, side_count + 1)
        for side in ("L", "R")
    }

    if count % 2 == 1:
        positions.add("C0")

    normalized = f"{count}*{request.sensor}"
    return frozenset(positions), normalized, warnings


def _resolve_fixed_positions(
    request: SensorRequest,
    rule: Mapping[str, Any],
) -> tuple[frozenset[str], str, list[str]]:
    positions = {
        str(item).upper()
        for item in rule.get("positions", [])
    }
    return frozenset(positions), request.sensor, []


def resolve_sensor_selections(
    requests: Mapping[str, SensorRequest],
    sensor_rules: Mapping[str, Mapping[str, Any]],
) -> dict[str, SensorSelection]:
    selections: dict[str, SensorSelection] = {}

    for code, request in requests.items():
        rule = sensor_rules[code]
        topology = rule.get("topology")

        if topology == "three_position":
            positions, normalized, warnings = _resolve_three_position(
                request, rule
            )
        elif topology == "symmetric_levels":
            positions, normalized, warnings = _resolve_symmetric_levels(
                request, rule
            )
        elif topology == "fixed_positions":
            positions, normalized, warnings = _resolve_fixed_positions(
                request, rule
            )
        else:
            raise SensorMapSectionError(
                f"{code}: unsupported topology {topology!r}."
            )

        axes, axis_warnings = _effective_axes(request, rule)

        # Preserve XY in normalized text only when Y survives capability checks.
        if axes == {"X", "Y"} and not normalized.endswith("XY"):
            normalized += "XY"

        selections[code] = SensorSelection(
            sensor=code,
            positions=positions,
            axes=axes,
            normalized_input=normalized,
            matched_by="semantic",
            warnings=tuple([*warnings, *axis_warnings]),
        )

    return selections
