"""Small geometry value types shared by the domain."""

from dataclasses import dataclass
from typing import Tuple


Point = Tuple[float, float]
BoundingBox = Tuple[float, float, float, float]
FrameSize = Tuple[int, int]


@dataclass(frozen=True)
class AngularError:
    pan_degrees: float = 0.0
    tilt_degrees: float = 0.0


@dataclass(frozen=True)
class GimbalPose:
    """The last commanded pose; this is not encoder feedback."""

    pan_degrees: float = 0.0
    tilt_degrees: float = 0.0
