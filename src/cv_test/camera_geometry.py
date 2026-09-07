"""Convert image-plane displacement into camera angular error."""

import math
from dataclasses import dataclass
from typing import Tuple

if __package__:
    from .control_models import AimObservation, Point
else:
    from control_models import AimObservation, Point


@dataclass(frozen=True)
class CameraGeometryConfig:
    horizontal_fov_deg: float = 70.0
    vertical_fov_deg: float = 43.0
    aim_offset_x_px: float = 0.0
    aim_offset_y_px: float = 0.0
    pan_sign: float = -1.0
    tilt_sign: float = -1.0

    def __post_init__(self) -> None:
        for name, value in (
            ("horizontal_fov_deg", self.horizontal_fov_deg),
            ("vertical_fov_deg", self.vertical_fov_deg),
        ):
            if not 0.0 < value < 179.0:
                raise ValueError(f"{name} must be in (0, 179)")
        if self.pan_sign == 0.0 or self.tilt_sign == 0.0:
            raise ValueError("axis signs cannot be zero")


class CameraGeometry:
    def __init__(self, config: CameraGeometryConfig) -> None:
        self.config = config

    def aim_center(self, frame_size: Tuple[int, int]) -> Point:
        width, height = frame_size
        if width <= 0 or height <= 0:
            raise ValueError("frame dimensions must be positive")
        return (
            width / 2.0 + self.config.aim_offset_x_px,
            height / 2.0 + self.config.aim_offset_y_px,
        )

    def error_angles_deg(
        self,
        observation: AimObservation,
        frame_size: Tuple[int, int],
    ) -> Tuple[float, float]:
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
        return (
            self.config.pan_sign
            * math.degrees(math.atan2(delta_x, focal_x)),
            self.config.tilt_sign
            * math.degrees(math.atan2(delta_y, focal_y)),
        )
