"""Convert image displacement into angular error."""

import math

from ..config.schema import CameraProjectionConfig
from ..domain.geometry import AngularError, FrameSize, Point
from ..domain.tracking import TargetObservation


class CameraProjection:
    def __init__(self, config: CameraProjectionConfig) -> None:
        self.config = config

    def aim_center(self, frame_size: FrameSize) -> Point:
        width, height = frame_size
        if width <= 0 or height <= 0:
            raise ValueError("frame dimensions must be positive")
        return (
            width / 2.0 + self.config.aim_offset_x_px,
            height / 2.0 + self.config.aim_offset_y_px,
        )

    def error(
        self,
        observation: TargetObservation,
        frame_size: FrameSize,
    ) -> AngularError:
        width, height = frame_size
        center_x, center_y = self.aim_center(frame_size)
        focal_x = (width / 2.0) / math.tan(
            math.radians(self.config.horizontal_fov_deg) / 2.0
        )
        focal_y = (height / 2.0) / math.tan(
            math.radians(self.config.vertical_fov_deg) / 2.0
        )
        delta_x = observation.aim_point[0] - center_x
        delta_y = observation.aim_point[1] - center_y
        return AngularError(
            self.config.pan_sign
            * math.degrees(math.atan2(delta_x, focal_x)),
            self.config.tilt_sign
            * math.degrees(math.atan2(delta_y, focal_y)),
        )
