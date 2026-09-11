"""Tests for background real-time spectrum analysis."""

import math
import sys
import time
import unittest
from pathlib import Path

import numpy as np

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from vision_gimbal.audio.spectrum import RealtimeSpectrumAnalyzer
from vision_gimbal.config.schema import AudioSpectrumConfig


class RealtimeSpectrumAnalyzerTests(unittest.TestCase):
    def test_finds_tone_and_resets_when_stream_stops(self):
        sample_rate = 8000
        analyzer = RealtimeSpectrumAnalyzer(
            AudioSpectrumConfig(
                window_ms=40.0,
                hop_ms=20.0,
                history_s=1.0,
                queue_blocks=16,
            ),
            sample_rate,
        )
        analyzer.start()
        analyzer.activate()
        time_axis = np.arange(1600, dtype=np.float32) / sample_rate
        tone = 0.5 * np.sin(2.0 * math.pi * 1000.0 * time_axis)
        for block in np.split(tone, 10):
            analyzer.submit(block)

        deadline = time.monotonic() + 1.0
        snapshot = analyzer.snapshot()
        while snapshot.latest_peak_dbfs is None and time.monotonic() < deadline:
            time.sleep(0.01)
            snapshot = analyzer.snapshot()

        self.assertTrue(snapshot.active)
        self.assertIsNotNone(snapshot.latest_peak_dbfs)
        valid_columns = np.flatnonzero(
            np.any(np.isfinite(snapshot.levels_dbfs), axis=0)
        )
        self.assertGreater(valid_columns.size, 0)
        latest = snapshot.levels_dbfs[:, valid_columns[-1]]
        peak_frequency = float(snapshot.frequencies_hz[int(np.nanargmax(latest))])
        self.assertAlmostEqual(peak_frequency, 1000.0, delta=20.0)
        self.assertAlmostEqual(snapshot.latest_peak_dbfs, -6.0, delta=0.5)

        analyzer.deactivate()
        stopped = analyzer.snapshot()
        self.assertFalse(stopped.active)
        self.assertFalse(np.any(np.isfinite(stopped.levels_dbfs)))
        analyzer.close()

    def test_disabled_analyzer_accepts_samples_without_starting(self):
        analyzer = RealtimeSpectrumAnalyzer(
            AudioSpectrumConfig(enabled=False),
            8000,
        )
        analyzer.start()
        analyzer.activate()
        analyzer.submit(np.ones(320, dtype=np.float32))

        snapshot = analyzer.snapshot()

        self.assertFalse(snapshot.active)
        self.assertIsNone(snapshot.latest_peak_dbfs)
        analyzer.close()


if __name__ == "__main__":
    unittest.main()
