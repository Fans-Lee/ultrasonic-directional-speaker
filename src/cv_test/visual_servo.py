"""Two-axis image-based PI/PID controller for a position servo gimbal."""

from dataclasses import dataclass, field
from typing import Optional, Tuple

if __package__:
    from .camera_geometry import CameraGeometry
    from .control_models import AimObservation, GimbalSetpoint, ServoOutput
else:
    from camera_geometry import CameraGeometry
    from control_models import AimObservation, GimbalSetpoint, ServoOutput


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)


@dataclass(frozen=True)
class AxisPidConfig:
    kp: float = 1.0
    ki: float = 0.08
    kd: float = 0.0
    deadband_deg: float = 0.6
    integral_limit: float = 10.0
    max_speed_deg_s: float = 25.0
    max_accel_deg_s2: float = 80.0
    min_angle_deg: float = -75.0
    max_angle_deg: float = 75.0

    def __post_init__(self) -> None:
        if self.kp < 0.0 or self.ki < 0.0 or self.kd < 0.0:
            raise ValueError("PID gains cannot be negative")
        if self.deadband_deg < 0.0 or self.integral_limit < 0.0:
            raise ValueError("deadband and integral limit cannot be negative")
        if self.max_speed_deg_s <= 0.0 or self.max_accel_deg_s2 <= 0.0:
            raise ValueError("speed and acceleration limits must be positive")
        if self.min_angle_deg >= self.max_angle_deg:
            raise ValueError("minimum angle must be less than maximum angle")


def _default_pan_config() -> AxisPidConfig:
    return AxisPidConfig()


def _default_tilt_config() -> AxisPidConfig:
    return AxisPidConfig(
        max_speed_deg_s=20.0,
        max_accel_deg_s2=60.0,
        min_angle_deg=-45.0,
        max_angle_deg=45.0,
    )


@dataclass(frozen=True)
class VisualServoConfig:
    pan: AxisPidConfig = field(default_factory=_default_pan_config)
    tilt: AxisPidConfig = field(default_factory=_default_tilt_config)
    nominal_dt_s: float = 0.10
    maximum_dt_s: float = 0.50

    def __post_init__(self) -> None:
        if self.nominal_dt_s <= 0.0:
            raise ValueError("nominal_dt_s must be positive")
        if self.maximum_dt_s < self.nominal_dt_s:
            raise ValueError("maximum_dt_s must be >= nominal_dt_s")


class AxisVelocityPid:
    """PID whose output is commanded angular velocity in degrees/second."""

    def __init__(self, config: AxisPidConfig) -> None:
        self.config = config
        self._integral = 0.0
        self._previous_error: Optional[float] = None

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

        raw_output = (
            self.config.kp * error_deg
            + self.config.ki * candidate_integral
            + self.config.kd * derivative
        )
        output = _clamp(
            raw_output,
            -self.config.max_speed_deg_s,
            self.config.max_speed_deg_s,
        )

        drives_further_into_saturation = (
            output != raw_output and error_deg * raw_output > 0.0
        )
        if allow_integral and not drives_further_into_saturation:
            self._integral = candidate_integral
        return output


