from math import atan, pi

import numpy as np
import pytest

from raceplan.common import OccupancyGrid, Pose2D, VehicleGeometry
from raceplan.planners.hybrid_primitives import (
    MotionPrimitiveConfig,
    generate_primitives,
    primitive_is_collision_free,
    rollout_bicycle,
)


VEHICLE = VehicleGeometry(2.0, 3.0, 1.0, 0.5)


def test_straight_rollout_reaches_requested_distance() -> None:
    poses = rollout_bicycle(
        Pose2D(1.0, 2.0, 0.0),
        steering_angle=0.0,
        signed_distance=2.0,
        wheelbase=2.0,
        sample_distance=0.4,
    )

    assert len(poses) == 6
    assert poses[-1].x == pytest.approx(3.0)
    assert poses[-1].y == pytest.approx(2.0)
    assert poses[-1].yaw == pytest.approx(0.0)


def test_constant_steering_follows_expected_circle() -> None:
    # tan(steering) / wheelbase = 0.5, hence radius 2 m.
    poses = rollout_bicycle(
        Pose2D(0.0, 0.0, 0.0),
        steering_angle=atan(1.0),
        signed_distance=pi,
        wheelbase=2.0,
        sample_distance=0.1,
    )

    assert poses[-1].x == pytest.approx(2.0, abs=1e-12)
    assert poses[-1].y == pytest.approx(2.0, abs=1e-12)
    assert poses[-1].yaw == pytest.approx(pi / 2, abs=1e-12)


def test_reverse_rollout_moves_backward() -> None:
    poses = rollout_bicycle(
        Pose2D(2.0, 2.0, 0.0),
        steering_angle=0.0,
        signed_distance=-1.0,
        wheelbase=2.0,
        sample_distance=0.25,
    )

    assert poses[-1].x == pytest.approx(1.0)
    assert poses[-1].yaw == pytest.approx(0.0)


def test_configuration_generates_steering_and_reverse_combinations() -> None:
    config = MotionPrimitiveConfig(
        max_steering_angle=0.4,
        steering_samples=5,
        travel_distance=1.0,
        sample_distance=0.2,
        allow_reverse=True,
    )

    primitives = generate_primitives(Pose2D(5.0, 5.0), VEHICLE, config)

    assert config.steering_angles == pytest.approx((-0.4, -0.2, 0.0, 0.2, 0.4))
    assert len(primitives) == 10
    assert {primitive.signed_distance for primitive in primitives} == {1.0, -1.0}


def test_primitive_collision_checks_intermediate_poses() -> None:
    occupied = np.zeros((12, 12), dtype=bool)
    occupied[5, 6] = True
    grid = OccupancyGrid(occupied, resolution=1.0)
    primitive = generate_primitives(
        Pose2D(3.0, 5.5),
        VEHICLE,
        MotionPrimitiveConfig(0.4, 3, 4.0, 0.25),
    )[1]  # zero steering

    assert not primitive_is_collision_free(grid, primitive, VEHICLE)

