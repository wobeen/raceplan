"""Smoothed A* with a constant-curvature lead-in when post-processing is rejected.

Development candidate for docs/LEADIN_RESCUE_DEVELOPMENT.md.  The sealed
``smoothed_astar_planner.py`` (``SmoothedLowClearance``) runs first and is
returned unchanged whenever it accepts its smoothed path.  Only when it falls
back to the raw A* path does this planner try lead-ins:

1. Constant-curvature arcs from the start pose (curvature at most 90 % of the
   bicycle limit) whose oriented footprint keeps the shared margin.
2. A* from each arc end to the goal; arcs are ranked by the heading mismatch
   between the arc end and the A* continuation, then by total length.
3. For the best ``attempts`` arcs, the arc points stay fixed while the rest is
   smoothed exactly like the base planner, then verified with the same
   footprint-margin and curvature checks.  The first verified path is returned.

If no lead-in verifies, or the time budget runs out during rescue, the base
result (raw A* path) is returned with ``rescue`` set to ``failed``/``timeout``.
The A* continuation starts at the cell centre containing the arc end, up to
0.141 m away; the junction is only accepted if the joined path passes the same
verification, so the offset can lower the rescue rate but not admit a path.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import importlib.util
from math import atan2, cos, isfinite, pi, sin
from pathlib import Path as FilePath
import sys
from time import perf_counter

import numpy as np

from raceplan.common import OccupancyGrid, Path, PlannerResult, PlannerStatus, Pose2D
from raceplan.defaults import baseline_vehicle
from raceplan.metrics import Clearance, resample
from raceplan.planners import AStarPlanner
from raceplan.planners.base import Planner


def _load_base():
    """Load the sealed base plugin by content hash without editing or re-registering it."""
    path = FilePath(__file__).resolve().with_name("smoothed_astar_planner.py")
    source = path.read_bytes()
    name = "_raceplan_smoothed_base_" + sha256(source).hexdigest()
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        exec(compile(source, str(path), "exec"), module.__dict__)
    return sys.modules[name]


base = _load_base()


@dataclass(frozen=True)
class LeadInConfig:
    curvatures: int = 9
    curvature_fraction: float = 0.9
    lengths_m: tuple[float, ...] = (0.6, 1.0, 1.4)
    attempts: int = 3
    straight_only: bool = False

    def __post_init__(self):
        if isinstance(self.curvatures, bool) or not isinstance(self.curvatures, int) \
                or self.curvatures < 1 or self.curvatures % 2 == 0:
            raise ValueError("curvatures must be a positive odd integer (includes zero)")
        if not isfinite(self.curvature_fraction) or not 0 < self.curvature_fraction <= 1:
            raise ValueError("curvature_fraction must be in (0, 1]")
        if not self.lengths_m or any(not isfinite(v) or v <= 0 for v in self.lengths_m):
            raise ValueError("lengths_m must be positive and finite")
        if isinstance(self.attempts, bool) or not isinstance(self.attempts, int) \
                or self.attempts < 1:
            raise ValueError("attempts must be a positive integer")


def arc_points(start: Pose2D, curvature: float, length: float, spacing: float):
    """Rear-axle samples and headings along a constant-curvature arc from ``start``."""
    steps = int(round(length / spacing))
    x, y, heading = start.x, start.y, start.yaw
    points, headings = [(x, y)], [heading]
    for _ in range(steps):
        if abs(curvature) < 1e-12:
            x, y = x + spacing * cos(heading), y + spacing * sin(heading)
        else:
            new = heading + curvature * spacing
            x += (sin(new) - sin(heading)) / curvature
            y += (cos(heading) - cos(new)) / curvature
            heading = new
        points.append((x, y))
        headings.append(heading)
    return np.array(points), headings


def smooth_rest(points: np.ndarray, fixed_count: int, grid: OccupancyGrid, config, clearance,
                deadline):
    """Base smoothing with the first ``fixed_count`` points and the goal fixed."""
    fixed = np.zeros(len(points), dtype=bool)
    fixed[:fixed_count] = True
    fixed[-1] = True
    step = base.implicit_smoother(len(points), fixed, config.smoothing_weight)
    for _ in range(config.iterations):
        if deadline is not None and perf_counter() >= deadline:
            return None
        distance, away = base.obstacle_distance(points, clearance.bounds, grid)
        push = np.maximum(config.target_clearance_m - distance, 0.0)[:, None] * away
        points = step(points, points + config.clearance_step * push)
    return points


def verify(points: np.ndarray, start_yaw: float, config, clearance):
    """The base planner's acceptance test: footprint margin and curvature limit."""
    poses = base.tangent_poses(points, start_yaw)
    curvature = base.max_discrete_curvature(poses, config.spacing_m)
    dense = resample(poses, base.VERIFY_SPACING_M)
    dense = base.tangent_poses(np.array([(p.x, p.y) for p in dense]), start_yaw)
    footprint = min(clearance.footprint(pose, baseline_vehicle()) for pose in dense)
    accepted = footprint >= config.footprint_margin_m and curvature <= config.max_curvature_per_m
    return accepted, poses, curvature, footprint


