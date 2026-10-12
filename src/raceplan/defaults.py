"""Development defaults shared by command-line smoke experiments."""

from raceplan.common import VehicleGeometry
from raceplan.controllers import PIDConfig, PurePursuitConfig
from raceplan.planners import HybridAStarConfig, HybridAStarPlanner
from raceplan.planners.hybrid_primitives import MotionPrimitiveConfig
from raceplan.simulator import SimulationConfig


def baseline_vehicle() -> VehicleGeometry:
    return VehicleGeometry(
        wheelbase=0.33,
        length=0.58,
        width=0.31,
        rear_axle_to_center=0.10,
    )


def baseline_hybrid_astar() -> HybridAStarPlanner:
    """Return development defaults; official experiments will load config."""

    config = HybridAStarConfig(
        xy_resolution=0.5,
        yaw_bins=36,
        goal_position_tolerance=0.5,
        goal_yaw_tolerance=0.35,
        primitives=MotionPrimitiveConfig(
            max_steering_angle=0.45,
            steering_samples=5,
            travel_distance=0.5,
            sample_distance=0.1,
            allow_reverse=False,
        ),
    )
    return HybridAStarPlanner(baseline_vehicle(), config)


def baseline_tracker_config() -> PurePursuitConfig:
    return PurePursuitConfig(
        lookahead_distance=0.8,
        target_speed=0.8,
        max_steering_angle=0.45,
        speed_pid=PIDConfig(
            kp=2.0,
            ki=0.2,
            kd=0.05,
            output_min=-3.0,
            output_max=2.0,
            integral_limit=2.0,
        ),
    )


def baseline_simulation_config() -> SimulationConfig:
    return SimulationConfig(
        dt=0.05,
        max_time_s=30.0,
        max_speed=2.0,
        max_acceleration=2.0,
        max_deceleration=3.0,
        max_steering_angle=0.45,
        goal_tolerance=0.5,
    )
