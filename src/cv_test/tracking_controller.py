"""Coordinate target selection, visual PID, and the gimbal transport."""

from dataclasses import dataclass, field, replace
from typing import Sequence, Tuple

if __package__:
    from .camera_geometry import CameraGeometry, CameraGeometryConfig
    from .close_range_aim import CloseRangeAimConfig, CloseRangeAimPolicy
    from .control_models import TrackingControlStatus
    from .gimbal_serial import GimbalCommandSink
    from .target_selector import TargetSelector, TargetSelectorConfig
    from .tracking_models import TrackedPerson
    from .visual_servo import VisualServoConfig, VisualServoController
else:
    from camera_geometry import CameraGeometry, CameraGeometryConfig
    from close_range_aim import CloseRangeAimConfig, CloseRangeAimPolicy
    from control_models import TrackingControlStatus
    from gimbal_serial import GimbalCommandSink
    from target_selector import TargetSelector, TargetSelectorConfig
    from tracking_models import TrackedPerson
    from visual_servo import VisualServoConfig, VisualServoController


@dataclass(frozen=True)
class TrackingControllerConfig:
    update_hz: float = 10.0
    target_selector: TargetSelectorConfig = field(
        default_factory=TargetSelectorConfig
    )
    camera: CameraGeometryConfig = field(
        default_factory=CameraGeometryConfig
    )
    close_range: CloseRangeAimConfig = field(
        default_factory=CloseRangeAimConfig
    )
    servo: VisualServoConfig = field(default_factory=VisualServoConfig)

    def __post_init__(self) -> None:
        if self.update_hz <= 0.0:
            raise ValueError("update_hz must be positive")


class TrackingController:
    """A non-blocking, frame-driven visual control facade."""

    def __init__(
        self,
        config: TrackingControllerConfig,
        gimbal: GimbalCommandSink,
    ) -> None:
        self.config = config
        self.gimbal = gimbal
        self.geometry = CameraGeometry(config.camera)
        self.selector = TargetSelector(config.target_selector)
        self.close_range = CloseRangeAimPolicy(config.close_range)
        self.servo = VisualServoController(config.servo, self.geometry)
        self._minimum_update_period = 1.0 / config.update_hz
        self._last_update_at = None
        self._status = TrackingControlStatus(serial=gimbal.status())

    def start(self) -> None:
        self.gimbal.start()

    def close(self) -> None:
        self.gimbal.close()

    def reset_target(self) -> None:
        self.selector.clear()
        self.close_range.reset()
        self.servo.reset_pid()
        self._last_update_at = None

    def aim_center(self, frame_size: Tuple[int, int]) -> Tuple[float, float]:
        return self.geometry.aim_center(frame_size)

    def status(self) -> TrackingControlStatus:
        return replace(self._status, serial=self.gimbal.status())

    def update(
        self,
        people: Sequence[TrackedPerson],
        frame_size: Tuple[int, int],
        timestamp_s: float,
    ) -> TrackingControlStatus:
        if (
            self._last_update_at is not None
            and timestamp_s - self._last_update_at
            < self._minimum_update_period
        ):
            return self.status()
        self._last_update_at = timestamp_s

        observation = self.selector.update(
            people,
            timestamp_s,
            self.geometry.aim_center(frame_size),
        )
        if observation is None:
            close_range_status = self.close_range.status()
            control_aim_point = None
            output = self.servo.hold(timestamp_s)
        else:
            observation, close_range_status = self.close_range.update(
                observation,
                frame_size,
            )
            control_aim_point = observation.aim_point
            output = self.servo.update(
                observation,
                frame_size,
                timestamp_s,
            )
            if output.setpoint is not None:
                self.gimbal.publish(output.setpoint)

        pan_command, tilt_command = self.servo.angles
        self._status = TrackingControlStatus(
            target_id=self.selector.selected_track_id,
            target_observed=output.target_observed,
            pan_error_deg=output.pan_error_deg,
            tilt_error_deg=output.tilt_error_deg,
            pan_command_deg=pan_command,
            tilt_command_deg=tilt_command,
            close_range_active=close_range_status.active,
            box_height_ratio=close_range_status.height_ratio,
            control_aim_point=control_aim_point,
            serial=self.gimbal.status(),
        )
        return self._status

