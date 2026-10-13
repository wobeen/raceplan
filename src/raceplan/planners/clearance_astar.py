"""Validation-tuned clearance-cost A*, with zero-weight baseline ablation."""
from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count
from math import isfinite
from time import perf_counter
from raceplan.common import OccupancyGrid,Path,PlannerResult,PlannerStatus,Pose2D
from raceplan.common.grid import GridIndex
from raceplan.common.planning_space import center_clearance
from ._grid_search import _neighbours,_reconstruct_path,euclidean,Heuristic
from .base import Planner

@dataclass(frozen=True)
class ClearanceConfig:
    weight: float

class ClearanceAStar(Planner):
    def __init__(self,weight):
        if not isfinite(weight) or weight<0:raise ValueError('weight must be finite and nonnegative')
        self.config=ClearanceConfig(weight)
    @property
    def name(self):return f'clearance_{self.config.weight}'
    def plan(self,grid,start,goal,*,timeout_s=None):
        return search_grid(grid,start,goal,timeout_s=timeout_s,algorithm=self.name,
                           heuristic=euclidean,weight=self.config.weight)

def search_grid(
    grid: OccupancyGrid,
    start: Pose2D,
    goal: Pose2D,
    *,
    heuristic: Heuristic,
    timeout_s: float | None,
    algorithm: str,
    weight: float,
) -> PlannerResult:
    """Run a best-first grid search with shared validation and accounting."""

    if timeout_s is not None and timeout_s < 0:
        raise ValueError("timeout_s cannot be negative")

    started_at = perf_counter()
    clearance = center_clearance(grid) if weight else None
    start_cell = grid.world_to_grid(start.x, start.y)
    goal_cell = grid.world_to_grid(goal.x, goal.y)

    def result(
        status: PlannerStatus,
        *,
        path: Path | None = None,
        expanded_nodes: int = 0,
    ) -> PlannerResult:
        return PlannerResult(
            status=status,
            path=path,
            expanded_nodes=expanded_nodes,
            planning_time_s=perf_counter() - started_at,
            metadata={"algorithm": algorithm},
        )

    if not grid.is_free(start_cell):
        return result(PlannerStatus.INVALID_START)
    if not grid.is_free(goal_cell):
        return result(PlannerStatus.INVALID_GOAL)

    frontier: list[tuple[float, float, int, GridIndex]] = []
    insertion_order = count()
    heappush(frontier, (heuristic(start_cell, goal_cell), 0.0, next(insertion_order), start_cell))
    best_cost: dict[GridIndex, float] = {start_cell: 0.0}
    came_from: dict[GridIndex, GridIndex] = {}
    expanded_nodes = 0

    while frontier:
        if timeout_s is not None and perf_counter() - started_at >= timeout_s:
            return result(PlannerStatus.TIMEOUT, expanded_nodes=expanded_nodes)

        _, cost_so_far, _, current = heappop(frontier)
        if cost_so_far != best_cost.get(current):
            continue
        expanded_nodes += 1

        if current == goal_cell:
            path = _reconstruct_path(grid, came_from, goal_cell, cost_so_far)
            return result(PlannerStatus.SUCCESS, path=path, expanded_nodes=expanded_nodes)

        for neighbour, step_cost in _neighbours(grid, current):
            penalty = 0.0 if clearance is None else weight / (float(clearance[neighbour]) + grid.resolution)
            candidate_cost = cost_so_far + step_cost * (1.0 + penalty)
            if candidate_cost >= best_cost.get(neighbour, float("inf")):
                continue
            best_cost[neighbour] = candidate_cost
            came_from[neighbour] = current
            priority = candidate_cost + heuristic(neighbour, goal_cell) * grid.resolution
            heappush(
                frontier,
                (priority, candidate_cost, next(insertion_order), neighbour),
            )

    return result(PlannerStatus.NO_PATH, expanded_nodes=expanded_nodes)

