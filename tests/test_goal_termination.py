from dataclasses import replace
from math import pi

import numpy as np
import pytest

from raceplan.common import OccupancyGrid, Path, Pose2D
from raceplan.defaults import baseline_vehicle, baseline_tracker_config, baseline_simulation_config
from raceplan.simulator import run_episode


@pytest.mark.parametrize('value', [0, -1, float('nan'), float('inf'), pi + .01])
def test_invalid_yaw_tolerance(value):
    with pytest.raises(ValueError, match='yaw tolerance'):
        replace(baseline_simulation_config(), goal_yaw_tolerance=value)


def test_yaw_requirement_prevents_false_success_and_preserves_legacy():
    grid = OccupancyGrid(np.zeros((100, 100), dtype=bool), .1)
    start = Pose2D(5, 5, 0)
    path = Path((start, Pose2D(6, 5)), 1)
    goal = Pose2D(5, 5, pi / 2)
    config = replace(baseline_simulation_config(), max_time_s=.05)
    def run(cfg, target=goal):
        return run_episode(grid, path, target, baseline_vehicle(), baseline_tracker_config(), cfg)
    assert run(config).reached
    strict = replace(config, goal_yaw_tolerance=.35)
    assert not run(strict).reached
    assert run(strict, Pose2D(5, 5, 2*pi)).reached
    assert run(strict, Pose2D(5, 5, .35)).reached
    assert not run(strict, Pose2D(5, 5, .350001)).reached
    assert not run(strict, Pose2D(8, 5, 0)).reached
