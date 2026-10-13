"""Map-based speed supervision; sampled prediction, not a swept-collision guarantee."""
from dataclasses import dataclass
from math import isfinite, sqrt

from raceplan.common import footprint_in_collision
from raceplan.planners.hybrid_primitives import rollout_bicycle


@dataclass(frozen=True, slots=True)
class ObstacleGuardConfig:
    horizon_m: float = 1.0
    sample_distance_m: float = .05
    stop_margin_m: float = .08
    slowdown_clearance_m: float = .3

    def __post_init__(self):
        if any(not isfinite(x) or x <= 0 for x in (
            self.horizon_m, self.sample_distance_m, self.stop_margin_m, self.slowdown_clearance_m
        )):
            raise ValueError('guard values must be finite and positive')
        if self.sample_distance_m > self.horizon_m or self.stop_margin_m >= self.horizon_m:
            raise ValueError('guard sample/margin must fit horizon')


def guarded_acceleration(grid, clearance, pose, speed, steering, acceleration,
                         vehicle, simulation, config):
    """Limit speed using current body clearance and a constant-steering preview.

    Uses true simulated state and known static map. Does not replan or change steering.
    Braking can fail if the vehicle is already inside its stopping distance.
    """
    gap = clearance.footprint(pose, vehicle)
    lateral_cap = simulation.max_speed * min(1.0, max(0.0,
        (gap - config.stop_margin_m) / config.slowdown_clearance_m))
    # Extend the preview if a caller selects a higher speed than the default horizon supports.
    horizon = max(config.horizon_m, speed * simulation.dt + speed**2 / (2*simulation.max_deceleration)
                  + config.stop_margin_m + config.sample_distance_m)
    poses = rollout_bicycle(pose, steering_angle=steering, signed_distance=horizon,
                            wheelbase=vehicle.wheelbase, sample_distance=config.sample_distance_m)
    free = horizon
    step = horizon / (len(poses) - 1)
    for i, predicted in enumerate(poses):
        if footprint_in_collision(grid, predicted, vehicle):
            free = max(0.0, (i-1)*step)
            break
    available = max(0.0, free - config.stop_margin_m)
    a = simulation.max_deceleration
    # Reserve one control interval in addition to continuous braking distance.
    braking_cap = sqrt((a*simulation.dt)**2 + 2*a*available) - a*simulation.dt
    cap = min(lateral_cap, braking_cap)
    return max(-a, min(acceleration, (cap-speed)/simulation.dt))