class VisualServoController:
    def __init__(
        self,
        config: VisualServoConfig,
        geometry: CameraGeometry,
    ) -> None:
        self.config = config
        self.geometry = geometry
        self._pan_pid = AxisVelocityPid(config.pan)
        self._tilt_pid = AxisVelocityPid(config.tilt)
        self._pan_angle = 0.0
        self._tilt_angle = 0.0
        self._pan_speed = 0.0
        self._tilt_speed = 0.0
        self._last_timestamp: Optional[float] = None
        self._last_target_id: Optional[int] = None

    @property
    def angles(self) -> Tuple[float, float]:
        return self._pan_angle, self._tilt_angle

    def seed_angles(self, pan_degrees: float, tilt_degrees: float) -> None:
        self._pan_angle = _clamp(
            pan_degrees,
            self.config.pan.min_angle_deg,
            self.config.pan.max_angle_deg,
        )
        self._tilt_angle = _clamp(
            tilt_degrees,
            self.config.tilt.min_angle_deg,
            self.config.tilt.max_angle_deg,
        )
        self.reset_pid()

    def reset_pid(self) -> None:
        self._pan_pid.reset()
        self._tilt_pid.reset()
        self._pan_speed = 0.0
        self._tilt_speed = 0.0
        self._last_timestamp = None
        self._last_target_id = None

    def hold(self, timestamp_s: float) -> ServoOutput:
        self._pan_pid.pause()
        self._tilt_pid.pause()
        self._pan_speed = 0.0
        self._tilt_speed = 0.0
        self._last_timestamp = timestamp_s
        return ServoOutput(
            setpoint=None,
            target_id=None,
            target_observed=False,
            pan_error_deg=0.0,
            tilt_error_deg=0.0,
        )

    def update(
        self,
        observation: AimObservation,
        frame_size: Tuple[int, int],
        timestamp_s: float,
    ) -> ServoOutput:
        if observation.track_id != self._last_target_id:
            self._pan_pid.reset()
            self._tilt_pid.reset()
            self._pan_speed = 0.0
            self._tilt_speed = 0.0
            self._last_target_id = observation.track_id

        dt_s = self.config.nominal_dt_s
        if self._last_timestamp is not None:
            dt_s = _clamp(
                timestamp_s - self._last_timestamp,
                1e-4,
                self.config.maximum_dt_s,
            )
        self._last_timestamp = timestamp_s

        pan_error, tilt_error = self.geometry.error_angles_deg(
            observation,
            frame_size,
        )
        pan_integral_allowed = observation.observed and not (
            self._pan_angle >= self.config.pan.max_angle_deg
            and pan_error > 0.0
            or self._pan_angle <= self.config.pan.min_angle_deg
            and pan_error < 0.0
        )
        tilt_integral_allowed = observation.observed and not (
            self._tilt_angle >= self.config.tilt.max_angle_deg
            and tilt_error > 0.0
            or self._tilt_angle <= self.config.tilt.min_angle_deg
            and tilt_error < 0.0
        )

        requested_pan_speed = self._pan_pid.update(
            pan_error,
            dt_s,
            pan_integral_allowed,
        )
        requested_tilt_speed = self._tilt_pid.update(
            tilt_error,
            dt_s,
            tilt_integral_allowed,
        )
        self._pan_speed = self._limit_acceleration(
            requested_pan_speed,
            self._pan_speed,
            self.config.pan.max_accel_deg_s2,
            dt_s,
        )
        self._tilt_speed = self._limit_acceleration(
            requested_tilt_speed,
            self._tilt_speed,
            self.config.tilt.max_accel_deg_s2,
            dt_s,
        )
        self._pan_angle = _clamp(
            self._pan_angle + self._pan_speed * dt_s,
            self.config.pan.min_angle_deg,
            self.config.pan.max_angle_deg,
        )
        self._tilt_angle = _clamp(
            self._tilt_angle + self._tilt_speed * dt_s,
            self.config.tilt.min_angle_deg,
            self.config.tilt.max_angle_deg,
        )

        return ServoOutput(
            setpoint=GimbalSetpoint(
                timestamp_s=timestamp_s,
                pan_degrees=self._pan_angle,
                tilt_degrees=self._tilt_angle,
            ),
            target_id=observation.track_id,
            target_observed=observation.observed,
            pan_error_deg=pan_error,
            tilt_error_deg=tilt_error,
        )

    @staticmethod
    def _limit_acceleration(
        requested_speed: float,
        current_speed: float,
        maximum_acceleration: float,
        dt_s: float,
    ) -> float:
        maximum_change = maximum_acceleration * dt_s
        return _clamp(
            requested_speed,
            current_speed - maximum_change,
            current_speed + maximum_change,
        )

