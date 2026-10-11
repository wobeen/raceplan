"""Kinematic bicycle motion primitives for the future Hybrid A* search."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, cos, isfinite, pi, sin, tan

from raceplan.common import OccupancyGrid, Pose2D, VehicleGeometry, footprint_in_collision


def normalize_angle(angle: float) -> float:
    """Normalize an angle to the half-open interval [-pi, pi)."""

    return (angle + pi) % (2 * pi) - pi


@dataclass(frozen=True, slots=True)
class MotionPrimitiveConfig:
    max_steering_angle: float
    steering_samples: int
    travel_distance: float
    sample_distance: float
    allow_reverse: bool = False

    def __post_init__(self) -> None:
        numeric = (
            self.max_steering_angle,
            self.travel_distance,
            self.sample_distance,
        )
        if not all(isfinite(value) for value in numeric):
            raise ValueError("motion primitive values must be finite")
        if not 0 < self.max_steering_angle < pi / 2:
            raise ValueError("max steering angle must be between 0 and pi/2")
        if self.steering_samples < 3 or self.steering_samples % 2 == 0:
            raise ValueError("steering_samples must be an odd integer of at least 3")
        if self.travel_distance <= 0 or self.sample_distance <= 0:
            raise ValueError("travel and sample distances must be positive")

    @property
    def steering_angles(self) -> tuple[float, ...]:
        step = 2 * self.max_steering_angle / (self.steering_samples - 1)
        return tuple(
            -self.max_steering_angle + index * step
            for index in range(self.steering_samples)
        )

    @property
    def signed_distances(self) -> tuple[float, ...]:
        if self.allow_reverse:
            return self.travel_distance, -self.travel_distance
        return (self.travel_distance,)


@dataclass(frozen=True, slots=True)
class MotionPrimitive:
    steering_angle: float
    signed_distance: float
    poses: tuple[Pose2D, ...]


def rollout_bicycle(
    start: Pose2D,
    *,
    steering_angle: float,
    signed_distance: float,
    wheelbase: float,
    sample_distance: float,
) -> tuple[Pose2D, ...]:
    """Integrate an exact constant-steering bicycle arc by travelled distance."""

    values = (steering_angle, signed_distance, wheelbase, sample_distance)
    if not all(isfinite(value) for value in values):
        raise ValueError("rollout parameters must be finite")
    if abs(steering_angle) >= pi / 2:
        raise ValueError("steering angle magnitude must be below pi/2")
    if wheelbase <= 0 or sample_distance <= 0:
        raise ValueError("wheelbase and sample_distance must be positive")
    if signed_distance == 0:
        raise ValueError("signed_distance cannot be zero")

    sample_count = ceil(abs(signed_distance) / sample_distance)
    distance_step = signed_distance / sample_count
    curvature = tan(steering_angle) / wheelbase
    poses = [start]
    current = start
    for _ in range(sample_count):
        if abs(curvature) < 1e-12:
            next_pose = Pose2D(
                current.x + distance_step * cos(current.yaw),
                current.y + distance_step * sin(current.yaw),
                current.yaw,
            )
        else:
            next_yaw_raw = current.yaw + distance_step * curvature
            next_pose = Pose2D(
                current.x + (sin(next_yaw_raw) - sin(current.yaw)) / curvature,
                current.y - (cos(next_yaw_raw) - cos(current.yaw)) / curvature,
                normalize_angle(next_yaw_raw),
            )
        poses.append(next_pose)
        current = next_pose
    return tuple(poses)


def generate_primitives(
    start: Pose2D,
    vehicle: VehicleGeometry,
    config: MotionPrimitiveConfig,
) -> tuple[MotionPrimitive, ...]:
    """Generate deterministic steering/direction combinations from one pose."""

    return tuple(
        MotionPrimitive(
            steering_angle=steering,
            signed_distance=distance,
            poses=rollout_bicycle(
                start,
                steering_angle=steering,
                signed_distance=distance,
                wheelbase=vehicle.wheelbase,
                sample_distance=config.sample_distance,
            ),
        )
        for distance in config.signed_distances
        for steering in config.steering_angles
    )


def primitive_is_collision_free(
    grid: OccupancyGrid,
    primitive: MotionPrimitive,
    vehicle: VehicleGeometry,
) -> bool:
    """Require the entire sampled primitive, including its start, to be free."""

    return all(
        not footprint_in_collision(grid, pose, vehicle)
        for pose in primitive.poses
    )

