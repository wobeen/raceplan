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


def test_clearance_candidate_filter_matches_exhaustive_distance():
    from raceplan.common.vehicle import footprint_corners, footprint_in_collision
    from raceplan.metrics import _point_segment
    occupied = np.zeros((20, 30), dtype=bool)
    occupied[4:10, 10:13] = True
    occupied[15:18, 17:22] = True
    grid = OccupancyGrid(occupied, 0.1)
    vehicle = VehicleGeometry(0.2, 0.3, 0.15, 0.03)
    clearance = Clearance(grid)
    for x, y, yaw in np.random.default_rng(42).uniform([0.2, 0.2, -3], [2.8, 1.8, 3], (20, 3)):
        pose = Pose2D(x, y, yaw)
        rectangle = footprint_corners(pose, vehicle)
        expected = min(min(px, 3-px, py, 2-py) for px, py in rectangle)
        if footprint_in_collision(grid, pose, vehicle):
            expected = 0.0
        else:
            for cell in clearance.cells:
                for a, b in ((rectangle, cell), (cell, rectangle)):
                    for p in a:
                        expected = min(expected, *(_point_segment(p, b[i], b[(i+1)%4]) for i in range(4)))
        assert clearance.footprint(pose, vehicle) == pytest.approx(expected)
