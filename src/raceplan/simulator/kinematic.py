"""Fixed-step kinematic bicycle simulation and episode accounting."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import cos, hypot, isfinite, sqrt, sin, tan

from raceplan.common import (
    OccupancyGrid,
    Path,
    Pose2D,
    VehicleGeometry,
    footprint_in_collision,
)
from raceplan.controllers import (
    PurePursuitConfig,
    PurePursuitController,
    path_tracking_error,
)
from raceplan.planners.hybrid_primitives import normalize_angle
from .noise import NoiseConfig, NoiseStreams
from .obstacle_guard import ObstacleGuardConfig, guarded_acceleration


@dataclass(frozen=True, slots=True)
class VehicleState:
    pose: Pose2D
    speed: float = 0.0


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    dt: float = 0.05
    max_time_s: float = 30.0
    max_speed: float = 2.0
    max_acceleration: float = 2.0
    max_deceleration: float = 3.0
    max_steering_angle: float = 0.45
    goal_tolerance: float = 0.5
    goal_yaw_tolerance: float | None = None

    def __post_init__(self) -> None:
        if self.goal_yaw_tolerance is not None and (
            not isfinite(self.goal_yaw_tolerance) or not 0 < self.goal_yaw_tolerance <= 3.141592653589793
        ):
            raise ValueError("goal yaw tolerance must be finite and in (0, pi]")
        values = (
            self.dt,
            self.max_time_s,
            self.max_speed,
            self.max_acceleration,
            self.max_deceleration,
            self.max_steering_angle,
            self.goal_tolerance,
        )
        if not all(isfinite(value) for value in values):
            raise ValueError("simulation values must be finite")
        if any(value <= 0 for value in values):
            raise ValueError("simulation values must be positive")


class SimulationStatus(StrEnum):
    REACHED = "reached"
    COLLISION = "collision"
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class TrajectorySample:
    time_s: float
    state: VehicleState
    acceleration: float
    steering_angle: float
    tracking_error: float


@dataclass(frozen=True, slots=True)
class SimulationResult:
    status: SimulationStatus
    samples: tuple[TrajectorySample, ...]
    completion_time_s: float
    goal_distance: float
    steering_limit: float
    goal_yaw_error: float = 0.0

    @property
    def reached(self) -> bool:
        return self.status is SimulationStatus.REACHED

    @property
    def collided(self) -> bool:
        return self.status is SimulationStatus.COLLISION

    @property
    def tracking_rmse(self) -> float:
        return sqrt(
            sum(sample.tracking_error**2 for sample in self.samples) / len(self.samples)
        )

    @property
    def max_tracking_error(self) -> float:
        return max(sample.tracking_error for sample in self.samples)

    @property
    def steering_total_variation(self) -> float:
        return sum(
            abs(second.steering_angle - first.steering_angle)
            for first, second in zip(self.samples, self.samples[1:])
        )

    @property
    def steering_saturation_fraction(self) -> float:
        saturated = sum(
            abs(sample.steering_angle) >= self.steering_limit - 1e-9
            for sample in self.samples
        )
        return saturated / len(self.samples)


def step_bicycle(
    state: VehicleState,
    *,
    acceleration: float,
    steering_angle: float,
    vehicle: VehicleGeometry,
    config: SimulationConfig,
) -> VehicleState:
    """Advance one exact constant-control bicycle step."""

    acceleration = max(
        -config.max_deceleration,
        min(config.max_acceleration, acceleration),
    )
    steering_angle = max(
        -config.max_steering_angle,
        min(config.max_steering_angle, steering_angle),
    )
    next_speed = max(0.0, min(config.max_speed, state.speed + acceleration * config.dt))
    distance = 0.5 * (state.speed + next_speed) * config.dt
    curvature = tan(steering_angle) / vehicle.wheelbase

    if abs(curvature) < 1e-12:
        next_pose = Pose2D(
            state.pose.x + distance * cos(state.pose.yaw),
            state.pose.y + distance * sin(state.pose.yaw),
            state.pose.yaw,
        )
    else:
        next_yaw_raw = state.pose.yaw + distance * curvature
        next_pose = Pose2D(
            state.pose.x + (sin(next_yaw_raw) - sin(state.pose.yaw)) / curvature,
            state.pose.y - (cos(next_yaw_raw) - cos(state.pose.yaw)) / curvature,
            normalize_angle(next_yaw_raw),
        )
    return VehicleState(next_pose, next_speed)


def run_episode(
    grid: OccupancyGrid,
    path: Path,
    goal: Pose2D,
    vehicle: VehicleGeometry,
    tracker_config: PurePursuitConfig,
    simulation_config: SimulationConfig,
    *,
    initial_pose: Pose2D | None = None,
    simulation_seed: int = 0,
    noise: NoiseConfig = NoiseConfig(),
    obstacle_guard: ObstacleGuardConfig | None = None,
) -> SimulationResult:
    """Track one planned path with fixed controller and vehicle settings."""

    tracker = PurePursuitController(path, vehicle, tracker_config)
    clearance = None
    if obstacle_guard is not None:
        from raceplan.metrics import Clearance
        clearance = Clearance(grid)
    random = NoiseStreams(simulation_seed)
    nominal = initial_pose if initial_pose is not None else path.poses[0]
    offsets = random.initial.standard_normal(4)
    yaw = nominal.yaw + float(offsets[2]) * noise.initial_yaw_std_rad
    state = VehicleState(
        Pose2D(
            nominal.x + float(offsets[0]) * noise.initial_position_std_m,
            nominal.y + float(offsets[1]) * noise.initial_position_std_m,
            normalize_angle(yaw) if noise.initial_yaw_std_rad else yaw,
        ),
        max(0.0, min(simulation_config.max_speed,
                     float(offsets[3]) * noise.initial_speed_std_mps)),
    )
    samples: list[TrajectorySample] = [
        TrajectorySample(0.0, state, 0.0, 0.0, path_tracking_error(path, state.pose))
    ]

    def finish(status: SimulationStatus, elapsed: float) -> SimulationResult:
        return SimulationResult(
            status=status,
            samples=tuple(samples),
            completion_time_s=elapsed,
            goal_distance=hypot(goal.x - state.pose.x, goal.y - state.pose.y),
            steering_limit=simulation_config.max_steering_angle,
            goal_yaw_error=abs(normalize_angle(goal.yaw - state.pose.yaw)),
        )

    if footprint_in_collision(grid, state.pose, vehicle):
        return finish(SimulationStatus.COLLISION, 0.0)

    step_count = round(simulation_config.max_time_s / simulation_config.dt)
    for step in range(step_count + 1):
        elapsed = step * simulation_config.dt
        position_reached = hypot(goal.x - state.pose.x, goal.y - state.pose.y) <= simulation_config.goal_tolerance
        yaw_reached = simulation_config.goal_yaw_tolerance is None or abs(
            normalize_angle(goal.yaw - state.pose.yaw)
        ) <= simulation_config.goal_yaw_tolerance + 1e-12
        if position_reached and yaw_reached:
            return finish(SimulationStatus.REACHED, elapsed)
        if step == step_count:
            break

        measured_speed = state.speed + float(random.speed.standard_normal()) * noise.speed_measurement_std_mps
        command = tracker.command(state.pose, measured_speed, simulation_config.dt)
        steering = max(-simulation_config.max_steering_angle, min(
            simulation_config.max_steering_angle,
            command.steering_angle + float(random.steering.standard_normal()) * noise.steering_std_rad,
        ))
        acceleration = max(-simulation_config.max_deceleration,
                           min(simulation_config.max_acceleration, command.acceleration))
        if obstacle_guard is not None:
            acceleration = guarded_acceleration(
                grid, clearance, state.pose, state.speed, steering, acceleration,
                vehicle, simulation_config, obstacle_guard,
            )
        state = step_bicycle(
            state,
            acceleration=acceleration,
            steering_angle=steering,
            vehicle=vehicle,
            config=simulation_config,
        )
        samples.append(
            TrajectorySample(
                time_s=elapsed + simulation_config.dt,
                state=state,
                acceleration=acceleration,
                steering_angle=steering,
                tracking_error=path_tracking_error(path, state.pose),
            )
        )
        if footprint_in_collision(grid, state.pose, vehicle):
            return finish(SimulationStatus.COLLISION, elapsed + simulation_config.dt)

    return finish(SimulationStatus.TIMEOUT, simulation_config.max_time_s)
