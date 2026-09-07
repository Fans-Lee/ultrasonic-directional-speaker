"""Data models shared by the visual tracking control modules."""

from dataclasses import dataclass
from typing import Optional, Tuple


Point = Tuple[float, float]


@dataclass(frozen=True)
class AimObservation:
    """One selected track expressed as a timestamped image observation."""

    timestamp_s: float
    track_id: int
    aim_point: Point
    confidence: float
    observed: bool


@dataclass(frozen=True)
class GimbalSetpoint:
    """Absolute logical gimbal angles produced by the visual controller."""

    timestamp_s: float
    pan_degrees: float
    tilt_degrees: float

    def rounded_degrees(self) -> Tuple[int, int]:
        return round(self.pan_degrees), round(self.tilt_degrees)


@dataclass(frozen=True)
class SerialLinkStatus:
    enabled: bool = False
    connected: bool = False
    last_response: str = ""
    last_error: str = ""


@dataclass(frozen=True)
class ServoOutput:
    setpoint: Optional[GimbalSetpoint]
    target_id: Optional[int]
    target_observed: bool
    pan_error_deg: float
    tilt_error_deg: float


@dataclass(frozen=True)
class TrackingControlStatus:
    target_id: Optional[int] = None
    target_observed: bool = False
    pan_error_deg: float = 0.0
    tilt_error_deg: float = 0.0
    pan_command_deg: float = 0.0
    tilt_command_deg: float = 0.0
    serial: SerialLinkStatus = SerialLinkStatus()

