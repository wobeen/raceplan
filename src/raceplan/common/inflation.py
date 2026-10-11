"""Obstacle inflation shared by all planners."""

from __future__ import annotations

from math import ceil, hypot, isfinite

import numpy as np

from .grid import OccupancyGrid


def inflate_obstacles(grid: OccupancyGrid, radius_m: float) -> OccupancyGrid:
    """Inflate occupied cells by a circular radius measured in metres.

    Inflation is evaluated between cell centres. The returned grid is a new
    immutable value; the input is never modified.
    """

    if not isfinite(radius_m) or radius_m < 0:
        raise ValueError("radius_m must be finite and non-negative")
    if radius_m == 0:
        return OccupancyGrid(
            grid.occupied,
            resolution=grid.resolution,
            origin_x=grid.origin_x,
            origin_y=grid.origin_y,
        )

    limit = ceil(radius_m / grid.resolution)
    offsets = [
        (d_row, d_column)
        for d_row in range(-limit, limit + 1)
        for d_column in range(-limit, limit + 1)
        if hypot(d_row, d_column) * grid.resolution <= radius_m
    ]
    inflated = grid.occupied.copy()
    occupied_cells = np.argwhere(grid.occupied)
    for row, column in occupied_cells:
        for d_row, d_column in offsets:
            target_row = int(row) + d_row
            target_column = int(column) + d_column
            if 0 <= target_row < grid.height and 0 <= target_column < grid.width:
                inflated[target_row, target_column] = True

    return OccupancyGrid(
        inflated,
        resolution=grid.resolution,
        origin_x=grid.origin_x,
        origin_y=grid.origin_y,
    )

