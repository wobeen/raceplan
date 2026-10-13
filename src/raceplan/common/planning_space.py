"""Conservative circular configuration space, separate from physical collision maps."""
from math import hypot, sqrt
import numpy as np
from raceplan.common import OccupancyGrid, VehicleGeometry


def enclosing_radius(vehicle: VehicleGeometry) -> float:
    return hypot(vehicle.length / 2 + abs(vehicle.rear_axle_to_center), vehicle.width / 2)


def center_clearance(grid: OccupancyGrid) -> np.ndarray:
    """Exact centre-to-cell-square/exterior distance, without vehicle margin."""
    y, x = np.indices(grid.occupied.shape)
    x = grid.origin_x + (x + .5) * grid.resolution
    y = grid.origin_y + (y + .5) * grid.resolution
    distance = np.minimum.reduce([x-grid.origin_x, y-grid.origin_y,
                                 grid.origin_x+grid.width*grid.resolution-x,
                                 grid.origin_y+grid.height*grid.resolution-y])
    for row, column in np.argwhere(grid.occupied):
        left, bottom = grid.origin_x+column*grid.resolution, grid.origin_y+row*grid.resolution
        dx = np.maximum(0, np.maximum(left-x, x-left-grid.resolution))
        dy = np.maximum(0, np.maximum(bottom-y, y-bottom-grid.resolution))
        distance = np.minimum(distance, np.hypot(dx, dy))
    return distance


def circle_planning_grid(grid: OccupancyGrid, vehicle: VehicleGeometry) -> OccupancyGrid:
    """Conservative yaw-independent rear-axle disk plus whole-cell coverage.

    The cell half-diagonal covers edges between free centres. This is more
    restrictive than oriented rectangles; physical driving uses the raw map.
    """
    radius = enclosing_radius(vehicle) + grid.resolution / sqrt(2)
    return OccupancyGrid(center_clearance(grid) <= radius, grid.resolution, grid.origin_x, grid.origin_y)
