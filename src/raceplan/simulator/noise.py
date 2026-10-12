"""Independent seeded Gaussian streams for paired simulation experiments."""

from dataclasses import dataclass, fields
from math import isfinite

import numpy as np


@dataclass(frozen=True, slots=True)
class NoiseConfig:
    initial_position_std_m: float = 0.0
    initial_yaw_std_rad: float = 0.0
    initial_speed_std_mps: float = 0.0
    steering_std_rad: float = 0.0
    speed_measurement_std_mps: float = 0.0

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if not isfinite(value) or value < 0:
                raise ValueError(f"{field.name} must be finite and non-negative")


class NoiseStreams:
    """Reset per episode; equal seeds align disturbances by simulation step.

    Initial-state, steering-actuation, and speed-measurement streams are
    independent so enabling one component does not shift another component.
    """

    def __init__(self, seed: int) -> None:
        if type(seed) is not int or seed < 0:
            raise ValueError("simulation_seed must be a non-negative integer")
        streams = np.random.SeedSequence(seed).spawn(3)
        self.initial, self.steering, self.speed = (
            np.random.Generator(np.random.PCG64(stream)) for stream in streams
        )
