"""Regression tests for repository defaults and standalone entry points."""

import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from vision_gimbal.config.loader import load_config  # noqa: E402


class ProjectSetupTests(unittest.TestCase):
    def test_optional_spatial_field_is_disabled_in_default_project_config(self):
        config = load_config(PROJECT_ROOT / "configs" / "vision_gimbal.toml")

        self.assertFalse(config.spatial_field.enabled)

    def test_default_audio_prebuffer_absorbs_short_host_stalls(self):
        config = load_config(PROJECT_ROOT / "configs" / "vision_gimbal.toml")

        self.assertEqual(config.audio.stream.prebuffer_ms, 120)
        self.assertEqual(config.audio.stream.prebuffer_samples, 960)
        self.assertLess(
            config.audio.stream.prebuffer_ms,
            config.audio.stream.device_buffer_ms,
        )

    def test_frequency_compensation_cli_can_show_help(self):
        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "utils" / "wav_frequency_squared_compensation.py"),
                "--help",
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=15.0,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--reference-frequency", result.stdout)


if __name__ == "__main__":
    unittest.main()
