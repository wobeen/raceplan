"""Baseline Hybrid A* search using kinematic bicycle motion primitives."""

from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count
from math import floor, hypot, isfinite, pi
from time import perf_counter

from raceplan.common import (
    OccupancyGrid,
    Path,
    PlannerResult,
    PlannerStatus,
    Pose2D,
    VehicleGeometry,
    footprint_in_collision,
)

from .base import Planner
from .hybrid_primitives import (
    MotionPrimitiveConfig,
    generate_primitives,
    normalize_angle,
    primitive_is_collision_free,
)

StateKey = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class HybridAStarConfig:
    """Search discretization, goal tolerances, and primitive configuration."""

    xy_resolution: float
    yaw_bins: int
    goal_position_tolerance: float
    goal_yaw_tolerance: float
    primitives: MotionPrimitiveConfig

    def __post_init__(self) -> None:
        numeric = (
            self.xy_resolution,
            self.goal_position_tolerance,
            self.goal_yaw_tolerance,
        )
        if not all(isfinite(value) for value in numeric):
            raise ValueError("Hybrid A* configuration values must be finite")
        if self.xy_resolution <= 0:
            raise ValueError("xy_resolution must be positive")
        if self.yaw_bins < 4:
            raise ValueError("yaw_bins must be at least 4")
        if self.goal_position_tolerance < 0:
            raise ValueError("goal position tolerance cannot be negative")
        if not 0 <= self.goal_yaw_tolerance <= pi:
            raise ValueError("goal yaw tolerance must be between 0 and pi")


@dataclass(frozen=True, slots=True)
class _SearchNode:
    pose: Pose2D
    cost: float
    parent: int | None
    segment: tuple[Pose2D, ...]


class HybridAStarPlanner(Planner):
    """Forward/reverse-capable Hybrid A* with path-length baseline cost."""

    def __init__(self, vehicle: VehicleGeometry, config: HybridAStarConfig) -> None:
        self.vehicle = vehicle
        self.config = config

    @property
    def name(self) -> str:
        return "hybrid_astar"

    def _state_key(self, grid: OccupancyGrid, pose: Pose2D) -> StateKey:
        x_index = floor((pose.x - grid.origin_x) / self.config.xy_resolution)
        y_index = floor((pose.y - grid.origin_y) / self.config.xy_resolution)
        normalized_yaw = normalize_angle(pose.yaw)
        yaw_fraction = (normalized_yaw + pi) / (2 * pi)
        yaw_index = floor(yaw_fraction * self.config.yaw_bins) % self.config.yaw_bins
        return x_index, y_index, yaw_index

    def _is_goal(self, pose: Pose2D, goal: Pose2D) -> bool:
        distance = hypot(goal.x - pose.x, goal.y - pose.y)
        yaw_error = abs(normalize_angle(goal.yaw - pose.yaw))
        return (
            distance <= self.config.goal_position_tolerance
            and yaw_error <= self.config.goal_yaw_tolerance
        )

    def _heuristic(self, pose: Pose2D, goal: Pose2D) -> float:
        return max(
            0.0,
            hypot(goal.x - pose.x, goal.y - pose.y)
            - self.config.goal_position_tolerance,
        )

    @staticmethod
    def _reconstruct(nodes: list[_SearchNode], node_id: int) -> Path:
        chain: list[_SearchNode] = []
        current_id: int | None = node_id
        while current_id is not None:
            current = nodes[current_id]
            chain.append(current)
            current_id = current.parent
        chain.reverse()

        poses = [chain[0].pose]
        for node in chain[1:]:
            poses.extend(node.segment[1:])
        return Path(tuple(poses), cost=nodes[node_id].cost)

    def plan(
        self,
        grid: OccupancyGrid,
        start: Pose2D,
        goal: Pose2D,
        *,
        timeout_s: float | None = None,
    ) -> PlannerResult:
        if timeout_s is not None and timeout_s < 0:
            raise ValueError("timeout_s cannot be negative")

        started_at = perf_counter()

        def result(
            status: PlannerStatus,
            *,
            path: Path | None = None,
            expanded_nodes: int = 0,
        ) -> PlannerResult:
            return PlannerResult(
                status=status,
                path=path,
                expanded_nodes=expanded_nodes,
                planning_time_s=perf_counter() - started_at,
                metadata={
                    "algorithm": self.name,
                    "xy_resolution": self.config.xy_resolution,
                    "yaw_bins": self.config.yaw_bins,
                    "allow_reverse": self.config.primitives.allow_reverse,
                },
            )

        if footprint_in_collision(grid, start, self.vehicle):
            return result(PlannerStatus.INVALID_START)
        if footprint_in_collision(grid, goal, self.vehicle):
            return result(PlannerStatus.INVALID_GOAL)
        if self._is_goal(start, goal):
            return result(
                PlannerStatus.SUCCESS,
                path=Path((start,), cost=0.0),
                expanded_nodes=1,
            )

        start_node = _SearchNode(start, 0.0, None, (start,))
        nodes = [start_node]
        start_key = self._state_key(grid, start)
        best_cost: dict[StateKey, float] = {start_key: 0.0}
        insertion_order = count()
        frontier: list[tuple[float, float, int, int, StateKey]] = []
        heappush(
            frontier,
            (self._heuristic(start, goal), 0.0, next(insertion_order), 0, start_key),
        )
        expanded_nodes = 0

        while frontier:
            if timeout_s is not None and perf_counter() - started_at >= timeout_s:
                return result(PlannerStatus.TIMEOUT, expanded_nodes=expanded_nodes)

            _, queued_cost, _, node_id, state_key = heappop(frontier)
            if queued_cost != best_cost.get(state_key):
                continue
            node = nodes[node_id]
            expanded_nodes += 1

            if self._is_goal(node.pose, goal):
                return result(
                    PlannerStatus.SUCCESS,
                    path=self._reconstruct(nodes, node_id),
                    expanded_nodes=expanded_nodes,
                )

            for primitive in generate_primitives(node.pose, self.vehicle, self.config.primitives):
                if not primitive_is_collision_free(grid, primitive, self.vehicle):
                    continue
                successor = primitive.poses[-1]
                successor_key = self._state_key(grid, successor)
                successor_cost = node.cost + abs(primitive.signed_distance)
                if successor_cost >= best_cost.get(successor_key, float("inf")):
                    continue

                best_cost[successor_key] = successor_cost
                successor_node = _SearchNode(
                    pose=successor,
                    cost=successor_cost,
                    parent=node_id,
                    segment=primitive.poses,
                )
                successor_id = len(nodes)
                nodes.append(successor_node)
                priority = successor_cost + self._heuristic(successor, goal)
                heappush(
                    frontier,
                    (
                        priority,
                        successor_cost,
                        next(insertion_order),
                        successor_id,
                        successor_key,
                    ),
                )

        return result(PlannerStatus.NO_PATH, expanded_nodes=expanded_nodes)

