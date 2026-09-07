"""Control values shared without depending on a transport or UI."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .geometry import AngularError, GimbalPose, Point


class ControlSource(str, Enum):
    HOLD = "hold"
    AUTO = "auto"
    MANUAL = "manual"


@dataclass(frozen=True)
class MotionRequest:
    pan_velocity_deg_s: float = 0.0
    tilt_velocity_deg_s: float = 0.0

    @property
    def moving(self) -> bool:
        return bool(
            self.pan_velocity_deg_s != 0.0
            or self.tilt_velocity_deg_s != 0.0
        )


@dataclass(frozen=True)
class GimbalSetpoint:
    timestamp_s: float
    pan_degrees: float
    tilt_degrees: float

    @property
    def pose(self) -> GimbalPose:
        return GimbalPose(self.pan_degrees, self.tilt_degrees)

    def rounded_degrees(self):
        return round(self.pan_degrees), round(self.tilt_degrees)


@dataclass(frozen=True)
class SerialLinkStatus:
    enabled: bool = False
    connected: bool = False
    last_response: str = ""
    last_error: str = ""


@dataclass(frozen=True)
class AutoControlTelemetry:
    target_observed: bool = False
    angular_error: AngularError = AngularError()
    control_aim_point: Optional[Point] = None
    close_range_active: bool = False
    box_height_ratio: float = 0.0


@dataclass(frozen=True)
class ControlDecision:
    source: ControlSource
    request: MotionRequest
    setpoint: Optional[GimbalSetpoint] = None
