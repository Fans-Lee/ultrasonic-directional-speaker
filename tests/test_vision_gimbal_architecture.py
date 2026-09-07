"""Regression tests for the layered UI/control architecture."""

import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from vision_gimbal.application.control_service import ControlService
from vision_gimbal.application.latest_snapshot import (
    LatestSnapshotStore,
)
from vision_gimbal.application.tracking_session import (
    TrackingSession,
)
from vision_gimbal.config.schema import AppConfig
from vision_gimbal.control.auto_tracking import (
    AutoTrackingController,
)
from vision_gimbal.control.camera_projection import CameraProjection
from vision_gimbal.control.close_range_aim import (
    CloseRangeAimPolicy,
)
from vision_gimbal.control.command_arbiter import CommandArbiter
from vision_gimbal.control.manual_jog import ManualJogController
from vision_gimbal.control.motion_limiter import (
    GimbalMotionLimiter,
)
from vision_gimbal.control.target_lock import TargetLock
from vision_gimbal.domain.control import SerialLinkStatus
from vision_gimbal.domain.intents import (
    ManualDirection,
    ManualKeyChanged,
    SelectTarget,
    StartTracking,
    StopTracking,
)
from vision_gimbal.domain.state import ControlMode, TargetStatus
from vision_gimbal.domain.tracking import (
    TrackedPerson,
    VisionSnapshot,
)
from vision_gimbal.ui.video_transform import (
    select_track_at,
    widget_to_source,
)


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self):
        return self.value


class _RecordingGimbal:
    def __init__(self) -> None:
        self.commands = []
        self.started = False

    def start(self):
        self.started = True

    def publish(self, setpoint):
        self.commands.append(setpoint)

    def status(self):
        return SerialLinkStatus(enabled=False, connected=False)

    def close(self):
        self.started = False


def _person(track_id, center, observed=True, confidence=0.9):
    x, y = center
    return TrackedPerson(
        track_id=track_id,
        bbox_xyxy=(x - 20.0, y - 40.0, x + 20.0, y + 40.0),
        detection_center=center,
        aim_point=center,
        confidence=confidence,
        observed=observed,
    )


def _snapshot(frame_id, timestamp_s, people):
    return VisionSnapshot(
        frame_id=frame_id,
        captured_at=timestamp_s,
        frame_size=(100, 100),
        tracks=tuple(people),
    )


def _control_service():
    config = AppConfig()
    clock = _Clock()
    store = LatestSnapshotStore()
    gimbal = _RecordingGimbal()
    automatic = AutoTrackingController(
        config.automatic,
        CameraProjection(config.projection),
        CloseRangeAimPolicy(config.close_range),
        config.motion,
    )
    service = ControlService(
        TrackingSession(config.target),
        TargetLock(config.target),
        automatic,
        ManualJogController(config.manual),
        CommandArbiter(),
        GimbalMotionLimiter(config.motion),
        gimbal,
        clock,
        store,
    )
    service.start()
    return service, store, clock, gimbal


class TrackingSessionTests(unittest.TestCase):
    def test_start_requires_an_explicit_visible_selection(self):
        config = AppConfig()
        session = TrackingSession(config.target)
        snapshot = _snapshot(1, 0.0, [_person(7, (50.0, 50.0))])

        session.handle(StartTracking(), snapshot)
        self.assertEqual(session.state.control_mode, ControlMode.STOPPED_MANUAL)

        session.handle(SelectTarget(7, 1), snapshot)
        session.handle(StartTracking(), snapshot)
        self.assertEqual(session.state.control_mode, ControlMode.AUTO_TRACKING)
        self.assertEqual(session.state.active_target_id, 7)

    def test_click_during_tracking_is_pending_until_start_is_pressed(self):
        config = AppConfig()
        session = TrackingSession(config.target)
        snapshot = _snapshot(
            2,
            0.0,
            [_person(1, (25.0, 50.0)), _person(2, (75.0, 50.0))],
        )
        session.handle(SelectTarget(1, 2), snapshot)
        session.handle(StartTracking(), snapshot)

        session.handle(SelectTarget(2, 2), snapshot)
        self.assertEqual(session.state.selected_target_id, 2)
        self.assertEqual(session.state.active_target_id, 1)

        session.handle(StartTracking(), snapshot)
        self.assertEqual(session.state.active_target_id, 2)


class ControlServiceTests(unittest.TestCase):
    def test_lost_target_stops_instead_of_switching_people(self):
        service, store, _, _ = _control_service()
        store.set(
            _snapshot(
                1,
                0.0,
                [_person(1, (25.0, 50.0)), _person(2, (75.0, 50.0))],
            )
        )
        service.submit(SelectTarget(1, 1))
        service.submit(StartTracking())
        service.tick(0.0)

        store.set(_snapshot(2, 0.1, [_person(2, (75.0, 50.0))]))
        interim = service.tick(0.1)
        self.assertEqual(interim.active_target_id, 1)
        self.assertEqual(interim.target_status, TargetStatus.LOST)

        stopped = service.tick(1.0)
        self.assertEqual(stopped.control_mode, ControlMode.STOPPED_MANUAL)
        self.assertIsNone(stopped.active_target_id)
        self.assertEqual(stopped.selected_target_id, 1)
        service.close()

    def test_wasd_moves_only_while_tracking_is_stopped(self):
        service, store, _, gimbal = _control_service()
        store.set(_snapshot(1, 0.0, [_person(4, (50.0, 50.0))]))
        service.submit(ManualKeyChanged(ManualDirection.RIGHT, True))
        manual = service.tick(0.1)
        self.assertLess(manual.last_commanded_pose.pan_degrees, 0.0)
        manual_pose = manual.last_commanded_pose

        service.submit(SelectTarget(4, 1))
        service.submit(StartTracking())
        service.submit(ManualKeyChanged(ManualDirection.LEFT, True))
        automatic = service.tick(0.2)
        self.assertEqual(automatic.control_mode, ControlMode.AUTO_TRACKING)
        self.assertEqual(automatic.last_commanded_pose, manual_pose)

        service.submit(StopTracking())
        stopped = service.tick(0.3)
        self.assertEqual(stopped.control_mode, ControlMode.STOPPED_MANUAL)
        self.assertTrue(gimbal.commands)
        service.close()


class VideoTransformTests(unittest.TestCase):
    def test_letterbox_click_maps_to_source_coordinates(self):
        point = widget_to_source((100.0, 100.0), (100, 100), (200, 100))
        self.assertEqual(point, (50.0, 100.0))
        self.assertIsNone(widget_to_source((25.0, 50.0), (100, 100), (200, 100)))

    def test_smallest_overlapping_observed_box_wins(self):
        large = TrackedPerson(
            1,
            (0.0, 0.0, 100.0, 100.0),
            (50.0, 50.0),
            (50.0, 50.0),
            0.95,
        )
        small = TrackedPerson(
            2,
            (40.0, 40.0, 60.0, 60.0),
            (50.0, 50.0),
            (50.0, 50.0),
            0.80,
        )
        selected = select_track_at(
            (50.0, 50.0),
            (100, 100),
            (100, 100),
            [large, small],
        )
        self.assertEqual(selected, 2)


if __name__ == "__main__":
    unittest.main()
