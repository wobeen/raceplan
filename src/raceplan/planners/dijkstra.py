"""Dijkstra planner on an 8-connected occupancy grid."""

from raceplan.common import OccupancyGrid, PlannerResult, Pose2D

from ._grid_search import search_grid, zero_heuristic
from .base import Planner


class DijkstraPlanner(Planner):
    @property
    def name(self) -> str:
        return "dijkstra"

    def plan(
        self,
        grid: OccupancyGrid,
        start: Pose2D,
        goal: Pose2D,
        *,
        timeout_s: float | None = None,
    ) -> PlannerResult:
        return search_grid(
            grid,
            start,
            goal,
            heuristic=zero_heuristic,
            timeout_s=timeout_s,
            algorithm=self.name,
        )

