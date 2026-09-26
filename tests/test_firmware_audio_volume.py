"""Compile and exercise the platform-independent firmware gain path."""

import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
MODULATION = ROOT / "src" / "full_size" / "src" / "modulation"


class FirmwareAudioVolumeTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("g++"), "g++ is needed for the firmware gain check")
    def test_gain_ramp_and_dsb_sram_output(self):
        with TemporaryDirectory() as folder:
            executable = Path(folder) / "audio_volume_test.exe"
            subprocess.run(
                [
                    "g++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
                    "-I", str(MODULATION),
                    str(ROOT / "tests" / "firmware_audio_volume_test.cpp"),
                    str(MODULATION / "audio_modulator.cpp"),
                    str(MODULATION / "dsb_am_modulator.cpp"),
                    str(MODULATION / "sram_modulator.cpp"),
                    "-o", str(executable),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run([str(executable)], check=True, capture_output=True, text=True)
