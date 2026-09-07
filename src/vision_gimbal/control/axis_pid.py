"""A bounded PID that produces requested angular velocity."""

from ..config.schema import AxisPidConfig


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)


class AxisVelocityPid:
    def __init__(self, config: AxisPidConfig) -> None:
        self.config = config
        self._integral = 0.0
        self._previous_error: float | None = None

    def reset(self) -> None:
        self._integral = 0.0
        self._previous_error = None

    def pause(self) -> None:
        self._previous_error = None

    def update(
        self,
        error_deg: float,
        dt_s: float,
        allow_integral: bool,
    ) -> float:
        dt_s = max(dt_s, 1e-4)
        if abs(error_deg) <= self.config.deadband_deg:
            self._integral *= max(0.0, 1.0 - 3.0 * dt_s)
            self._previous_error = None
            return 0.0

        derivative = 0.0
        if self._previous_error is not None:
            derivative = (error_deg - self._previous_error) / dt_s
        self._previous_error = error_deg

        candidate_integral = self._integral
        if allow_integral:
            candidate_integral = _clamp(
                self._integral + error_deg * dt_s,
                -self.config.integral_limit,
                self.config.integral_limit,
            )
        raw = (
            self.config.kp * error_deg
            + self.config.ki * candidate_integral
            + self.config.kd * derivative
        )
        output = _clamp(
            raw,
            -self.config.output_limit_deg_s,
            self.config.output_limit_deg_s,
        )
        saturated_outward = output != raw and error_deg * raw > 0.0
        if allow_integral and not saturated_outward:
            self._integral = candidate_integral
        return output
