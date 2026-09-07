"""Headless smoke test for Qt worker startup and shutdown."""

import os
import sys
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from vision_gimbal.application.runtime import ApplicationRuntime
from vision_gimbal.application.vision_service import DisplayFrame
from vision_gimbal.domain.control import (
    AutoControlTelemetry,
    ControlSource,
    SerialLinkStatus,
)
from vision_gimbal.domain.geometry import GimbalPose
from vision_gimbal.domain.state import (
    ControlMode,
    TargetStatus,
    UiSnapshot,
)
from vision_gimbal.domain.tracking import VisionSnapshot
from vision_gimbal.ui.qt_workers import QtApplicationRuntime


class _FakeVisionService:
    def __init__(self) -> None:
        self.frame_id = 0

    def start(self) -> None:
        pass

    def step(self) -> DisplayFrame:
        self.frame_id += 1
        time.sleep(0.002)
        snapshot = VisionSnapshot(
            self.frame_id,
            time.monotonic(),
            (16, 9),
            (),
        )
        return DisplayFrame(object(), snapshot)

    def close(self) -> None:
        pass


class _FakeControlService:
    def start(self) -> None:
        pass

    def submit(self, intent) -> None:
        del intent

    def tick(self) -> UiSnapshot:
        return UiSnapshot(
            ControlMode.STOPPED_MANUAL,
            None,
            None,
            TargetStatus.NONE,
            GimbalPose(),
            ControlSource.HOLD,
            AutoControlTelemetry(),
            SerialLinkStatus(),
        )

    def close(self) -> None:
        pass


class QtApplicationRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt_app = QApplication.instance() or QApplication([])

    def test_workers_publish_and_stop_after_event_loop_exits(self):
        application = ApplicationRuntime(
            _FakeVisionService(),
            _FakeControlService(),
        )
        runtime = QtApplicationRuntime(application, control_hz=10.0)
        counts = {"frames": 0, "states": 0}
        runtime.frame_ready.connect(
            lambda _: counts.__setitem__("frames", counts["frames"] + 1)
        )
        runtime.state_ready.connect(
            lambda _: counts.__setitem__("states", counts["states"] + 1)
        )

        runtime.start()
        event_loop = QEventLoop()
        QTimer.singleShot(250, event_loop.quit)
        event_loop.exec()
        runtime.stop()

        self.assertGreater(counts["frames"], 0)
        self.assertGreater(counts["states"], 0)


if __name__ == "__main__":
    unittest.main()
