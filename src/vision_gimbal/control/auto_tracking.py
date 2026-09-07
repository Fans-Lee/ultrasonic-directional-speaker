"""Explicit-target visual tracking controller."""

from ..config.schema import AutoControlConfig, GimbalMotionConfig
from ..domain.control import AutoControlTelemetry, MotionRequest
from ..domain.geometry import GimbalPose
from ..domain.tracking import TargetObservation
from .axis_pid import AxisVelocityPid
from .camera_projection import CameraProjection
from .close_range_aim import CloseRangeAimPolicy


class AutoTrackingController:
    def __init__(
        self,
        config: AutoControlConfig,
        projection: CameraProjection,
        close_range: CloseRangeAimPolicy,
        motion_config: GimbalMotionConfig,
    ) -> None:
        self.config = config
        self.projection = projection
        self.close_range = close_range
        self.motion_config = motion_config
        self._pan_pid = AxisVelocityPid(config.pan_pid)
        self._tilt_pid = AxisVelocityPid(config.tilt_pid)
        self._last_timestamp = None
        self._last_target_id = None

    def reset(self) -> None:
        self._pan_pid.reset()
        self._tilt_pid.reset()
        self.close_range.reset()
        self._last_timestamp = None
        self._last_target_id = None

    def hold(self, timestamp_s: float) -> AutoControlTelemetry:
        self._pan_pid.pause()
        self._tilt_pid.pause()
        self._last_timestamp = timestamp_s
        return AutoControlTelemetry()

    def update(
        self,
        observation: TargetObservation,
        frame_size,
        timestamp_s: float,
        commanded_pose: GimbalPose,
    ):
        if observation.track_id != self._last_target_id:
            self.reset()
            self._last_target_id = observation.track_id

        dt_s = self.config.nominal_dt_s
        if self._last_timestamp is not None:
            dt_s = min(
                max(timestamp_s - self._last_timestamp, 1e-4),
                self.config.maximum_dt_s,
            )
        self._last_timestamp = timestamp_s
        adjusted, close_status = self.close_range.update(
            observation,
            frame_size,
        )
        angular_error = self.projection.error(adjusted, frame_size)
        pan_limits = self.motion_config.pan
        tilt_limits = self.motion_config.tilt
        pan_integral_allowed = observation.observed and not (
            commanded_pose.pan_degrees >= pan_limits.max_angle_deg
            and angular_error.pan_degrees > 0.0
            or commanded_pose.pan_degrees <= pan_limits.min_angle_deg
            and angular_error.pan_degrees < 0.0
        )
        tilt_integral_allowed = observation.observed and not (
            commanded_pose.tilt_degrees >= tilt_limits.max_angle_deg
            and angular_error.tilt_degrees > 0.0
            or commanded_pose.tilt_degrees <= tilt_limits.min_angle_deg
            and angular_error.tilt_degrees < 0.0
        )
        request = MotionRequest(
            self._pan_pid.update(
                angular_error.pan_degrees,
                dt_s,
                pan_integral_allowed,
            ),
            self._tilt_pid.update(
                angular_error.tilt_degrees,
                dt_s,
                tilt_integral_allowed,
            ),
        )
        telemetry = AutoControlTelemetry(
            target_observed=observation.observed,
            angular_error=angular_error,
            control_aim_point=adjusted.aim_point,
            close_range_active=close_status.active,
            box_height_ratio=close_status.height_ratio,
        )
        return request, telemetry
