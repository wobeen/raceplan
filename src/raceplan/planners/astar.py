"""A* planner with a consistent Euclidean heuristic."""

from raceplan.common import OccupancyGrid, PlannerResult, Pose2D

from ._grid_search import euclidean, search_grid
from .base import Planner


class AStarPlanner(Planner):
    @property
    def name(self) -> str:
        return "astar"

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
            heuristic=euclidean,
            timeout_s=timeout_s,
            algorithm=self.name,
        )

