"""Integrate velocity through shared acceleration and angle limits."""

from typing import Optional

from ..config.schema import AxisMotionConfig, GimbalMotionConfig
from ..domain.control import GimbalSetpoint, MotionRequest
from ..domain.geometry import GimbalPose


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)


class GimbalMotionLimiter:
    def __init__(self, config: GimbalMotionConfig) -> None:
        self.config = config
        self._pose = GimbalPose()
        self._pan_speed = 0.0
        self._tilt_speed = 0.0
        self._last_timestamp: Optional[float] = None

    @property
    def pose(self) -> GimbalPose:
        return self._pose

    def seed(self, pose: GimbalPose) -> None:
        self._pose = GimbalPose(
            _clamp(
                pose.pan_degrees,
                self.config.pan.min_angle_deg,
                self.config.pan.max_angle_deg,
            ),
            _clamp(
                pose.tilt_degrees,
                self.config.tilt.min_angle_deg,
                self.config.tilt.max_angle_deg,
            ),
        )
        self._pan_speed = 0.0
        self._tilt_speed = 0.0
        self._last_timestamp = None

    def hold(self, timestamp_s: float) -> GimbalSetpoint:
        self._pan_speed = 0.0
        self._tilt_speed = 0.0
        self._last_timestamp = timestamp_s
        return GimbalSetpoint(
            timestamp_s,
            self._pose.pan_degrees,
            self._pose.tilt_degrees,
        )

    def update(
        self,
        request: MotionRequest,
        timestamp_s: float,
    ) -> GimbalSetpoint:
        dt_s = self.config.nominal_dt_s
        if self._last_timestamp is not None:
            dt_s = min(
                max(timestamp_s - self._last_timestamp, 1e-4),
                self.config.maximum_dt_s,
            )
        self._last_timestamp = timestamp_s
        self._pan_speed = self._next_speed(
            request.pan_velocity_deg_s,
            self._pan_speed,
            self.config.pan,
            dt_s,
        )
        self._tilt_speed = self._next_speed(
            request.tilt_velocity_deg_s,
            self._tilt_speed,
            self.config.tilt,
            dt_s,
        )
        pan = _clamp(
            self._pose.pan_degrees + self._pan_speed * dt_s,
            self.config.pan.min_angle_deg,
            self.config.pan.max_angle_deg,
        )
        tilt = _clamp(
            self._pose.tilt_degrees + self._tilt_speed * dt_s,
            self.config.tilt.min_angle_deg,
            self.config.tilt.max_angle_deg,
        )
        if pan in (self.config.pan.min_angle_deg, self.config.pan.max_angle_deg):
            if (pan == self.config.pan.min_angle_deg and self._pan_speed < 0.0) or (
                pan == self.config.pan.max_angle_deg and self._pan_speed > 0.0
            ):
                self._pan_speed = 0.0
        if tilt in (
            self.config.tilt.min_angle_deg,
            self.config.tilt.max_angle_deg,
        ):
            if (
                tilt == self.config.tilt.min_angle_deg
                and self._tilt_speed < 0.0
            ) or (
                tilt == self.config.tilt.max_angle_deg
                and self._tilt_speed > 0.0
            ):
                self._tilt_speed = 0.0
        self._pose = GimbalPose(pan, tilt)
        return GimbalSetpoint(timestamp_s, pan, tilt)

    @staticmethod
    def _next_speed(
        requested: float,
        current: float,
        config: AxisMotionConfig,
        dt_s: float,
    ) -> float:
        requested = _clamp(
            requested,
            -config.max_speed_deg_s,
            config.max_speed_deg_s,
        )
        maximum_change = config.max_accel_deg_s2 * dt_s
        return _clamp(
            requested,
            current - maximum_change,
            current + maximum_change,
        )
