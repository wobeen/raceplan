"""Vehicle geometry and conservative oriented-footprint collision checks."""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, isfinite, sin

from .grid import OccupancyGrid
from .types import Pose2D

Point = tuple[float, float]


@dataclass(frozen=True, slots=True)
class VehicleGeometry:
    """Rectangular vehicle footprint referenced at the rear axle centre."""

    wheelbase: float
    length: float
    width: float
    rear_axle_to_center: float

    def __post_init__(self) -> None:
        values = (self.wheelbase, self.length, self.width, self.rear_axle_to_center)
        if not all(isfinite(value) for value in values):
            raise ValueError("vehicle dimensions must be finite")
        if self.wheelbase <= 0 or self.length <= 0 or self.width <= 0:
            raise ValueError("wheelbase, length, and width must be positive")
        if abs(self.rear_axle_to_center) > self.length / 2:
            raise ValueError("rear axle reference must lie within the footprint")


def footprint_corners(pose: Pose2D, vehicle: VehicleGeometry) -> tuple[Point, ...]:
    """Return counter-clockwise world coordinates of the vehicle rectangle."""

    heading = (cos(pose.yaw), sin(pose.yaw))
    lateral = (-heading[1], heading[0])
    center = (
        pose.x + vehicle.rear_axle_to_center * heading[0],
        pose.y + vehicle.rear_axle_to_center * heading[1],
    )
    half_length = vehicle.length / 2
    half_width = vehicle.width / 2
    return tuple(
        (
            center[0] + longitudinal * heading[0] + sideways * lateral[0],
            center[1] + longitudinal * heading[1] + sideways * lateral[1],
        )
        for longitudinal, sideways in (
            (half_length, half_width),
            (-half_length, half_width),
            (-half_length, -half_width),
            (half_length, -half_width),
        )
    )


def _project(points: tuple[Point, ...], axis: Point) -> tuple[float, float]:
    values = tuple(x * axis[0] + y * axis[1] for x, y in points)
    return min(values), max(values)


def _polygons_intersect(
    rectangle: tuple[Point, ...],
    cell: tuple[Point, ...],
    yaw: float,
) -> bool:
    axes = ((cos(yaw), sin(yaw)), (-sin(yaw), cos(yaw)), (1.0, 0.0), (0.0, 1.0))
    for axis in axes:
        first_min, first_max = _project(rectangle, axis)
        second_min, second_max = _project(cell, axis)
        if first_max < second_min or second_max < first_min:
            return False
    return True


def footprint_in_collision(
    grid: OccupancyGrid,
    pose: Pose2D,
    vehicle: VehicleGeometry,
) -> bool:
    """Check map bounds and intersection with every candidate occupied cell.

    Boundary contact is treated as collision. This conservative convention is
    shared by all Hybrid A* primitives.
    """

    rectangle = footprint_corners(pose, vehicle)
    min_x = min(point[0] for point in rectangle)
    max_x = max(point[0] for point in rectangle)
    min_y = min(point[1] for point in rectangle)
    max_y = max(point[1] for point in rectangle)
    map_max_x = grid.origin_x + grid.width * grid.resolution
    map_max_y = grid.origin_y + grid.height * grid.resolution
    if (
        min_x < grid.origin_x
        or min_y < grid.origin_y
        or max_x > map_max_x
        or max_y > map_max_y
    ):
        return True

    min_row, min_column = grid.world_to_grid(min_x, min_y)
    max_row, max_column = grid.world_to_grid(max_x, max_y)
    min_row = max(0, min_row)
    min_column = max(0, min_column)
    max_row = min(grid.height - 1, max_row)
    max_column = min(grid.width - 1, max_column)

    for row in range(min_row, max_row + 1):
        for column in range(min_column, max_column + 1):
            if not grid.occupied[row, column]:
                continue
            left = grid.origin_x + column * grid.resolution
            bottom = grid.origin_y + row * grid.resolution
            right = left + grid.resolution
            top = bottom + grid.resolution
            cell = ((left, bottom), (right, bottom), (right, top), (left, top))
            if _polygons_intersect(rectangle, cell, pose.yaw):
                return True
    return False

