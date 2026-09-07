"""Small geometry value types shared by the domain."""

from dataclasses import dataclass

Point = tuple[float, float]
BoundingBox = tuple[float, float, float, float]
FrameSize = tuple[int, int]


@dataclass(frozen=True)
class AngularError:
    pan_degrees: float = 0.0
    tilt_degrees: float = 0.0


@dataclass(frozen=True)
class GimbalPose:
    """The last commanded pose; this is not encoder feedback."""

    pan_degrees: float = 0.0
    tilt_degrees: float = 0.0
