from dataclasses import replace
import numpy as np
import pytest
from raceplan.common import OccupancyGrid, Pose2D, Path
from raceplan.defaults import baseline_vehicle, baseline_tracker_config, baseline_simulation_config
from raceplan.simulator import run_episode
from raceplan.simulator.obstacle_guard import ObstacleGuardConfig
from raceplan.simulator.obstacle_guard import guard_diagnostics
from raceplan.metrics import Clearance


def test_parallel_wall_can_stop_lateral_cap_without_forward_collision():
    occupied = np.zeros((60, 80), dtype=bool)
    occupied[20, :] = True
    grid = OccupancyGrid(occupied, .1)
    result = guard_diagnostics(grid, Clearance(grid), Pose2D(2, 2.3), 0, 0,
                               baseline_vehicle(), baseline_simulation_config(), ObstacleGuardConfig())
    assert result['clearance_m'] == pytest.approx(.045)
    assert result['lateral_cap_mps'] == 0
    assert not result['preview_collision']
    assert result['braking_cap_mps'] > 0


def test_forward_wall_blocks_preview_even_with_large_current_clearance():
    occupied = np.zeros((60, 80), dtype=bool)
    occupied[:, 40] = True
    grid = OccupancyGrid(occupied, .1)
    result = guard_diagnostics(grid, Clearance(grid), Pose2D(3, 3), 0, 0,
                               baseline_vehicle(), baseline_simulation_config(), ObstacleGuardConfig())
    assert result['preview_collision']
    assert result['lateral_cap_mps'] > 0
    assert result['preview_free_m'] < 1


def test_guard_stops_before_wall_and_does_not_claim_success():
    occupied = np.zeros((60, 80), dtype=bool)
    occupied[:, 40] = True
    grid = OccupancyGrid(occupied, .1)
    start, goal = Pose2D(1, 3), Pose2D(6, 3)
    path = Path((start, goal), 5)
    args = (grid, path, goal, baseline_vehicle(), baseline_tracker_config(),
            replace(baseline_simulation_config(), max_time_s=8))
    assert run_episode(*args).collided
    guarded = run_episode(*args, obstacle_guard=ObstacleGuardConfig())
    assert not guarded.collided and not guarded.reached
    assert guarded.samples[-1].state.speed < .01
    assert guarded.samples[-1].state.pose.x < 4 - .39


def test_guard_free_route_reaches_position_regardless_of_goal_yaw():
    grid = OccupancyGrid(np.zeros((60, 80), dtype=bool), .1)
    start, goal = Pose2D(1, 3), Pose2D(5, 3, 1.57)
    args = (grid, Path((start, goal), 4), goal, baseline_vehicle(), baseline_tracker_config(), baseline_simulation_config())
    old = run_episode(*args)
    new = run_episode(*args, obstacle_guard=ObstacleGuardConfig())
    assert new.reached and new.goal_yaw_error > .35
    assert new.samples == old.samples


def test_collision_at_goal_is_not_counted_as_arrival():
    occupied = np.zeros((60, 80), dtype=bool)
    occupied[30, 30] = True
    grid = OccupancyGrid(occupied, .1)
    goal = Pose2D(3, 3)
    result = run_episode(grid, Path((goal,), 0), goal, baseline_vehicle(),
                         baseline_tracker_config(), baseline_simulation_config(),
                         obstacle_guard=ObstacleGuardConfig())
    assert result.collided and not result.reached


@pytest.mark.parametrize('kwargs', [dict(stop_margin_m=float('nan')), dict(sample_distance_m=2)])
def test_invalid_guard_config(kwargs):
    with pytest.raises(ValueError):
        ObstacleGuardConfig(**kwargs)
