import numpy as np
import pytest

from raceplan.common import OccupancyGrid


def test_world_grid_round_trip_uses_cell_centres() -> None:
    grid = OccupancyGrid(np.zeros((3, 4), dtype=bool), 0.5, -1.0, 2.0)

    assert grid.world_to_grid(-0.25, 3.25) == (2, 1)
    pose = grid.grid_to_world((2, 1))
    assert pose.x == pytest.approx(-0.25)
    assert pose.y == pytest.approx(3.25)


def test_boundary_and_occupancy_checks() -> None:
    occupied = np.array([[False, True], [False, False]])
    grid = OccupancyGrid(occupied, 1.0)

    assert grid.is_free((0, 0))
    assert not grid.is_free((0, 1))
    assert not grid.is_free((-1, 0))
    assert not grid.is_free((2, 0))


def test_grid_copies_and_freezes_source_array() -> None:
    source = np.zeros((2, 2), dtype=bool)
    grid = OccupancyGrid(source, 1.0)
    source[0, 0] = True

    assert grid.is_free((0, 0))
    with pytest.raises(ValueError):
        grid.occupied[0, 0] = True

