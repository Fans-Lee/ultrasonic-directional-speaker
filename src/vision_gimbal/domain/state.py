"""Session and UI-facing state snapshots."""

from dataclasses import dataclass, field
from enum import Enum
from typing import FrozenSet, Optional

from .control import AutoControlTelemetry, ControlSource, SerialLinkStatus
from .geometry import GimbalPose, Point
from .intents import ManualDirection


class ControlMode(str, Enum):
    STOPPED_MANUAL = "stopped_manual"
    AUTO_TRACKING = "auto_tracking"


class TargetStatus(str, Enum):
    NONE = "none"
    READY = "ready"
    OBSERVED = "observed"
    PREDICTED = "predicted"
    LOST = "lost"


@dataclass
class SessionState:
    control_mode: ControlMode = ControlMode.STOPPED_MANUAL
    selected_target_id: Optional[int] = None
    active_target_id: Optional[int] = None
    target_status: TargetStatus = TargetStatus.NONE
    pressed_directions: FrozenSet[ManualDirection] = field(
        default_factory=frozenset
    )
    last_commanded_pose: GimbalPose = GimbalPose()
    shutdown_requested: bool = False
    last_message: str = "请选择画面中的人物"


@dataclass(frozen=True)
class UiSnapshot:
    control_mode: ControlMode
    selected_target_id: Optional[int]
    active_target_id: Optional[int]
    target_status: TargetStatus
    last_commanded_pose: GimbalPose
    control_source: ControlSource
    telemetry: AutoControlTelemetry
    serial: SerialLinkStatus
    aim_center: Optional[Point] = None
    selected_target_available: bool = False
    message: str = ""

    @property
    def manual_enabled(self) -> bool:
        return self.control_mode is ControlMode.STOPPED_MANUAL

    @property
    def tracking(self) -> bool:
        return self.control_mode is ControlMode.AUTO_TRACKING
