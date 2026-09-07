"""Pure session state transitions driven by presentation intents."""

from dataclasses import dataclass

from ..config.schema import TargetLockConfig
from ..domain.geometry import GimbalPose
from ..domain.intents import (
    ClearManualKeys,
    ManualKeyChanged,
    SelectTarget,
    ShutdownRequested,
    StartTracking,
    StopTracking,
    UserIntent,
)
from ..domain.state import ControlMode, SessionState, TargetStatus
from ..domain.tracking import VisionSnapshot


@dataclass(frozen=True)
class SessionActions:
    reset_auto: bool = False
    reset_motion: bool = False
    force_hold: bool = False
    active_target_changed: bool = False

    def merge(self, other: "SessionActions") -> "SessionActions":
        return SessionActions(
            reset_auto=self.reset_auto or other.reset_auto,
            reset_motion=self.reset_motion or other.reset_motion,
            force_hold=self.force_hold or other.force_hold,
            active_target_changed=(
                self.active_target_changed or other.active_target_changed
            ),
        )


class TrackingSession:
    def __init__(self, config: TargetLockConfig) -> None:
        self.config = config
        self.state = SessionState()

    def handle(
        self,
        intent: UserIntent,
        snapshot: VisionSnapshot | None,
    ) -> SessionActions:
        if isinstance(intent, SelectTarget):
            return self._select_target(intent, snapshot)
        if isinstance(intent, StartTracking):
            return self._start_tracking(snapshot)
        if isinstance(intent, StopTracking):
            return self._stop_tracking("追踪已停止，可使用 WASD 手动控制")
        if isinstance(intent, ManualKeyChanged):
            return self._manual_key(intent)
        if isinstance(intent, ClearManualKeys):
            self.state.pressed_directions = frozenset()
            return SessionActions(reset_motion=True)
        if isinstance(intent, ShutdownRequested):
            self.state.shutdown_requested = True
            return self._stop_tracking("正在关闭")
        raise TypeError(f"unsupported intent: {intent!r}")

    def _select_target(
        self,
        intent: SelectTarget,
        snapshot: VisionSnapshot | None,
    ) -> SessionActions:
        if snapshot is None:
            self.state.last_message = "尚未收到摄像头画面"
            return SessionActions()
        frame_age = snapshot.frame_id - intent.frame_id
        if frame_age < 0 or frame_age > self.config.max_selection_age_frames:
            self.state.last_message = "点击对应的画面已过期，请重新选择"
            return SessionActions()
        person = snapshot.find(intent.track_id)
        if person is None or not person.observed:
            self.state.last_message = "该目标已离开画面，请重新选择"
            return SessionActions()

        self.state.selected_target_id = person.track_id
        if self.state.active_target_id == person.track_id:
            self.state.last_message = f"正在追踪 ID {person.track_id}"
        elif self.state.control_mode is ControlMode.AUTO_TRACKING:
            self.state.last_message = f"已选择 ID {person.track_id}，点击“切换目标”生效"
        else:
            self.state.target_status = TargetStatus.READY
            self.state.last_message = f"已选择 ID {person.track_id}，点击“开始追踪”"
        return SessionActions()

    def _start_tracking(
        self,
        snapshot: VisionSnapshot | None,
    ) -> SessionActions:
        selected = self.state.selected_target_id
        if selected is None:
            self.state.last_message = "请先点击画面中的人物"
            return SessionActions()
        person = snapshot.find(selected) if snapshot is not None else None
        if (
            person is None
            or not person.observed
            or person.confidence < self.config.min_confidence
        ):
            self.state.last_message = "选中目标当前不可见，请重新选择"
            return SessionActions()

        changed = self.state.active_target_id != selected
        self.state.control_mode = ControlMode.AUTO_TRACKING
        self.state.active_target_id = selected
        self.state.target_status = TargetStatus.OBSERVED
        self.state.pressed_directions = frozenset()
        self.state.last_message = f"正在追踪 ID {selected}"
        return SessionActions(
            reset_auto=True,
            reset_motion=True,
            active_target_changed=changed,
        )

    def _stop_tracking(self, message: str) -> SessionActions:
        was_active = self.state.control_mode is ControlMode.AUTO_TRACKING
        self.state.control_mode = ControlMode.STOPPED_MANUAL
        self.state.active_target_id = None
        self.state.pressed_directions = frozenset()
        self.state.target_status = (
            TargetStatus.READY
            if self.state.selected_target_id is not None
            else TargetStatus.NONE
        )
        self.state.last_message = message
        return SessionActions(
            reset_auto=True,
            reset_motion=True,
            force_hold=was_active,
            active_target_changed=was_active,
        )

    def _manual_key(self, intent: ManualKeyChanged) -> SessionActions:
        if self.state.control_mode is not ControlMode.STOPPED_MANUAL:
            self.state.last_message = "自动追踪中；请先停止追踪再使用 WASD"
            return SessionActions()
        directions = set(self.state.pressed_directions)
        if intent.pressed:
            directions.add(intent.direction)
        else:
            directions.discard(intent.direction)
        self.state.pressed_directions = frozenset(directions)
        self.state.last_message = "WASD 手动控制中" if directions else "手动控制已停止"
        return SessionActions()

    def set_target_status(self, status: TargetStatus) -> None:
        self.state.target_status = status
        if (
            status is TargetStatus.OBSERVED
            and self.state.selected_target_id == self.state.active_target_id
        ):
            self.state.last_message = f"正在追踪 ID {self.state.active_target_id}"
        elif status is TargetStatus.PREDICTED:
            self.state.last_message = "目标短暂漏检，正在预测"
        elif status is TargetStatus.LOST:
            self.state.last_message = "目标丢失，云台保持当前位置"

    def release_lost_target(self) -> SessionActions:
        self.state.control_mode = ControlMode.STOPPED_MANUAL
        self.state.active_target_id = None
        self.state.target_status = TargetStatus.LOST
        self.state.pressed_directions = frozenset()
        self.state.last_message = "目标丢失超时，已停止追踪"
        return SessionActions(
            reset_auto=True,
            reset_motion=True,
            force_hold=True,
            active_target_changed=True,
        )

    def stop_for_fault(self, message: str) -> SessionActions:
        return self._stop_tracking(message)

    def update_pose(self, pose: GimbalPose) -> None:
        self.state.last_commanded_pose = pose
