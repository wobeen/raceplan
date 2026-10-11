import numpy as np
import pytest

from raceplan.common import OccupancyGrid, inflate_obstacles


def test_circular_inflation_uses_metric_radius() -> None:
    occupied = np.zeros((5, 5), dtype=bool)
    occupied[2, 2] = True
    grid = OccupancyGrid(occupied, resolution=0.5)

    inflated = inflate_obstacles(grid, radius_m=0.5)

    expected = {(2, 2), (1, 2), (3, 2), (2, 1), (2, 3)}
    actual = {tuple(cell) for cell in np.argwhere(inflated.occupied)}
    assert actual == expected
    assert np.count_nonzero(grid.occupied) == 1


def test_inflation_rejects_invalid_radius() -> None:
    grid = OccupancyGrid(np.zeros((1, 1), dtype=bool), resolution=1.0)
    with pytest.raises(ValueError, match="non-negative"):
        inflate_obstacles(grid, -0.1)

