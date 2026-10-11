from math import pi, sqrt

import numpy as np
import pytest

from raceplan.common import (
    OccupancyGrid,
    Pose2D,
    VehicleGeometry,
    footprint_corners,
    footprint_in_collision,
)


VEHICLE = VehicleGeometry(
    wheelbase=2.0,
    length=4.0,
    width=2.0,
    rear_axle_to_center=1.0,
)


def test_footprint_rotates_around_rear_axle_reference() -> None:
    corners = footprint_corners(Pose2D(5.0, 5.0, pi / 2), VEHICLE)

    assert corners[0][0] == pytest.approx(4.0)
    assert corners[0][1] == pytest.approx(8.0)
    assert corners[2][0] == pytest.approx(6.0)
    assert corners[2][1] == pytest.approx(4.0)


def test_footprint_detects_occupied_cell_at_rotation() -> None:
    occupied = np.zeros((10, 10), dtype=bool)
    occupied[6, 6] = True
    grid = OccupancyGrid(occupied, resolution=1.0)
    small_vehicle = VehicleGeometry(2.0, 4.0, 1.0, 1.0)

    assert footprint_in_collision(
        grid,
        Pose2D(5.0, 5.0, pi / 4),
        small_vehicle,
    )


def test_footprint_outside_map_is_collision() -> None:
    grid = OccupancyGrid(np.zeros((10, 10), dtype=bool), resolution=1.0)

    assert footprint_in_collision(grid, Pose2D(0.5, 5.0), VEHICLE)
    assert not footprint_in_collision(grid, Pose2D(5.0, 5.0), VEHICLE)


def test_vehicle_rejects_axle_outside_footprint() -> None:
    with pytest.raises(ValueError, match="within"):
        VehicleGeometry(2.0, 4.0, 2.0, rear_axle_to_center=2.1)

