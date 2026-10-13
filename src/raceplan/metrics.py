"""Geometric metrics on an explicitly sampled path; no planning or simulation."""
from __future__ import annotations

from math import atan2, ceil, hypot, isfinite, pi

import numpy as np

from raceplan.common import OccupancyGrid, Pose2D, VehicleGeometry
from raceplan.common.vehicle import footprint_corners, footprint_in_collision


def _angle(value: float) -> float:
    return (value + pi) % (2 * pi) - pi


def resample(poses: tuple[Pose2D, ...], spacing: float) -> tuple[Pose2D, ...]:
    """Uniform arc-length samples, including endpoints, with shortest-yaw interpolation.

    Actual spacing is length / ceil(length / requested_spacing). Zero-length
    segments are omitted; an entirely stationary path keeps its first pose.
    """
    if not isfinite(spacing) or spacing <= 0:
        raise ValueError('spacing must be finite and positive')
    if not poses:
        raise ValueError('path must have at least one pose')
    points = [poses[0]]
    distances = [0.0]
    for pose in poses[1:]:
        distance = hypot(pose.x - points[-1].x, pose.y - points[-1].y)
        if distance > 1e-12:
            points.append(pose)
            distances.append(distances[-1] + distance)
    if len(points) == 1:
        return (points[0],)
    count = ceil(distances[-1] / spacing)
    result = []
    segment = 0
    for distance in np.linspace(0.0, distances[-1], count + 1):
        while segment < len(points) - 2 and distance > distances[segment + 1]:
            segment += 1
        a, b = points[segment:segment + 2]
        fraction = (distance - distances[segment]) / (distances[segment + 1] - distances[segment])
        result.append(Pose2D(a.x + fraction * (b.x - a.x), a.y + fraction * (b.y - a.y),
                             _angle(a.yaw + fraction * _angle(b.yaw - a.yaw))))
    return tuple(result)


def _point_segment(point, start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    denominator = dx * dx + dy * dy
    t = 0.0 if denominator == 0 else max(0.0, min(1.0,
        ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / denominator))
    return hypot(point[0] - start[0] - t * dx, point[1] - start[1] - t * dy)


class Clearance:
    """Unsigned distance to occupied cell squares and map exterior, in metres."""

    def __init__(self, grid: OccupancyGrid):
        self.grid = grid
        self.right = grid.origin_x + grid.width * grid.resolution
        self.top = grid.origin_y + grid.height * grid.resolution
        self.cells = []
        for row, column in np.argwhere(grid.occupied):
            x = grid.origin_x + int(column) * grid.resolution
            y = grid.origin_y + int(row) * grid.resolution
            r = grid.resolution
            self.cells.append(((x, y), (x + r, y), (x + r, y + r), (x, y + r)))

    def point(self, pose: Pose2D) -> float:
        boundary = min(pose.x - self.grid.origin_x, self.right - pose.x,
                       pose.y - self.grid.origin_y, self.top - pose.y)
        if boundary <= 0:
            return 0.0
        nearest = boundary
        for cell in self.cells:
            dx = max(cell[0][0] - pose.x, 0.0, pose.x - cell[2][0])
            dy = max(cell[0][1] - pose.y, 0.0, pose.y - cell[2][1])
            nearest = min(nearest, hypot(dx, dy))
        return nearest

    def footprint(self, pose: Pose2D, vehicle: VehicleGeometry) -> float:
        if footprint_in_collision(self.grid, pose, vehicle):
            return 0.0
        rectangle = footprint_corners(pose, vehicle)
        nearest = min(min(x - self.grid.origin_x, self.right - x,
                          y - self.grid.origin_y, self.top - y) for x, y in rectangle)
        for cell in self.cells:
            for first, second in ((rectangle, cell), (cell, rectangle)):
                for point in first:
                    for index in range(4):
                        nearest = min(nearest, _point_segment(point, second[index], second[(index + 1) % 4]))
        return max(0.0, nearest)


def trajectory_clearance(poses: tuple[Pose2D, ...], clearance: Clearance,
                         vehicle: VehicleGeometry) -> tuple[float, ...]:
    """Clearance at every recorded true pose, including initial/failure samples.

    No resampling: retains the simulator's temporal resolution and actual yaw.
    Does not certify the swept space between recorded poses.
    """
    if not poses:
        raise ValueError('trajectory must have at least one pose')
    return tuple(clearance.footprint(pose, vehicle) for pose in poses)


def path_metrics(poses: tuple[Pose2D, ...], grid: OccupancyGrid,
                 vehicle: VehicleGeometry, start: Pose2D, goal: Pose2D,
                 spacing: float = 0.1) -> dict[str, float | int | None]:
    samples = resample(poses, spacing)
    length = sum(hypot(b.x - a.x, b.y - a.y) for a, b in zip(poses, poses[1:]))
    direct = hypot(goal.x - start.x, goal.y - start.y)
    headings = [atan2(b.y - a.y, b.x - a.x) for a, b in zip(samples, samples[1:])]
    turns = [abs(_angle(b - a)) for a, b in zip(headings, headings[1:])]
    actual_spacing = length / (len(samples) - 1) if len(samples) > 1 else 0.0
    clearance = Clearance(grid)
    # Include original vertices for clearance so sharp corners are not discarded.
    clearance_poses = samples + poses
    footprint = min(clearance.footprint(pose, vehicle) for pose in clearance_poses)
    point = min(clearance.point(pose) for pose in clearance_poses)
    return {
        'path_length_m': length,
        'path_to_query_distance_ratio': length / direct if direct > 1e-12 else None,
        'path_start_offset_m': hypot(poses[0].x - start.x, poses[0].y - start.y),
        'path_goal_offset_m': hypot(poses[-1].x - goal.x, poses[-1].y - goal.y),
        'path_goal_yaw_error_rad': abs(_angle(poses[-1].yaw - goal.yaw)),
        'sample_spacing_m': actual_spacing,
        'sample_count': len(samples),
        'total_absolute_turn_rad': sum(turns),
        'max_discrete_curvature_per_m': max(turns) / actual_spacing if turns and actual_spacing else None,
        'min_sampled_footprint_clearance_m': footprint,
        'min_sampled_footprint_clearance_vehicle_widths': footprint / vehicle.width,
        'min_sampled_reference_clearance_m': point,
        'local_clearance_diameter_proxy_vehicle_widths': 2 * point / vehicle.width,
    }