class LeadInRescueK3(Planner):
    """``SmoothedLowClearance`` plus lead-in rescue for rejected post-processing."""

    def __init__(self, config: LeadInConfig | None = None):
        self.config = config if config is not None else LeadInConfig()
        self.base = base.SmoothedLowClearance()

    @property
    def name(self):
        return "leadin_rescue_k3"

    def plan(self, grid: OccupancyGrid, start: Pose2D, goal: Pose2D, *, timeout_s=None):
        if timeout_s is not None and (not isfinite(timeout_s) or timeout_s < 0):
            raise ValueError("timeout_s must be finite and non-negative")
        started = perf_counter()
        deadline = None if timeout_s is None else started + timeout_s
        first = self.base.plan(grid, start, goal, timeout_s=timeout_s)
        metadata = {**first.metadata, "algorithm": self.name}

        def result(status, path, expanded, **extra):
            return PlannerResult(status, path, expanded, perf_counter() - started,
                                 {**metadata, **extra})

        if first.status is not PlannerStatus.SUCCESS:
            return result(first.status, first.path, first.expanded_nodes, rescue="base_failed")
        if first.metadata["smoothing"] == "accepted":
            return result(first.status, first.path, first.expanded_nodes, rescue="not_needed")

        def fallback(expanded, reason, **extra):
            # The verified base result (raw A* path) stays valid when rescue fails or runs out of time.
            return result(PlannerStatus.SUCCESS, first.path, expanded, rescue=reason, **extra)

        smoothing = self.base.config
        clearance = Clearance(grid)
        vehicle = baseline_vehicle()
        limit = self.config.curvature_fraction * smoothing.max_curvature_per_m
        curvatures = ([0.0] if self.config.straight_only
                      else np.linspace(-limit, limit, self.config.curvatures))
        expanded = first.expanded_nodes
        ranked = []
        for curvature in curvatures:
            for length in self.config.lengths_m:
                if deadline is not None and perf_counter() >= deadline:
                    return fallback(expanded, "timeout")
                points, headings = arc_points(start, float(curvature), length, smoothing.spacing_m)
                if any(clearance.footprint(Pose2D(x, y, h), vehicle) < smoothing.footprint_margin_m
                       for (x, y), h in zip(points, headings)):
                    continue
                end = Pose2D(float(points[-1, 0]), float(points[-1, 1]), headings[-1])
                if not grid.is_free(grid.world_to_grid(end.x, end.y)):
                    continue
                remaining = None if deadline is None else max(0.0, deadline - perf_counter())
                rest = AStarPlanner().plan(grid, end, goal, timeout_s=remaining)
                expanded += rest.expanded_nodes
                if rest.status is not PlannerStatus.SUCCESS:
                    continue
                tail = np.array([(p.x, p.y) for p in resample(rest.path.poses, smoothing.spacing_m)])
                ahead = tail[min(5, len(tail) - 1)] - tail[0]
                mismatch = (abs((atan2(ahead[1], ahead[0]) - end.yaw + pi) % (2 * pi) - pi)
                            if np.any(ahead) else 0.0)
                ranked.append((mismatch, length + rest.path.cost, float(curvature), length,
                               points, tail))
        ranked.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
        for _, _, curvature, length, points, tail in ranked[:self.config.attempts]:
            joined = np.vstack([points, tail[1:]])
            smoothed = smooth_rest(joined, len(points), grid, smoothing, clearance, deadline)
            if smoothed is None:
                return fallback(expanded, "timeout")
            accepted, poses, max_curvature, footprint = verify(smoothed, start.yaw, smoothing,
                                                               clearance)
            if accepted:
                length_m = float(np.hypot(*np.diff(smoothed, axis=0).T).sum())
                return result(PlannerStatus.SUCCESS, Path(poses, length_m), expanded,
                              smoothing="accepted", smoothing_reason="", rescue="lead_in",
                              lead_in_curvature_per_m=curvature, lead_in_length_m=length,
                              smoothed_max_curvature_per_m=max_curvature,
                              smoothed_min_footprint_clearance_m=footprint)
        return fallback(expanded, "failed", lead_in_candidates=len(ranked))


class LeadInRescueK6(LeadInRescueK3):
    def __init__(self):
        super().__init__(LeadInConfig(lengths_m=(0.6, 1.0, 1.4, 1.8), attempts=6))

    @property
    def name(self):
        return "leadin_rescue_k6"


class LeadInStraight(LeadInRescueK3):
    """Ablation: zero-curvature lead-ins only; not a selectable candidate."""

    def __init__(self):
        super().__init__(LeadInConfig(straight_only=True))

    @property
    def name(self):
        return "leadin_straight"
