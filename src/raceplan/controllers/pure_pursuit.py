"""Pure Pursuit lateral tracking with PID longitudinal control."""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, hypot, isfinite, sin

from raceplan.common import Path, Pose2D, VehicleGeometry
from raceplan.planners.hybrid_primitives import normalize_angle

from .pid import PIDConfig, PIDController


@dataclass(frozen=True, slots=True)
class PurePursuitConfig:
    lookahead_distance: float
    target_speed: float
    max_steering_angle: float
    speed_pid: PIDConfig
    approach_distance: float | None = None
    approach_min_speed: float = 0.15

    def __post_init__(self) -> None:
        if self.approach_distance is not None and (
            not isfinite(self.approach_distance) or self.approach_distance <= 0
        ):
            raise ValueError("approach distance must be finite and positive")
        if not isfinite(self.approach_min_speed) or self.approach_min_speed <= 0 or (
            self.approach_distance is not None and self.approach_min_speed > self.target_speed
        ):
            raise ValueError("approach minimum speed must be in (0, target speed]")
        values = (
            self.lookahead_distance,
            self.target_speed,
            self.max_steering_angle,
        )
        if not all(isfinite(value) for value in values):
            raise ValueError("Pure Pursuit values must be finite")
        if self.lookahead_distance <= 0 or self.target_speed <= 0:
            raise ValueError("lookahead distance and target speed must be positive")
        if self.max_steering_angle <= 0:
            raise ValueError("max steering angle must be positive")


@dataclass(frozen=True, slots=True)
class ControlCommand:
    acceleration: float
    steering_angle: float
    target_index: int
    tracking_error: float


def _point_segment_distance(point: Pose2D, first: Pose2D, second: Pose2D) -> float:
    dx = second.x - first.x
    dy = second.y - first.y
    squared_length = dx * dx + dy * dy
    if squared_length == 0:
        return hypot(point.x - first.x, point.y - first.y)
    projection = (
        (point.x - first.x) * dx + (point.y - first.y) * dy
    ) / squared_length
    projection = max(0.0, min(1.0, projection))
    nearest_x = first.x + projection * dx
    nearest_y = first.y + projection * dy
    return hypot(point.x - nearest_x, point.y - nearest_y)


def path_tracking_error(path: Path, pose: Pose2D) -> float:
    """Return unsigned distance to the closest path segment."""

    if len(path.poses) == 1:
        only = path.poses[0]
        return hypot(pose.x - only.x, pose.y - only.y)
    return min(
        _point_segment_distance(pose, first, second)
        for first, second in zip(path.poses, path.poses[1:])
    )


class PurePursuitController:
    """Forward-only path tracker whose tuning is independent of the planner."""

    def __init__(
        self,
        path: Path,
        vehicle: VehicleGeometry,
        config: PurePursuitConfig,
    ) -> None:
        self.path = path
        self.vehicle = vehicle
        self.config = config
        self._speed_pid = PIDController(config.speed_pid)
        self._progress_index = 0
        self._remaining = [0.0] * len(path.poses)
        for i in range(len(path.poses) - 2, -1, -1):
            a, b = path.poses[i:i + 2]
            self._remaining[i] = self._remaining[i + 1] + hypot(b.x - a.x, b.y - a.y)

    def command(self, pose: Pose2D, speed: float, dt: float) -> ControlCommand:
        poses = self.path.poses
        nearest_index = min(
            range(self._progress_index, len(poses)),
            key=lambda index: hypot(poses[index].x - pose.x, poses[index].y - pose.y),
        )
        self._progress_index = nearest_index

        target_index = nearest_index
        distance_along = hypot(
            poses[nearest_index].x - pose.x,
            poses[nearest_index].y - pose.y,
        )
        while target_index < len(poses) - 1 and distance_along < self.config.lookahead_distance:
            first = poses[target_index]
            target_index += 1
            second = poses[target_index]
            distance_along += hypot(second.x - first.x, second.y - first.y)

        target = poses[target_index]
        target_distance = hypot(target.x - pose.x, target.y - pose.y)
        target_heading = atan2(target.y - pose.y, target.x - pose.x)
        alpha = normalize_angle(target_heading - pose.yaw)
        steering = atan2(
            2.0 * self.vehicle.wheelbase * sin(alpha),
            max(target_distance, 1e-9),
        )
        steering = max(
            -self.config.max_steering_angle,
            min(self.config.max_steering_angle, steering),
        )
        target_speed = self.config.target_speed
        if self.config.approach_distance is not None:
            # Remaining polyline distance avoids slowing beside an early pass near the endpoint.
            remaining = self._remaining[nearest_index] + hypot(
                poses[nearest_index].x - pose.x, poses[nearest_index].y - pose.y
            )
            target_speed = min(target_speed, max(
                self.config.approach_min_speed,
                target_speed * remaining / self.config.approach_distance,
            ))
        acceleration = self._speed_pid.update(target_speed, speed, dt)
        return ControlCommand(
            acceleration=acceleration,
            steering_angle=steering,
            target_index=target_index,
            tracking_error=path_tracking_error(self.path, pose),
        )
