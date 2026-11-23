"""A* followed by collision-checked clearance/curvature smoothing.

Development-only user planner for the hypothesis left open by
docs/SHARP_TURN_DEVELOPMENT_20261105.md: instead of adding turn costs to the
point-grid search, post-process the plain A* path.

1. Resample the A* path at ``spacing_m`` and pin the first step to the start yaw.
2. Run a fixed number of implicit elastic-band steps.  Each step pushes the
   rear-axle reference points away from the nearest occupied cell square or
   map edge while they are closer than ``target_clearance_m`` and then solves
   ``min smoothing_weight * sum |second difference|^2 + sum |p - pushed|^2``
   with the first two points and the goal point fixed.  The implicit solve is
   unconditionally stable, so corners are rounded over a path-length scale
   instead of only between neighbouring samples.
3. Accept the result only if every 0.05 m sample of the oriented vehicle
   footprint (yaw = path tangent) keeps ``footprint_margin_m`` clearance and the
   maximum discrete curvature does not exceed the bicycle-model limit.
   Otherwise return the unmodified A* path and record the rejection reason.

The search, the vehicle model, and the controller are unchanged; only the
reference path differs.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, isfinite, pi, sin, tan
from time import perf_counter

import numpy as np

from raceplan.common import OccupancyGrid, Path, PlannerResult, PlannerStatus, Pose2D
from raceplan.defaults import baseline_tracker_config, baseline_vehicle
from raceplan.metrics import Clearance, resample
from raceplan.planners import AStarPlanner
from raceplan.planners.base import Planner

VERIFY_SPACING_M = 0.05


def bicycle_curvature_limit() -> float:
    """Largest curvature the shared tracker may command with the shared vehicle."""
    return tan(baseline_tracker_config().max_steering_angle) / baseline_vehicle().wheelbase


@dataclass(frozen=True)
class SmoothingConfig:
    target_clearance_m: float = 0.45
    footprint_margin_m: float = 0.02
    spacing_m: float = 0.1
    iterations: int = 100
    smoothing_weight: float = 100.0
    clearance_step: float = 0.5
    max_curvature_per_m: float = bicycle_curvature_limit()

    def __post_init__(self):
        values = (self.target_clearance_m, self.footprint_margin_m, self.spacing_m,
                  self.smoothing_weight, self.clearance_step, self.max_curvature_per_m)
        if any(not isfinite(value) or value < 0 for value in values):
            raise ValueError("smoothing parameters must be finite and non-negative")
        if self.spacing_m <= 0 or self.max_curvature_per_m <= 0:
            raise ValueError("spacing_m and max_curvature_per_m must be positive")
        if isinstance(self.iterations, bool) or not isinstance(self.iterations, int) \
                or self.iterations < 0:
            raise ValueError("iterations must be a non-negative integer")


def obstacle_distance(points: np.ndarray, bounds: np.ndarray, grid: OccupancyGrid):
    """Distance and unit away-direction from each point to the nearest obstacle.

    Obstacles are occupied cell squares (``bounds`` rows: x0, y0, x1, y1) and
    the map exterior.  Points inside an occupied square get zero distance and
    no direction; the verification step rejects such paths.
    """
    x, y = points[:, 0:1], points[:, 1:2]
    right = grid.origin_x + grid.width * grid.resolution
    top = grid.origin_y + grid.height * grid.resolution
    edge = np.hstack([x - grid.origin_x, right - x, y - grid.origin_y, top - y])
    edge_direction = np.array([[1.0, 0.0], [-1.0, 0.0], [0.0, 1.0], [0.0, -1.0]])
    nearest = edge.min(axis=1)
    direction = edge_direction[edge.argmin(axis=1)]
    if len(bounds):
        dx = np.where(x < bounds[:, 0], x - bounds[:, 0],
                      np.where(x > bounds[:, 2], x - bounds[:, 2], 0.0))
        dy = np.where(y < bounds[:, 1], y - bounds[:, 1],
                      np.where(y > bounds[:, 3], y - bounds[:, 3], 0.0))
        distance = np.hypot(dx, dy)
        index = distance.argmin(axis=1)
        rows = np.arange(len(points))
        cell = distance[rows, index]
        closer = cell < nearest
        safe = np.where(cell > 0, cell, 1.0)
        cell_direction = np.stack([dx[rows, index] / safe, dy[rows, index] / safe], axis=1)
        cell_direction[cell <= 0] = 0.0
        nearest = np.where(closer, cell, nearest)
        direction = np.where(closer[:, None], cell_direction, direction)
    return np.maximum(nearest, 0.0), direction


def implicit_smoother(count: int, fixed: np.ndarray, weight: float):
    """Return ``step(points, pushed)`` minimizing weight*|D2 p|^2 + |p - pushed|^2.

    Rows in ``fixed`` keep their current coordinates.  The linear system is
    factored once per path because its matrix depends only on the sample count.
    """
    second = np.zeros((count - 2, count))
    rows = np.arange(count - 2)
    second[rows, rows] = 1.0
    second[rows, rows + 1] = -2.0
    second[rows, rows + 2] = 1.0
    laplacian = weight * (second.T @ second)
    free = ~fixed
    inverse = np.linalg.inv(np.eye(int(free.sum())) + laplacian[np.ix_(free, free)])
    coupling = laplacian[np.ix_(free, fixed)]

    def step(points: np.ndarray, pushed: np.ndarray) -> np.ndarray:
        updated = points.copy()
        updated[free] = inverse @ (pushed[free] - coupling @ points[fixed])
        return updated

    return step


def tangent_poses(points: np.ndarray, start_yaw: float) -> tuple[Pose2D, ...]:
    """Poses whose yaw is the forward chord direction; the last keeps the final chord."""
    headings = [atan2(b[1] - a[1], b[0] - a[0]) for a, b in zip(points, points[1:])]
    headings = headings + [headings[-1]] if headings else [start_yaw]
    return tuple(Pose2D(float(x), float(y), yaw) for (x, y), yaw in zip(points, headings))


def max_discrete_curvature(poses: tuple[Pose2D, ...], spacing: float) -> float:
    """Same definition as ``raceplan.metrics.path_metrics`` at the given spacing."""
    samples = resample(poses, spacing)
    if len(samples) < 3:
        return 0.0
    length = sum(np.hypot(b.x - a.x, b.y - a.y) for a, b in zip(samples, samples[1:]))
    headings = [atan2(b.y - a.y, b.x - a.x) for a, b in zip(samples, samples[1:])]
    turns = [abs((b - a + pi) % (2 * pi) - pi) for a, b in zip(headings, headings[1:])]
    return max(turns) / (length / (len(samples) - 1))


class SmoothedAStar(Planner):
    """Plain A* reference path, post-processed and verified before use."""

    def __init__(self, config: SmoothingConfig | None = None):
        self.config = config if config is not None else SmoothingConfig()

    @property
    def name(self):
        return "smoothed_astar"

    def plan(self, grid: OccupancyGrid, start: Pose2D, goal: Pose2D, *, timeout_s=None):
        if timeout_s is not None and (not isfinite(timeout_s) or timeout_s < 0):
            raise ValueError("timeout_s must be finite and non-negative")
        started = perf_counter()
        base = AStarPlanner().plan(grid, start, goal, timeout_s=timeout_s)
        metadata = {"algorithm": self.name, "base_planner": "astar",
                    "goal_yaw_constrained": False}

        def result(status, path=None, **extra):
            return PlannerResult(status, path, base.expanded_nodes,
                                 perf_counter() - started, {**metadata, **extra})

        if base.status is not PlannerStatus.SUCCESS:
            return result(base.status, smoothing="not_run")

        config = self.config
        raw = base.path
        dense = resample(raw.poses, config.spacing_m)
        if len(dense) < 4:
            return result(PlannerStatus.SUCCESS, raw, smoothing="rejected",
                          smoothing_reason="too_short")
        points = np.array([(pose.x, pose.y) for pose in dense], dtype=float)
        # Pin the first step to the start heading so tracking begins aligned.
        points[1] = points[0] + config.spacing_m * np.array([cos(start.yaw), sin(start.yaw)])
        fixed = np.zeros(len(points), dtype=bool)
        fixed[[0, 1, -1]] = True
        step = implicit_smoother(len(points), fixed, config.smoothing_weight)
        clearance = Clearance(grid)

        for _ in range(config.iterations):
            if timeout_s is not None and perf_counter() - started >= timeout_s:
                return result(PlannerStatus.TIMEOUT)
            distance, away = obstacle_distance(points, clearance.bounds, grid)
            push = np.maximum(config.target_clearance_m - distance, 0.0)[:, None] * away
            points = step(points, points + config.clearance_step * push)

        poses = tangent_poses(points, start.yaw)
        curvature = max_discrete_curvature(poses, config.spacing_m)
        vehicle = baseline_vehicle()
        verify = resample(poses, VERIFY_SPACING_M)
        verify = tangent_poses(np.array([(pose.x, pose.y) for pose in verify]), start.yaw)
        footprint = min(clearance.footprint(pose, vehicle) for pose in verify)
        diagnostics = {"smoothed_max_curvature_per_m": curvature,
                       "smoothed_min_footprint_clearance_m": footprint}
        if footprint < config.footprint_margin_m:
            return result(PlannerStatus.SUCCESS, raw, smoothing="rejected",
                          smoothing_reason="footprint_clearance", **diagnostics)
        if curvature > config.max_curvature_per_m:
            return result(PlannerStatus.SUCCESS, raw, smoothing="rejected",
                          smoothing_reason="curvature", **diagnostics)
        length = float(np.hypot(*np.diff(points, axis=0).T).sum())
        return result(PlannerStatus.SUCCESS, Path(poses, length), smoothing="accepted",
                      **diagnostics)


class SmoothedLowClearance(SmoothedAStar):
    def __init__(self):
        super().__init__(SmoothingConfig(target_clearance_m=0.30))

    @property
    def name(self):
        return "smoothed_low_clearance"


class SmoothedNoClearance(SmoothedAStar):
    """Ablation: curvature smoothing and verification without the clearance spring."""

    def __init__(self):
        super().__init__(SmoothingConfig(target_clearance_m=0.0))

    @property
    def name(self):
        return "smoothed_no_clearance"
