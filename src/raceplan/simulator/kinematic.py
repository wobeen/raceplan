"""Fixed-step kinematic bicycle simulation and episode accounting."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from math import cos, hypot, isfinite, sqrt, sin, tan
from time import perf_counter

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
from .obstacle_guard import ObstacleGuardConfig, guarded_acceleration, guard_diagnostics
from .recovery import (RecoveryConfig, RecoveryEvent, Replanner, creep_speed_cap,
                       PathProgress, path_prefix, repeated_path)


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
    PLANNING_FAILED = "planning_failed"
    RECOVERY_FAILED = "recovery_failed"


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
    stopped_time_s: float = 0.0
    restart_count: int = 0
    replan_count: int = 0
    recovery_events: tuple[RecoveryEvent, ...] = ()
    recovery_reason: str | None = None

    @property
    def driving_time_s(self) -> float:
        return max(0.0, self.completion_time_s - self.stopped_time_s)

    @property
    def replanning_time_s(self) -> float:
        return sum(event.planning_time_s for event in self.recovery_events)

    @property
    def replan_validation_time_s(self) -> float:
        return sum(event.validation_time_s for event in self.recovery_events)

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
    recovery: RecoveryConfig | None = None,
    replanner: Replanner | None = None,
) -> SimulationResult:
    """Track one planned path with fixed controller and vehicle settings."""

    if recovery is not None and obstacle_guard is None:
        raise ValueError("recovery requires an obstacle guard")
    tracker = PurePursuitController(path, vehicle, tracker_config)
    active_path = path
    events: list[RecoveryEvent] = []
    stopped_time = 0.0
    stop_dwell = 0.0
    restarts = replans = 0
    creeping = False
    pending_replan = False
    recovery_reason = None
    progress_distance = None
    progress_time = 0.0
    resume_dwell = 0.0
    progress_cursor = 0.0
    progress_pose = None
    blocked_prefixes = []
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
    route_progress = PathProgress(active_path, state.pose) if recovery is not None and recovery.policy_version == 2 else None

    def finish(status: SimulationStatus, elapsed: float) -> SimulationResult:
        return SimulationResult(
            status=status,
            samples=tuple(samples),
            completion_time_s=elapsed,
            goal_distance=hypot(goal.x - state.pose.x, goal.y - state.pose.y),
            steering_limit=simulation_config.max_steering_angle,
            goal_yaw_error=abs(normalize_angle(goal.yaw - state.pose.yaw)),
            stopped_time_s=stopped_time,
            restart_count=restarts,
            replan_count=replans,
            recovery_events=tuple(events),
            recovery_reason=recovery_reason,
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
        requested_acceleration = acceleration
        if obstacle_guard is not None:
            acceleration = guarded_acceleration(
                grid, clearance, state.pose, state.speed, steering, acceleration,
                vehicle, simulation_config, obstacle_guard,
            )
        stop_threshold = recovery.stop_speed_mps if recovery is not None else .03
        was_stopped = state.speed <= stop_threshold
        if recovery is not None:
            distance = hypot(goal.x - state.pose.x, goal.y - state.pose.y)
            cursor = route_progress.update(state.pose) if route_progress is not None else 0.0
            if progress_distance is not None:
                advanced = distance <= progress_distance - recovery.progress_distance_m
                if route_progress is not None:
                    advanced = (cursor-progress_cursor >= recovery.progress_distance_m
                                and hypot(state.pose.x-progress_pose.x, state.pose.y-progress_pose.y)
                                >= recovery.progress_distance_m)
                if advanced:
                    progress_distance, progress_time = distance, elapsed
                    progress_cursor, progress_pose = cursor, state.pose
                elif elapsed - progress_time >= recovery.progress_timeout_s:
                    pending_replan = True
            blocked = state.speed <= recovery.stop_speed_mps and acceleration <= 0
            stop_dwell = stop_dwell + simulation_config.dt if blocked else 0.0
            cap = 0.0
            if not pending_replan and (creeping or stop_dwell >= recovery.stop_dwell_s):
                cap = creep_speed_cap(grid, clearance, state.pose, state.speed, steering,
                                      vehicle, simulation_config, obstacle_guard, recovery)
            if creeping and not pending_replan:
                if recovery.policy_version == 2:
                    diagnostics = guard_diagnostics(grid, clearance, state.pose, state.speed,
                                                    steering, vehicle, simulation_config, obstacle_guard)
                    # Enter creep at a sustained stop; exit only with sustained
                    # native-guard headroom. Noise cannot release a single frame.
                    release_speed = min(tracker_config.target_speed, simulation_config.max_speed,
                                        recovery.creep_speed_mps + recovery.resume_speed_margin_mps)
                    clear = diagnostics['speed_cap_mps'] >= release_speed and cap > 0
                    resume_dwell = resume_dwell + simulation_config.dt if clear else 0.0
                    if resume_dwell >= recovery.resume_dwell_s:
                        creeping = False
                        resume_dwell = 0.0
                        events.append(RecoveryEvent(elapsed, 'resume', state.pose, 'guard_headroom_sustained'))
                if creeping and cap > 0:
                    acceleration = max(-simulation_config.max_deceleration,
                                       min(requested_acceleration,
                                           (cap - state.speed) / simulation_config.dt))
                    stop_dwell = 0.0
                elif creeping:
                    creeping = False
                    pending_replan = True
                    events.append(RecoveryEvent(elapsed, 'stop', state.pose, 'forward_preview_blocked'))
            if stop_dwell >= recovery.stop_dwell_s and not pending_replan:
                if cap > 0 and restarts < recovery.max_restarts:
                    restarts += 1
                    creeping = True
                    resume_dwell = 0.0
                    stop_dwell = 0.0
                    if progress_distance is None:
                        progress_distance, progress_time = distance, elapsed
                        progress_cursor, progress_pose = cursor, state.pose
                    events.append(RecoveryEvent(elapsed, 'restart', state.pose, 'clear_forward_creep'))
                    acceleration = max(-simulation_config.max_deceleration,
                                       min(requested_acceleration,
                                           (cap - state.speed) / simulation_config.dt))
                else:
                    pending_replan = True
            if pending_replan:
                acceleration = -simulation_config.max_deceleration
                creeping = False
                # Planning starts only from a fully stopped physical state.
                if state.speed <= 1e-12:
                    if replanner is None or replans >= recovery.max_replans:
                        recovery_reason = 'no_replanner' if replanner is None else 'replan_budget_exhausted'
                        events.append(RecoveryEvent(elapsed, 'failed', state.pose, recovery_reason))
                        return finish(SimulationStatus.RECOVERY_FAILED, elapsed)
                    replans += 1
                    if recovery.policy_version == 2:
                        blocked_prefixes.append(path_prefix(active_path, state.pose))
                    planned = replanner(state.pose, goal)
                    events.append(RecoveryEvent(elapsed, 'replan', state.pose,
                                                planned.status.value, planned.path,
                                                planned.planning_time_s))
                    if planned.path is None:
                        recovery_reason = 'planner_' + planned.status.value
                        return finish(SimulationStatus.PLANNING_FAILED, elapsed)
                    if recovery.policy_version == 2:
                        candidate_prefix = path_prefix(planned.path, state.pose)
                        duplicate = any(repeated_path(candidate_prefix, previous,
                                                       recovery.repeated_path_tolerance_m)
                                        for previous in blocked_prefixes)
                        validation_started = perf_counter()
                        feasible = False if duplicate else replan_feasible(
                            grid, planned.path, goal, state.pose, vehicle, tracker_config,
                            simulation_config, obstacle_guard, recovery)
                        validation_time = 0.0 if duplicate else perf_counter()-validation_started
                        if not duplicate:
                            events.append(RecoveryEvent(elapsed, 'validation', state.pose,
                                                        'prefix_trackable' if feasible else 'prefix_blocked',
                                                        validation_time_s=validation_time))
                        if duplicate or not feasible:
                            recovery_reason = 'repeated_blocked_path' if duplicate else 'replan_not_trackable'
                            events.append(RecoveryEvent(elapsed, 'rejected', state.pose, recovery_reason,
                                                        planned.path))
                            return finish(SimulationStatus.RECOVERY_FAILED, elapsed)
                    # Never teleport to the planner's discretized start pose.
                    active_path = planned.path
                    tracker = PurePursuitController(active_path, vehicle, tracker_config)
                    pending_replan = False
                    stop_dwell = 0.0
                    progress_distance, progress_time = distance, elapsed
                    if route_progress is not None:
                        route_progress = PathProgress(active_path, state.pose)
                        progress_cursor, progress_pose = route_progress.cursor, state.pose
                    resume_dwell = 0.0
                    # Hold this step; the new tracker is sampled next control interval.
                    acceleration = 0.0
        if was_stopped:
            stopped_time += simulation_config.dt
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
                tracking_error=path_tracking_error(active_path, state.pose),
            )
        )
        if footprint_in_collision(grid, state.pose, vehicle):
            return finish(SimulationStatus.COLLISION, elapsed + simulation_config.dt)

    return finish(SimulationStatus.TIMEOUT, simulation_config.max_time_s)


def replan_feasible(grid, path, goal, pose, vehicle, tracker, simulation, guard, recovery):
    """Check a candidate prefix with the real tracker, guard and bicycle dynamics.

    A deterministic disposable episode has its own PID and RNG. It never updates
    the physical episode or consumes its noise stream. Zero replans prevents
    nested checks while retaining the v2 watchdog and speed-resume behavior.
    The short prefix check is necessary evidence, not full-path feasibility.
    """
    preview = run_episode(grid, path, goal, vehicle, tracker,
                          replace(simulation, max_time_s=recovery.feasibility_time_s),
                          initial_pose=pose, noise=NoiseConfig(), obstacle_guard=guard,
                          recovery=replace(recovery, policy_version=2, max_replans=0,
                                           max_restarts=1,
                                           progress_timeout_s=max(recovery.progress_timeout_s,
                                                                  recovery.feasibility_time_s+simulation.dt)))
    if preview.collided or preview.status is SimulationStatus.RECOVERY_FAILED:
        return False
    if preview.reached:
        return True
    progress = PathProgress(path, pose)
    start = progress.cursor
    for sample in preview.samples:
        progress.update(sample.state.pose)
    end = preview.samples[-1].state.pose
    return (progress.cursor-start >= recovery.feasibility_progress_m
            and hypot(end.x-pose.x, end.y-pose.y) >= recovery.feasibility_progress_m)
