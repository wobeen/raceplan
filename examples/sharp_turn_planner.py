"""Direction-state A* variants that distinguish gradual and abrupt turns.

This is a development-only successor to ``turn_aware_planner.py``.  The old
sealed candidate remains untouched.  The added squared-angle term makes one
90-degree change more expensive than two 45-degree changes with the same total
absolute heading change.
"""
from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count
from math import atan2, cos, hypot, isfinite, sin
from time import perf_counter

from raceplan.common import OccupancyGrid, Path, PlannerResult, PlannerStatus, Pose2D
from raceplan.planners.base import Planner

MOVES = ((0, 1), (1, 1), (1, 0), (1, -1),
         (0, -1), (-1, -1), (-1, 0), (-1, 1))
HEADINGS = tuple(atan2(row, column) for row, column in MOVES)
State = tuple[int, int, int]


def angle_difference(first: float, second: float) -> float:
    return abs(atan2(sin(first - second), cos(first - second)))


@dataclass(frozen=True)
class SharpTurnConfig:
    absolute_turn_weight_m_per_rad: float = 0.0
    squared_turn_weight_m_per_rad2: float = 0.20

    def __post_init__(self):
        values = (self.absolute_turn_weight_m_per_rad,
                  self.squared_turn_weight_m_per_rad2)
        if any(not isfinite(value) or value < 0 for value in values):
            raise ValueError("turn weights must be finite and non-negative")


class SharpTurnAStar(Planner):
    """Minimize length plus absolute and squared heading-change costs."""

    def __init__(self, config: SharpTurnConfig | None = None):
        self.config = config if config is not None else SharpTurnConfig()

    @property
    def name(self):
        return "sharp_turn_astar"

    def plan(self, grid: OccupancyGrid, start: Pose2D, goal: Pose2D, *, timeout_s=None):
        if timeout_s is not None and (not isfinite(timeout_s) or timeout_s < 0):
            raise ValueError("timeout_s must be finite and non-negative")
        started = perf_counter()
        start_cell = grid.world_to_grid(start.x, start.y)
        goal_cell = grid.world_to_grid(goal.x, goal.y)
        expanded = 0

        def result(status, path=None):
            return PlannerResult(status, path, expanded, perf_counter() - started, {
                "algorithm": self.name,
                "objective": "length_m + absolute_weight*|turn| + squared_weight*turn^2",
                "goal_yaw_constrained": False,
            })

        if not grid.is_free(start_cell):
            return result(PlannerStatus.INVALID_START)
        if not grid.is_free(goal_cell):
            return result(PlannerStatus.INVALID_GOAL)

        initial = (*start_cell, -1)
        order = count()
        distance = lambda row, col: hypot(goal_cell[0] - row, goal_cell[1] - col) * grid.resolution
        frontier = [(distance(*start_cell), 0.0, next(order), initial)]
        best = {initial: 0.0}
        parent: dict[State, State] = {}

        while frontier:
            if timeout_s is not None and perf_counter() - started >= timeout_s:
                return result(PlannerStatus.TIMEOUT)
            _, cost, _, current = heappop(frontier)
            if cost != best.get(current):
                continue
            expanded += 1
            row, col, incoming = current
            if (row, col) == goal_cell:
                states = [current]
                while states[-1] in parent:
                    states.append(parent[states[-1]])
                states.reverse()
                poses = []
                for index, (r, c, direction) in enumerate(states):
                    yaw = (HEADINGS[states[index + 1][2]] if index + 1 < len(states)
                           else start.yaw if direction == -1 else HEADINGS[direction])
                    poses.append(grid.grid_to_world((r, c), yaw))
                return result(PlannerStatus.SUCCESS, Path(tuple(poses), cost))

            heading = start.yaw if incoming == -1 else HEADINGS[incoming]
            for direction, (dr, dc) in enumerate(MOVES):
                neighbour = (row + dr, col + dc)
                if not grid.is_free(neighbour):
                    continue
                if dr and dc and (not grid.is_free((row + dr, col))
                                  or not grid.is_free((row, col + dc))):
                    continue
                delta = angle_difference(HEADINGS[direction], heading)
                step = hypot(dr, dc) * grid.resolution
                turn_cost = (self.config.absolute_turn_weight_m_per_rad * delta
                             + self.config.squared_turn_weight_m_per_rad2 * delta * delta)
                candidate = cost + step + turn_cost
                state = (*neighbour, direction)
                if candidate >= best.get(state, float("inf")):
                    continue
                best[state] = candidate
                parent[state] = current
                heappush(frontier, (candidate + distance(*neighbour), candidate,
                                    next(order), state))
        return result(PlannerStatus.NO_PATH)


class SharpTurnLow(SharpTurnAStar):
    def __init__(self):
        super().__init__(SharpTurnConfig(squared_turn_weight_m_per_rad2=0.10))

    @property
    def name(self):
        return "sharp_turn_low"


class SharpTurnHigh(SharpTurnAStar):
    def __init__(self):
        super().__init__(SharpTurnConfig(squared_turn_weight_m_per_rad2=0.40))

    @property
    def name(self):
        return "sharp_turn_high"


class SharpTurnCombined(SharpTurnAStar):
    def __init__(self):
        super().__init__(SharpTurnConfig(absolute_turn_weight_m_per_rad=0.05,
                                        squared_turn_weight_m_per_rad2=0.20))

    @property
    def name(self):
        return "sharp_turn_combined"
