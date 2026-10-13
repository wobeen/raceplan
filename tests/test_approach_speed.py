from dataclasses import replace
import pytest
from raceplan.common import Path, Pose2D
from raceplan.controllers import PurePursuitController
from raceplan.defaults import baseline_tracker_config, baseline_vehicle


def command(path, pose, config):
    return PurePursuitController(path, baseline_vehicle(), config).command(pose, .8, .05)


def test_approach_brakes_near_endpoint_without_changing_steering():
    path = Path(tuple(Pose2D(i / 10, 0) for i in range(31)), 3)
    base = baseline_tracker_config()
    slow = replace(base, approach_distance=1.2)
    far = Pose2D(.5, 0)
    assert command(path, far, base) == command(path, far, slow)
    near = Pose2D(2.8, 0)
    old, new = command(path, near, base), command(path, near, slow)
    assert new.acceleration < old.acceleration
    assert new.steering_angle == old.steering_angle


def test_early_pass_near_endpoint_does_not_trigger_slowdown():
    path = Path((Pose2D(0, 0), Pose2D(3, 0), Pose2D(3, 3), Pose2D(0, .1)), 10)
    base = baseline_tracker_config()
    assert command(path, path.poses[0], base) == command(path, path.poses[0], replace(base, approach_distance=1.2))


@pytest.mark.parametrize('kwargs', [dict(approach_distance=0), dict(approach_distance=float('nan')),
                                   dict(approach_min_speed=0), dict(approach_distance=1, approach_min_speed=2)])
def test_invalid_approach_settings(kwargs):
    with pytest.raises(ValueError):
        replace(baseline_tracker_config(), **kwargs)
