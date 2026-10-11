"""Dependency-light data types shared by planners and experiments."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from typing import Mapping


@dataclass(frozen=True, slots=True)
class Pose2D:
    """Planar pose in metres and radians."""

    x: float
    y: float
    yaw: float = 0.0

    def __post_init__(self) -> None:
        if not all(isfinite(value) for value in (self.x, self.y, self.yaw)):
            raise ValueError("pose values must be finite")


@dataclass(frozen=True, slots=True)
class Path:
    """Ordered poses and the accumulated planner cost."""

    poses: tuple[Pose2D, ...]
    cost: float

    def __post_init__(self) -> None:
        if not self.poses:
            raise ValueError("a path must contain at least one pose")
        if not isfinite(self.cost) or self.cost < 0:
            raise ValueError("path cost must be finite and non-negative")


class PlannerStatus(StrEnum):
    SUCCESS = "success"
    NO_PATH = "no_path"
    INVALID_START = "invalid_start"
    INVALID_GOAL = "invalid_goal"
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class PlannerResult:
    """Uniform planner output, including failures as first-class results."""

    status: PlannerStatus
    path: Path | None = None
    expanded_nodes: int = 0
    planning_time_s: float = 0.0
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.expanded_nodes < 0:
            raise ValueError("expanded_nodes cannot be negative")
        if not isfinite(self.planning_time_s) or self.planning_time_s < 0:
            raise ValueError("planning_time_s must be finite and non-negative")
        if self.status is PlannerStatus.SUCCESS and self.path is None:
            raise ValueError("successful planning requires a path")
        if self.status is not PlannerStatus.SUCCESS and self.path is not None:
            raise ValueError("failed planning cannot contain a path")

