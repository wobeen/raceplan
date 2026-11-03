"""Direction-state A* example; fixed turn cost, with a zero-weight ablation.

This point-grid search does not model vehicle steering or a vehicle footprint.
See docs/TURN_AWARE_CANDIDATE.md for the objective and development protocol.
"""
from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count
from math import atan2, cos, hypot, isfinite, sin
from time import perf_counter

from raceplan.common import OccupancyGrid, Path, PlannerResult, PlannerStatus, Pose2D
from raceplan.planners.base import Planner

# Row increases with world y; indices are the incoming edge direction.
MOVES = ((0, 1), (1, 1), (1, 0), (1, -1),
         (0, -1), (-1, -1), (-1, 0), (-1, 1))
HEADINGS = tuple(atan2(row, column) for row, column in MOVES)
State = tuple[int, int, int]


def angle_difference(first: float, second: float) -> float:
    return abs(atan2(sin(first - second), cos(first - second)))


@dataclass(frozen=True)
class TurnAwareConfig:
    turn_weight_m_per_rad: float = 0.20

    def __post_init__(self):
        if not isfinite(self.turn_weight_m_per_rad) or self.turn_weight_m_per_rad < 0:
            raise ValueError('turn_weight_m_per_rad must be finite and non-negative')


class TurnAwareAStar(Planner):
    """Minimize length + weight * absolute heading change on an 8-connected grid."""

    def __init__(self, config: TurnAwareConfig | None = None):
        self.config = config if config is not None else TurnAwareConfig()

    @property
    def name(self):
        return 'turn_aware_astar'

    def plan(self, grid: OccupancyGrid, start: Pose2D, goal: Pose2D, *, timeout_s=None):
        if timeout_s is not None and (not isfinite(timeout_s) or timeout_s < 0):
            raise ValueError('timeout_s must be finite and non-negative')
        started = perf_counter()
        start_cell = grid.world_to_grid(start.x, start.y)
        goal_cell = grid.world_to_grid(goal.x, goal.y)
        weight = self.config.turn_weight_m_per_rad
        expanded = 0

        def result(status, path=None):
            return PlannerResult(status, path, expanded, perf_counter() - started, {
                'algorithm': self.name,
                'objective': 'length_m + turn_weight_m_per_rad * absolute_turn_rad',
                'goal_yaw_constrained': False,
            })

        if not grid.is_free(start_cell):
            return result(PlannerStatus.INVALID_START)
        if not grid.is_free(goal_cell):
            return result(PlannerStatus.INVALID_GOAL)

        # -1 is a single initial state using the exact supplied start yaw.
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
                # Yaws follow outgoing edges; the last retains its incoming yaw.
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
                state = (*neighbour, direction)
                step = hypot(dr, dc) * grid.resolution
                candidate = cost + step + weight * angle_difference(HEADINGS[direction], heading)
                if candidate >= best.get(state, float('inf')):
                    continue
                best[state] = candidate
                parent[state] = current
                heappush(frontier, (candidate + distance(*neighbour), candidate, next(order), state))
        return result(PlannerStatus.NO_PATH)


class LengthOnlyAStar(TurnAwareAStar):
    """Same direction-state search with the turn term removed, not a baseline delegate."""

    def __init__(self):
        super().__init__(TurnAwareConfig(turn_weight_m_per_rad=0.0))

    @property
    def name(self):
        return 'turn_aware_zero'
