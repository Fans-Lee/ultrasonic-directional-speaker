"""Headless smoke test for Qt worker startup and shutdown."""

import os
import sys
import time
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from vision_gimbal.application.runtime import ApplicationRuntime
from vision_gimbal.application.vision_service import DisplayFrame
from vision_gimbal.audio.spectrum import AudioSpectrumSnapshot
from vision_gimbal.domain.audio import (
    AudioControlStatus,
    AudioDriveMode,
    AudioModeSettings,
    AudioProcessingMode,
)
from vision_gimbal.domain.control import (
    AutoControlTelemetry,
    ControlSource,
    SerialLinkStatus,
)
from vision_gimbal.domain.geometry import GimbalPose
from vision_gimbal.domain.intents import ConfigureAudio, StartAudio, StopAudio
from vision_gimbal.domain.state import (
    ControlMode,
    TargetStatus,
    UiSnapshot,
)
from vision_gimbal.domain.tracking import VisionSnapshot
from vision_gimbal.ui.qt_workers import QtApplicationRuntime
from vision_gimbal.ui.audio_panel import AudioPanel
from vision_gimbal.ui.presenter import present
from vision_gimbal.ui.spectrum_panel import SpectrumPanel


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


class _FakeAudioService:
    def __init__(self) -> None:
        self.started = False
        self.transmitting = False
        self.settings = AudioModeSettings()
        self.errors = []
        self.spectrum_refresh_hz = 20.0

    def start(self) -> None:
        self.started = True

    def start_transmitting(self) -> None:
        self.transmitting = True

    def stop_transmitting(self) -> None:
        self.transmitting = False

    def configure(self, settings) -> None:
        self.settings = settings

    def record_error(self, error) -> None:
        self.errors.append(str(error))

    def control_status(self) -> AudioControlStatus:
        return AudioControlStatus(
            enabled=True,
            transmitting=self.transmitting,
            microphone_open=self.transmitting,
            settings=self.settings,
        )

    def spectrum_snapshot(self) -> AudioSpectrumSnapshot:
        return AudioSpectrumSnapshot(
            sequence=1,
            active=self.transmitting,
            sample_rate=8000,
            frequencies_hz=np.linspace(0.0, 4000.0, 257, dtype=np.float32),
            levels_dbfs=np.full((257, 10), -40.0, dtype=np.float32),
            history_s=1.0,
            window_ms=40.0,
            hop_ms=20.0,
            min_dbfs=-80.0,
            max_dbfs=0.0,
            latest_peak_dbfs=-12.0 if self.transmitting else None,
            dropped_blocks=0,
        )

    def close(self) -> None:
        self.transmitting = False
        self.started = False


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

    def test_application_routes_audio_controls_and_merges_status(self):
        audio = _FakeAudioService()
        application = ApplicationRuntime(
            _FakeVisionService(),
            _FakeControlService(),
            audio=audio,
        )
        application.start()
        application.submit(StartAudio())
        started = application.tick()
        self.assertTrue(started.audio.transmitting)

        settings = AudioModeSettings(drive=AudioDriveMode.BOOST)
        application.submit(ConfigureAudio(settings))
        configured = application.tick()
        self.assertEqual(configured.audio.settings, settings)

        application.submit(StopAudio())
        stopped = application.tick()
        self.assertFalse(stopped.audio.transmitting)
        application.close()

    def test_runtime_publishes_latest_spectrum_snapshot(self):
        audio = _FakeAudioService()
        application = ApplicationRuntime(
            _FakeVisionService(),
            _FakeControlService(),
            audio=audio,
        )
        runtime = QtApplicationRuntime(application, control_hz=10.0)
        snapshots = []
        runtime.spectrum_ready.connect(snapshots.append)

        runtime.start()
        event_loop = QEventLoop()
        QTimer.singleShot(120, event_loop.quit)
        event_loop.exec()
        runtime.stop()

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].sample_rate, 8000)

    def test_audio_panel_emits_start_and_mode_controls(self):
        panel = AudioPanel()
        starts = []
        stops = []
        settings_events = []
        panel.start_requested.connect(lambda: starts.append(True))
        panel.stop_requested.connect(lambda: stops.append(True))
        panel.settings_requested.connect(settings_events.append)
        snapshot = replace(
            _FakeControlService().tick(),
            serial=SerialLinkStatus(enabled=True, connected=True),
            audio=AudioControlStatus(enabled=True),
        )
        panel.apply(present(snapshot))

        self.assertTrue(panel.start_button.isEnabled())
        panel.start_button.click()
        panel.processing_combo.setCurrentIndex(1)

        self.assertEqual(starts, [True])
        self.assertIs(
            settings_events[-1].processing, AudioProcessingMode.LOUD
        )

        transmitting = replace(
            snapshot,
            audio=AudioControlStatus(
                enabled=True,
                transmitting=True,
                microphone_open=True,
                settings=AudioModeSettings(
                    processing="loud",
                    drive="boost",
                    modulation="sram",
                ),
            ),
        )
        panel.apply(present(transmitting))
        self.assertTrue(panel.stop_button.isEnabled())
        panel.stop_button.click()
        self.assertEqual(stops, [True])

    def test_spectrum_panel_displays_snapshot_status(self):
        panel = SpectrumPanel()
        audio = _FakeAudioService()
        audio.transmitting = True

        panel.apply(audio.spectrum_snapshot())

        self.assertIn("峰值 -12.0 dBFS", panel.status.text())
        self.assertFalse(panel.canvas._image.isNull())


if __name__ == "__main__":
    unittest.main()
