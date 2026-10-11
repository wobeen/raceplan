"""Occupancy-grid representation and world/grid coordinate conversion."""

from __future__ import annotations

from dataclasses import dataclass
from math import floor, isfinite

import numpy as np
import numpy.typing as npt

from .types import Pose2D

GridIndex = tuple[int, int]  # row, column


@dataclass(frozen=True, slots=True)
class OccupancyGrid:
    """Immutable boolean occupancy grid with a bottom-left world origin.

    Array rows grow toward positive world y and columns toward positive world x.
    ``True`` denotes an occupied cell.
    """

    occupied: npt.NDArray[np.bool_]
    resolution: float
    origin_x: float = 0.0
    origin_y: float = 0.0

    def __post_init__(self) -> None:
        array = np.asarray(self.occupied, dtype=np.bool_)
        if array.ndim != 2 or 0 in array.shape:
            raise ValueError("occupied must be a non-empty 2D array")
        if not isfinite(self.resolution) or self.resolution <= 0:
            raise ValueError("resolution must be finite and positive")
        if not isfinite(self.origin_x) or not isfinite(self.origin_y):
            raise ValueError("grid origin must be finite")
        array = array.copy()
        array.setflags(write=False)
        object.__setattr__(self, "occupied", array)

    @property
    def height(self) -> int:
        return int(self.occupied.shape[0])

    @property
    def width(self) -> int:
        return int(self.occupied.shape[1])

    def contains(self, cell: GridIndex) -> bool:
        row, column = cell
        return 0 <= row < self.height and 0 <= column < self.width

    def is_free(self, cell: GridIndex) -> bool:
        return self.contains(cell) and not bool(self.occupied[cell])

    def world_to_grid(self, x: float, y: float) -> GridIndex:
        """Return the cell containing a world point.

        The result may be out of bounds so callers can distinguish conversion
        from validity checks with :meth:`contains`.
        """

        if not isfinite(x) or not isfinite(y):
            raise ValueError("world coordinates must be finite")
        column = floor((x - self.origin_x) / self.resolution)
        row = floor((y - self.origin_y) / self.resolution)
        return row, column

    def grid_to_world(self, cell: GridIndex, yaw: float = 0.0) -> Pose2D:
        """Return the world pose at a cell centre."""

        if not self.contains(cell):
            raise IndexError(f"cell outside grid: {cell}")
        row, column = cell
        return Pose2D(
            x=self.origin_x + (column + 0.5) * self.resolution,
            y=self.origin_y + (row + 0.5) * self.resolution,
            yaw=yaw,
        )

