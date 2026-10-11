"""Shared implementation details for comparable grid searches."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from heapq import heappop, heappush
from itertools import count
from math import hypot, sqrt
from time import perf_counter

from raceplan.common import OccupancyGrid, Path, PlannerResult, PlannerStatus, Pose2D
from raceplan.common.grid import GridIndex

Heuristic = Callable[[GridIndex, GridIndex], float]

_CARDINAL_COST = 1.0
_DIAGONAL_COST = sqrt(2.0)
_MOVES: tuple[tuple[int, int, float], ...] = (
    (-1, 0, _CARDINAL_COST),
    (0, -1, _CARDINAL_COST),
    (0, 1, _CARDINAL_COST),
    (1, 0, _CARDINAL_COST),
    (-1, -1, _DIAGONAL_COST),
    (-1, 1, _DIAGONAL_COST),
    (1, -1, _DIAGONAL_COST),
    (1, 1, _DIAGONAL_COST),
)


def euclidean(cell: GridIndex, goal: GridIndex) -> float:
    return hypot(goal[0] - cell[0], goal[1] - cell[1])


def zero_heuristic(cell: GridIndex, goal: GridIndex) -> float:
    del cell, goal
    return 0.0


def _neighbours(grid: OccupancyGrid, cell: GridIndex) -> Iterator[tuple[GridIndex, float]]:
    row, column = cell
    for d_row, d_column, cost in _MOVES:
        neighbour = row + d_row, column + d_column
        if not grid.is_free(neighbour):
            continue
        if d_row and d_column:
            # A diagonal move may not squeeze between two touching obstacles.
            if not grid.is_free((row + d_row, column)):
                continue
            if not grid.is_free((row, column + d_column)):
                continue
        yield neighbour, cost * grid.resolution


def _reconstruct_path(
    grid: OccupancyGrid,
    came_from: dict[GridIndex, GridIndex],
    goal: GridIndex,
    cost: float,
) -> Path:
    cells = [goal]
    while cells[-1] in came_from:
        cells.append(came_from[cells[-1]])
    cells.reverse()
    return Path(tuple(grid.grid_to_world(cell) for cell in cells), cost=cost)


def search_grid(
    grid: OccupancyGrid,
    start: Pose2D,
    goal: Pose2D,
    *,
    heuristic: Heuristic,
    timeout_s: float | None,
    algorithm: str,
) -> PlannerResult:
    """Run a best-first grid search with shared validation and accounting."""

    if timeout_s is not None and timeout_s < 0:
        raise ValueError("timeout_s cannot be negative")

    started_at = perf_counter()
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
            candidate_cost = cost_so_far + step_cost
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

