"""Contract checks for the collision-checked A* smoothing development candidate."""
import sys
from math import atan2
from pathlib import Path

import numpy as np
import pytest

from raceplan.common import OccupancyGrid, PlannerStatus, Pose2D
from raceplan.defaults import baseline_vehicle
from raceplan.metrics import Clearance, path_metrics, resample
from raceplan.planners import AStarPlanner
from raceplan.planners.custom import load_custom_planner

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "examples/smoothed_astar_planner.py"


def load(name="SmoothedAStar"):
    return load_custom_planner(f"{PLUGIN}:{name}")[0]


def module():
    return sys.modules[type(load()).__module__]


def room_with_block():
    occupied = np.zeros((30, 30), dtype=bool)
    occupied[[0, -1], :] = occupied[:, [0, -1]] = True
    occupied[8:22, 8:22] = True
    return OccupancyGrid(occupied, 0.2)


@pytest.mark.parametrize("name", ["SmoothedAStar", "SmoothedLowClearance"])
def test_accepted_path_is_verified_against_footprint_and_curvature(name):
    grid = room_with_block()
    start, goal = grid.grid_to_world((5, 5), 0.0), grid.grid_to_world((24, 24))
    planner = load(name)
    result = planner.plan(grid, start, goal)
    assert result.status is PlannerStatus.SUCCESS
    assert result.metadata["smoothing"] == "accepted"
    poses = result.path.poses
    assert (poses[0].x, poses[0].y) == pytest.approx((start.x, start.y))
    assert (poses[-1].x, poses[-1].y) == pytest.approx((goal.x, goal.y))
    assert atan2(poses[1].y - poses[0].y, poses[1].x - poses[0].x) == pytest.approx(start.yaw)
    # Independent check with the shared analysis metrics, not the plugin helpers.
    metrics = path_metrics(poses, grid, baseline_vehicle(), start, goal)
    assert metrics["max_discrete_curvature_per_m"] <= planner.config.max_curvature_per_m
    clearance = Clearance(grid)
    dense = resample(poses, 0.02)
    for a, b in zip(dense, dense[1:]):
        pose = Pose2D(a.x, a.y, atan2(b.y - a.y, b.x - a.x))
        assert clearance.footprint(pose, baseline_vehicle()) >= planner.config.footprint_margin_m - 0.01


def test_rejected_smoothing_returns_the_unmodified_astar_path():
    occupied = np.ones((7, 30), dtype=bool)
    occupied[3, 1:-1] = False  # a single-cell corridor narrower than the vehicle
    grid = OccupancyGrid(occupied, 0.2)
    start, goal = grid.grid_to_world((3, 1)), grid.grid_to_world((3, 28))
    result = load().plan(grid, start, goal)
    assert result.status is PlannerStatus.SUCCESS
    assert result.metadata["smoothing"] == "rejected"
    assert result.metadata["smoothing_reason"] == "footprint_clearance"
    assert result.path == AStarPlanner().plan(grid, start, goal).path


def test_planning_failures_and_timeout_are_reported_without_a_path():
    grid = room_with_block()
    blocked = load().plan(grid, Pose2D(3.0, 3.0), Pose2D(5.0, 5.0))
    assert blocked.status is PlannerStatus.INVALID_START and blocked.path is None
    timed_out = load().plan(grid, Pose2D(1.0, 1.0), Pose2D(5.0, 5.0), timeout_s=0)
    assert timed_out.status is PlannerStatus.TIMEOUT and timed_out.path is None
    with pytest.raises(ValueError, match="iterations"):
        type(load().config)(iterations=1.5)


def test_implicit_step_solves_the_smoothing_normal_equations():
    rng = np.random.default_rng(0)
    points, pushed = rng.normal(size=(12, 2)), rng.normal(size=(12, 2))
    fixed = np.zeros(12, dtype=bool)
    fixed[[0, 1, -1]] = True
    weight = 7.0
    updated = module().implicit_smoother(12, fixed, weight)(points, pushed)
    assert np.array_equal(updated[fixed], points[fixed])
    second = np.zeros((10, 12))
    for row in range(10):
        second[row, row:row + 3] = (1.0, -2.0, 1.0)
    residual = weight * second.T @ second @ updated + updated - pushed
    assert np.abs(residual[~fixed]).max() < 1e-9


def test_obstacle_distance_matches_shared_clearance_and_points_away():
    grid = room_with_block()
    clearance = Clearance(grid)
    points = np.array([(1.0, 1.3), (1.4, 3.0), (3.0, 4.7), (5.5, 2.2), (4.5, 1.0)])
    distance, away = module().obstacle_distance(points, clearance.bounds, grid)
    expected = [clearance.point(Pose2D(x, y)) for x, y in points]
    assert distance == pytest.approx(expected)
    moved = points + 0.01 * away
    assert np.all(module().obstacle_distance(moved, clearance.bounds, grid)[0] > distance)
