from math import pi

import numpy as np
import pytest

from raceplan.common import OccupancyGrid, Pose2D, VehicleGeometry
from raceplan.metrics import Clearance, path_metrics, trajectory_clearance


def test_geometry_has_known_length_curvature_and_boundary_clearance():
    grid = OccupancyGrid(np.zeros((10, 10), dtype=bool), 1.0)
    vehicle = VehicleGeometry(1.0, 2.0, 2.0, 0.0)
    straight = (Pose2D(2, 5), Pose2D(8, 5))
    result = path_metrics(straight, grid, vehicle, *straight, spacing=1.0)
    assert result['path_length_m'] == pytest.approx(6.0)
    assert result['path_to_query_distance_ratio'] == pytest.approx(1.0)
    assert result['max_discrete_curvature_per_m'] == pytest.approx(0.0)
    assert result['min_sampled_footprint_clearance_m'] == pytest.approx(1.0)
    corner = (Pose2D(2, 2), Pose2D(4, 2), Pose2D(4, 4))
    result = path_metrics(corner, grid, vehicle, corner[0], corner[-1], spacing=1.0)
    assert result['total_absolute_turn_rad'] == pytest.approx(pi / 2)
    assert result['max_discrete_curvature_per_m'] == pytest.approx(pi / 2)
    occupied = np.zeros((10, 10), dtype=bool)
    occupied[5, 5] = True
    clearance = Clearance(OccupancyGrid(occupied, 1.0))
    assert clearance.footprint(Pose2D(3, 5.5), vehicle) == pytest.approx(1.0)
    assert clearance.footprint(Pose2D(4, 5.5), vehicle) == 0.0


def test_recorded_trajectory_clearance_keeps_contact_and_initial_samples():
    grid = OccupancyGrid(np.zeros((10, 10), dtype=bool), 1.0)
    vehicle = VehicleGeometry(1.0, 2.0, 1.0, 0.0)
    poses = (Pose2D(2, 5), Pose2D(2, 5, pi / 2), Pose2D(1, 5), Pose2D(0.5, 5))
    assert trajectory_clearance(poses, Clearance(grid), vehicle) == pytest.approx((1, 1.5, 0, 0))
    with pytest.raises(ValueError, match='at least one'):
        trajectory_clearance((), Clearance(grid), vehicle)
