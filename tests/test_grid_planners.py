from math import sqrt

import numpy as np
import pytest

from raceplan.common import OccupancyGrid, PlannerStatus, Pose2D
from raceplan.planners import AStarPlanner, DijkstraPlanner


@pytest.mark.parametrize("planner", [DijkstraPlanner(), AStarPlanner()])
def test_finds_shortest_path_on_empty_grid(planner) -> None:
    grid = OccupancyGrid(np.zeros((5, 5), dtype=bool), resolution=0.5)

    result = planner.plan(grid, Pose2D(0.25, 0.25), Pose2D(2.25, 2.25))

    assert result.status is PlannerStatus.SUCCESS
    assert result.path is not None
    assert result.path.cost == pytest.approx(4 * sqrt(2) * 0.5)
    assert len(result.path.poses) == 5


def test_astar_and_dijkstra_return_same_optimal_cost() -> None:
    occupied = np.zeros((8, 8), dtype=bool)
    occupied[1:7, 3] = True
    occupied[4, 3] = False
    grid = OccupancyGrid(occupied, resolution=0.2)
    start = Pose2D(0.1, 0.1)
    goal = Pose2D(1.5, 1.5)

    dijkstra = DijkstraPlanner().plan(grid, start, goal)
    astar = AStarPlanner().plan(grid, start, goal)

    assert dijkstra.status is PlannerStatus.SUCCESS
    assert astar.status is PlannerStatus.SUCCESS
    assert dijkstra.path is not None and astar.path is not None
    assert astar.path.cost == pytest.approx(dijkstra.path.cost)
    assert astar.expanded_nodes <= dijkstra.expanded_nodes


@pytest.mark.parametrize("planner", [DijkstraPlanner(), AStarPlanner()])
def test_diagonal_corner_cutting_is_rejected(planner) -> None:
    occupied = np.array([[False, True], [True, False]])
    grid = OccupancyGrid(occupied, resolution=1.0)

    result = planner.plan(grid, Pose2D(0.5, 0.5), Pose2D(1.5, 1.5))

    assert result.status is PlannerStatus.NO_PATH
    assert result.path is None


@pytest.mark.parametrize("planner", [DijkstraPlanner(), AStarPlanner()])
def test_reports_invalid_start_and_goal(planner) -> None:
    occupied = np.zeros((2, 2), dtype=bool)
    occupied[0, 0] = True
    grid = OccupancyGrid(occupied, resolution=1.0)

    invalid_start = planner.plan(grid, Pose2D(0.5, 0.5), Pose2D(1.5, 1.5))
    invalid_goal = planner.plan(grid, Pose2D(1.5, 1.5), Pose2D(0.5, 0.5))

    assert invalid_start.status is PlannerStatus.INVALID_START
    assert invalid_goal.status is PlannerStatus.INVALID_GOAL


@pytest.mark.parametrize("planner", [DijkstraPlanner(), AStarPlanner()])
def test_zero_timeout_is_reported(planner) -> None:
    grid = OccupancyGrid(np.zeros((3, 3), dtype=bool), resolution=1.0)

    result = planner.plan(
        grid,
        Pose2D(0.5, 0.5),
        Pose2D(2.5, 2.5),
        timeout_s=0.0,
    )

    assert result.status is PlannerStatus.TIMEOUT
    assert result.expanded_nodes == 0

