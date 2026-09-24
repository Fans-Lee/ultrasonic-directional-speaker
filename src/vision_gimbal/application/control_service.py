"""Single owner of session mutation and outbound gimbal commands."""

import queue

from ..control.auto_tracking import AutoTrackingController
from ..control.command_arbiter import CommandArbiter
from ..control.manual_jog import ManualJogController
from ..control.motion_limiter import GimbalMotionLimiter
from ..control.target_lock import TargetLock
from ..domain.control import AutoControlTelemetry, ControlSource
from ..domain.intents import Intent
from ..domain.state import ControlMode, UiSnapshot
from ..domain.tracking import VisionSnapshot
from ..ports.clock import Clock
from ..ports.gimbal import GimbalSink
from .latest_snapshot import LatestSnapshotStore
from .tracking_session import SessionActions, TrackingSession


class ControlService:
    """The only application object allowed to publish to ``GimbalSink``."""

    def __init__(
        self,
        session: TrackingSession,
        target_lock: TargetLock,
        automatic: AutoTrackingController,
        manual: ManualJogController,
        arbiter: CommandArbiter,
        motion: GimbalMotionLimiter,
        gimbal: GimbalSink,
        clock: Clock,
        snapshots: LatestSnapshotStore[VisionSnapshot],
    ) -> None:
        self.session = session
        self.target_lock = target_lock
        self.automatic = automatic
        self.manual = manual
        self.arbiter = arbiter
        self.motion = motion
        self.gimbal = gimbal
        self.clock = clock
        self.snapshots = snapshots
        self._intents: queue.Queue[Intent] = queue.Queue()
        self._telemetry = AutoControlTelemetry()
        self._control_source = ControlSource.HOLD
        self._started = False
        self._serial_was_connected = False

    def start(self) -> None:
        if not self._started:
            self.gimbal.start()
            self._started = True

    def submit(self, intent: Intent) -> None:
        self._intents.put(intent)

    def tick(self, timestamp_s: float | None = None) -> UiSnapshot:
        now = self.clock.now() if timestamp_s is None else timestamp_s
        snapshot = self.snapshots.get()
        actions = self._drain_intents(snapshot)
        serial_status = self.gimbal.status()
        if (
            self._serial_was_connected
            and not serial_status.connected
            and self.session.state.control_mode is ControlMode.AUTO_TRACKING
        ):
            actions = actions.merge(
                self.session.stop_for_fault("串口连接中断，已停止自动追踪")
            )
        self._serial_was_connected = serial_status.connected
        if actions.reset_auto:
            self.automatic.reset()
        if actions.active_target_changed:
            active_id = self.session.state.active_target_id
            if active_id is None:
                self.target_lock.clear()
            else:
                self.target_lock.lock(active_id)
        if actions.reset_motion:
            self.motion.seed(self.motion.pose)

        auto_request = None
        state = self.session.state
        if (
            state.control_mode is ControlMode.AUTO_TRACKING
            and state.active_target_id is not None
        ):
            resolution = self.target_lock.resolve(snapshot, now)
            if resolution.released:
                lost_actions = self.session.release_lost_target()
                self.automatic.reset()
                self.target_lock.clear()
                self.motion.seed(self.motion.pose)
                actions = actions.merge(lost_actions)
                self._telemetry = AutoControlTelemetry()
            else:
                self.session.set_target_status(resolution.status)
                if resolution.observation is not None and snapshot is not None:
                    auto_request, self._telemetry = self.automatic.update(
                        resolution.observation,
                        snapshot.frame_size,
                        now,
                        self.motion.pose,
                    )
                else:
                    self._telemetry = self.automatic.hold(now)
        else:
            self._telemetry = self.automatic.hold(now)

        manual_request = self.manual.request(state.pressed_directions)
        decision = self.arbiter.choose(
            state.control_mode,
            auto_request,
            manual_request,
        )
        self._control_source = decision.source
        should_publish = actions.force_hold
        if decision.source is ControlSource.HOLD:
            setpoint = self.motion.hold(now)
        else:
            setpoint = self.motion.update(decision.request, now)
            should_publish = True
        if should_publish:
            self.gimbal.publish(setpoint)
        self.session.update_pose(setpoint.pose)
        return self.ui_snapshot()

    def ui_snapshot(self) -> UiSnapshot:
        state = self.session.state
        vision = self.snapshots.get()
        aim_center = (
            self.automatic.projection.aim_center(vision.frame_size)
            if vision is not None
            else None
        )
        selected_person = (
            vision.find_person(state.selected_target_id)
            if vision is not None and state.selected_target_id is not None
            else None
        )
        return UiSnapshot(
            control_mode=state.control_mode,
            selected_target_id=state.selected_target_id,
            active_target_id=state.active_target_id,
            target_status=state.target_status,
            last_commanded_pose=state.last_commanded_pose,
            control_source=self._control_source,
            telemetry=self._telemetry,
            serial=self.gimbal.status(),
            aim_center=aim_center,
            selected_target_available=(
                selected_person is not None and selected_person.observed
            ),
            message=state.last_message,
        )

    def close(self) -> None:
        if not self._started:
            return
        now = self.clock.now()
        self.motion.hold(now)
        self.automatic.reset()
        self.target_lock.clear()
        self.gimbal.close()
        self._started = False
        self._serial_was_connected = False

    def _drain_intents(
        self,
        snapshot: VisionSnapshot | None,
    ) -> SessionActions:
        actions = SessionActions()
        while True:
            try:
                intent = self._intents.get_nowait()
            except queue.Empty:
                break
            actions = actions.merge(self.session.handle(intent, snapshot))
        return actions
