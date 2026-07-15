from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SensorRequest:
    sensor: str
    raw: str
    count: int | None = None
    axes: frozenset[str] = frozenset()
    side_hints: frozenset[str] = frozenset()
    level_hints: tuple[int, ...] = ()
    matched_by: str = "parsed"
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SensorSelection:
    sensor: str
    positions: frozenset[str]
    axes: frozenset[str]
    normalized_input: str
    matched_by: str = "parsed"
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "sensor": self.sensor,
            "positions": sorted(self.positions),
            "axes": sorted(self.axes),
            "normalized_input": self.normalized_input,
            "matched_by": self.matched_by,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class SectionLocation:
    sensor_code: str
    start_row: int
    end_row: int
    title: str


@dataclass(frozen=True)
class SensorRow:
    row_number: int
    sensor: str
    position: str | None
    axis: str | None
    text: str


@dataclass
class SensorFilterResult:
    sensor: str
    deleted_rows: list[dict[str, Any]] = field(default_factory=list)
    selection: dict[str, Any] = field(default_factory=dict)
