"""Optional bounded forward recovery using sampled physical-body previews.

This policy uses the simulator's true pose and static map. It is not a safety
guarantee for swept collisions, map error, steering latency or dynamic obstacles.
"""
from dataclasses import dataclass
from math import isfinite, hypot
from typing import Callable

from raceplan.common import Path, PlannerResult, Pose2D, footprint_in_collision
from raceplan.planners.hybrid_primitives import rollout_bicycle

Replanner = Callable[[Pose2D, Pose2D], PlannerResult]


@dataclass(frozen=True, slots=True)
class RecoveryConfig:
    stop_speed_mps: float = .03
    stop_dwell_s: float = .5
    creep_speed_mps: float = .25
    preview_distance_m: float = .35
    minimum_clearance_m: float = .02
    progress_distance_m: float = .25
    progress_timeout_s: float = 6.0
    max_restarts: int = 8
    max_replans: int = 3
    policy_version: int = 2
    resume_dwell_s: float = .75
    resume_speed_margin_mps: float = .15
    feasibility_time_s: float = 5.0
    feasibility_progress_m: float = .5
    repeated_path_tolerance_m: float = .1

    def __post_init__(self):
        values = (self.stop_speed_mps, self.stop_dwell_s, self.creep_speed_mps,
                  self.preview_distance_m, self.minimum_clearance_m,
                  self.progress_distance_m, self.progress_timeout_s,
                  self.resume_dwell_s, self.resume_speed_margin_mps,
                  self.feasibility_time_s, self.feasibility_progress_m,
                  self.repeated_path_tolerance_m)
        if any(not isfinite(x) or x <= 0 for x in values):
            raise ValueError('recovery values must be finite and positive')
        if any(isinstance(x, bool) or not isinstance(x, int) or x < 0
               for x in (self.max_restarts, self.max_replans)):
            raise ValueError('recovery budgets must be non-negative integers')
        if isinstance(self.policy_version, bool) or self.policy_version not in (1, 2):
            raise ValueError('recovery policy version must be 1 or 2')


class PathProgress:
    """Local polyline projection, bounded by physical movement at crossings.

    The cursor may move backward, but only forward gain from the watchdog's
    anchor earns progress. A spatial anchor additionally rejects oscillation.
    """
    def __init__(self, path, pose):
        self.segments = []
        total = 0.0
        for a, b in zip(path.poses, path.poses[1:]):
            length = hypot(b.x-a.x, b.y-a.y)
            if length:
                self.segments.append((a, b, total, length))
                total += length
        self.cursor = 0.0
        self.pose = pose
        self.update(pose)

    def update(self, pose):
        movement = hypot(pose.x-self.pose.x, pose.y-self.pose.y)
        low, high = max(0.0, self.cursor-.5), self.cursor + movement + .5
        candidates = []
        for a, b, start, length in self.segments:
            if start > high or start+length < low:
                continue
            fraction = ((pose.x-a.x)*(b.x-a.x)+(pose.y-a.y)*(b.y-a.y))/length**2
            fraction = max(max(0.0, (low-start)/length),
                           min(min(1.0, (high-start)/length), fraction))
            gap = hypot(pose.x-a.x-fraction*(b.x-a.x), pose.y-a.y-fraction*(b.y-a.y))
            candidates.append((gap, start+fraction*length))
        if candidates:
            gap, projected = min(candidates, key=lambda item: (item[0], abs(item[1]-self.cursor)))
            if gap <= .75:
                # Projection gains cannot jump ahead faster than actual movement.
                self.cursor = min(projected, self.cursor+movement)
        self.pose = pose
        return self.cursor


def path_prefix(path, pose, distance=2.0, spacing=.1):
    """Sample the forward path suffix nearest the stopped pose, ignoring density."""
    if len(path.poses) == 1:
        return path.poses
    candidates = []
    for index, (a, b) in enumerate(zip(path.poses, path.poses[1:])):
        squared = (b.x-a.x)**2 + (b.y-a.y)**2
        fraction = max(0.0, min(1.0, ((pose.x-a.x)*(b.x-a.x)+(pose.y-a.y)*(b.y-a.y))/squared)) if squared else 0.0
        projected = Pose2D(a.x+fraction*(b.x-a.x), a.y+fraction*(b.y-a.y))
        candidates.append((hypot(projected.x-pose.x, projected.y-pose.y), index, projected))
    _, nearest, projected = min(candidates, key=lambda item: item[:2])
    suffix = (projected,) + path.poses[nearest+1:]
    points = [projected]
    remaining = spacing
    travelled = 0.0
    for a, b in zip(suffix, suffix[1:]):
        length = hypot(b.x-a.x, b.y-a.y)
        offset = remaining
        while length > 0 and offset <= length+1e-9 and travelled+offset <= distance+1e-9:
            f = min(1.0, offset/length)
            points.append(Pose2D(a.x+f*(b.x-a.x), a.y+f*(b.y-a.y)))
            offset += spacing
        if travelled+length >= distance:
            break
        remaining = offset-length
        travelled += length
    return tuple(points)


def repeated_path(candidate, blocked, tolerance):
    return len(candidate) == len(blocked) and all(
        hypot(a.x-b.x, a.y-b.y) <= tolerance for a, b in zip(candidate, blocked))


@dataclass(frozen=True, slots=True)
class RecoveryEvent:
    time_s: float
    kind: str
    pose: Pose2D
    reason: str
    path: Path | None = None
    planning_time_s: float = 0.0
    validation_time_s: float = 0.0


def creep_speed_cap(grid, clearance, pose, speed, steering, vehicle, simulation, guard, config):
    """Allow a lateral-cap override only when the actual forward arc is clear.

    Recheck every control step, including the noisy applied steering. The preview
    covers one interval plus braking distance and margin at the candidate speed.
    A wall beside the car can therefore permit slow forward travel, while a wall
    ahead still blocks it. The baseline guard itself remains unchanged.
    """
    candidate = min(config.creep_speed_mps, simulation.max_speed)
    checked_speed = max(speed, candidate)
    distance = max(config.preview_distance_m,
                   checked_speed * simulation.dt
                   + checked_speed**2 / (2 * simulation.max_deceleration)
                   + guard.stop_margin_m + guard.sample_distance_m)
    poses = rollout_bicycle(pose, steering_angle=steering, signed_distance=distance,
                            wheelbase=vehicle.wheelbase,
                            sample_distance=guard.sample_distance_m)
    if any(footprint_in_collision(grid, p, vehicle)
           or clearance.footprint(p, vehicle) < config.minimum_clearance_m for p in poses):
        return 0.0
    return candidate
