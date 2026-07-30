from __future__ import annotations

# 本文件定义 TCD09 传感器领域的公共数据模型和基础常量。
# Overview 表格与汽车底图布局共用这些类型，避免重复定义。

from dataclasses import dataclass, field


INERTIAL_FAMILIES = ("SMA", "SMB", "SMI", "SMG", "SMU")
PERIPHERAL_FAMILIES = ("UFS", "RCS", "PAS", "PCS", "PPS", "PTS")
KNOWN_FAMILIES = (*INERTIAL_FAMILIES, *PERIPHERAL_FAMILIES)

POSITION_ORDER = {
    "UFS": ("L", "C", "R"),
    "RCS": ("L", "C", "R"),
    "PCS": ("L", "C", "R"),
    "PPS": ("FL", "FR", "RL", "RR"),
    "PAS": ("BL", "BR", "CL", "CR"),
}


@dataclass
class SensorEntry:
    """One normalized sensor family/model from the front-end configuration."""

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
