from pathlib import Path

import numpy as np

from raceplan.common import (
    OccupancyGrid,
    PlannerStatus,
    Pose2D,
    VehicleGeometry,
    load_occupancy_map,
    load_scenario,
)
from raceplan.planners import HybridAStarConfig, HybridAStarPlanner
from raceplan.planners.hybrid_primitives import MotionPrimitiveConfig


VEHICLE = VehicleGeometry(0.33, 0.58, 0.31, 0.10)
CONFIG = HybridAStarConfig(
    xy_resolution=0.5,
    yaw_bins=36,
    goal_position_tolerance=0.5,
    goal_yaw_tolerance=0.35,
    primitives=MotionPrimitiveConfig(
        max_steering_angle=0.45,
        steering_samples=5,
        travel_distance=0.5,
        sample_distance=0.1,
        allow_reverse=False,
    ),
)


def test_hybrid_astar_reaches_pose_on_open_map() -> None:
    grid = OccupancyGrid(np.zeros((8, 8), dtype=bool), resolution=1.0)
    planner = HybridAStarPlanner(VEHICLE, CONFIG)

    result = planner.plan(
        grid,
        Pose2D(1.5, 1.5, 0.0),
        Pose2D(5.5, 3.5, 0.0),
        timeout_s=2.0,
    )

    assert result.status is PlannerStatus.SUCCESS
    assert result.path is not None
    assert len(result.path.poses) > 2


def test_hybrid_astar_rejects_colliding_start() -> None:
    occupied = np.zeros((5, 5), dtype=bool)
    occupied[2, 2] = True
    grid = OccupancyGrid(occupied, resolution=1.0)

    result = HybridAStarPlanner(VEHICLE, CONFIG).plan(
        grid,
        Pose2D(2.5, 2.5, 0.0),
        Pose2D(4.0, 4.0, 0.0),
    )

    assert result.status is PlannerStatus.INVALID_START


def test_hybrid_astar_solves_repository_demo() -> None:
    root = Path(__file__).resolve().parents[1]
    scenario = load_scenario(root / "scenarios" / "demo.yaml")
    grid = load_occupancy_map(scenario.map_path).grid

    result = HybridAStarPlanner(VEHICLE, CONFIG).plan(
        grid,
        scenario.start,
        scenario.goal,
        timeout_s=scenario.timeout_s,
    )

    assert result.status is PlannerStatus.SUCCESS
    assert result.path is not None
