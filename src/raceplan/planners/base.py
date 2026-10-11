"""Common contract implemented by every RacePlan global planner."""

from __future__ import annotations

from abc import ABC, abstractmethod

from raceplan.common import OccupancyGrid, PlannerResult, Pose2D


class Planner(ABC):
    """Plan collision-free motion on a known occupancy grid."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable identifier used in results and configuration."""

    @abstractmethod
    def plan(
        self,
        grid: OccupancyGrid,
        start: Pose2D,
        goal: Pose2D,
        *,
        timeout_s: float | None = None,
    ) -> PlannerResult:
        """Plan from start to goal without raising for expected failures."""

