"""Independent cost and public-run checks for the sharp-turn development candidates."""
from heapq import heappop, heappush
from math import atan2, hypot, pi
from pathlib import Path

import numpy as np
import pytest

from raceplan.common import OccupancyGrid
from raceplan.planners.custom import load_custom_planner

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "examples/sharp_turn_planner.py"


def load(name="SharpTurnAStar"):
    return load_custom_planner(f"{PLUGIN}:{name}")[0]


def oracle(grid, start, goal, absolute_weight, squared_weight):
    initial = (*grid.world_to_grid(start.x, start.y), start.yaw)
    target = grid.world_to_grid(goal.x, goal.y)
    queue, costs = [(0.0, initial)], {initial: 0.0}
    while queue:
        cost, state = heappop(queue)
        if cost != costs[state]:
            continue
        row, col, heading = state
        if (row, col) == target:
            return cost
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if (not dr and not dc) or not grid.is_free((row + dr, col + dc)):
                    continue
                if dr and dc and (not grid.is_free((row + dr, col))
                                  or not grid.is_free((row, col + dc))):
                    continue
                yaw = atan2(dr, dc)
                delta = abs((yaw - heading + pi) % (2 * pi) - pi)
                updated = (cost + hypot(dr, dc) * grid.resolution
                           + absolute_weight * delta + squared_weight * delta * delta)
                other = (row + dr, col + dc, yaw)
                if updated < costs.get(other, float("inf")):
                    costs[other] = updated
                    heappush(queue, (updated, other))
    return float("inf")


@pytest.mark.parametrize("name", ["SharpTurnLow", "SharpTurnAStar",
                                  "SharpTurnHigh", "SharpTurnCombined"])
def test_cost_matches_independent_direction_state_oracle(name):
    occupied = np.zeros((7, 8), dtype=bool)
    occupied[1:6, 3] = True
    occupied[4, 3] = False
    grid = OccupancyGrid(occupied, 0.3)
    start, goal = grid.grid_to_world((1, 1), 0.2), grid.grid_to_world((5, 6))
    planner = load(name)
    result = planner.plan(grid, start, goal)
    config = planner.config
    assert result.path.cost == pytest.approx(oracle(
        grid, start, goal, config.absolute_turn_weight_m_per_rad,
        config.squared_turn_weight_m_per_rad2))


def test_squared_cost_prefers_two_gradual_turns_to_one_sharp_turn():
    planner = load()
    weight = planner.config.squared_turn_weight_m_per_rad2
    assert 2 * weight * (pi / 4) ** 2 < weight * (pi / 2) ** 2


def test_invalid_weights_and_timeout_contract():
    config_type = type(load().config)
    with pytest.raises(ValueError, match="finite and non-negative"):
        config_type(squared_turn_weight_m_per_rad2=-0.1)
    with pytest.raises(ValueError, match="finite and non-negative"):
        config_type(absolute_turn_weight_m_per_rad=float("nan"))
    grid = OccupancyGrid(np.zeros((3, 3), dtype=bool), 0.5)
    start, goal = grid.grid_to_world((0, 0)), grid.grid_to_world((2, 2))
    result = load().plan(grid, start, goal, timeout_s=0)
    assert result.status.value == "timeout" and result.expanded_nodes == 0
