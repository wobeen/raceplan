"""Small deterministic PID implementation for longitudinal speed control."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class PIDConfig:
    kp: float
    ki: float
    kd: float
    output_min: float
    output_max: float
    integral_limit: float | None = None

    def __post_init__(self) -> None:
        values = (self.kp, self.ki, self.kd, self.output_min, self.output_max)
        if not all(isfinite(value) for value in values):
            raise ValueError("PID values must be finite")
        if self.output_min >= self.output_max:
            raise ValueError("PID output_min must be below output_max")
        if self.integral_limit is not None:
            if not isfinite(self.integral_limit) or self.integral_limit <= 0:
                raise ValueError("integral_limit must be finite and positive")


class PIDController:
    """Stateful PID with output clamping and conditional integration."""

    def __init__(self, config: PIDConfig) -> None:
        self.config = config
        self.reset()

    def reset(self) -> None:
        self._integral = 0.0
        self._previous_error: float | None = None

    def update(self, setpoint: float, measurement: float, dt: float) -> float:
        if not all(isfinite(value) for value in (setpoint, measurement, dt)):
            raise ValueError("PID inputs must be finite")
        if dt <= 0:
            raise ValueError("PID dt must be positive")

        error = setpoint - measurement
        candidate_integral = self._integral + error * dt
        if self.config.integral_limit is not None:
            limit = self.config.integral_limit
            candidate_integral = max(-limit, min(limit, candidate_integral))
        derivative = (
            0.0
            if self._previous_error is None
            else (error - self._previous_error) / dt
        )
        raw = (
            self.config.kp * error
            + self.config.ki * candidate_integral
            + self.config.kd * derivative
        )
        output = max(self.config.output_min, min(self.config.output_max, raw))

        # Do not wind the integral farther into a saturated output.
        saturating_high = raw > self.config.output_max and error > 0
        saturating_low = raw < self.config.output_min and error < 0
        if not (saturating_high or saturating_low):
            self._integral = candidate_integral
        self._previous_error = error
        return output
