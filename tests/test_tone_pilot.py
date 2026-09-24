from __future__ import annotations

import wave

import numpy as np

from utils.audio_calibration.tone_pilot import inspect_tone


def test_pilot_uses_measured_frequency_and_active_channel(tmp_path):
    rate = 48000
    time = np.arange(rate * 3) / rate
    rng = np.random.default_rng(3)
    left = rng.normal(0, 0.0002, time.size)
    right = 0.35 * np.sin(2 * np.pi * 500 * time) + 0.07 * np.sin(2 * np.pi * 1000 * time)
    channels = np.column_stack([left, right])
    path = tmp_path / "600Hz.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(np.rint(channels * 32767).astype("<i2").tobytes())
    result = inspect_tone(path)
    assert result["channel_index_zero_based"] == 1
    assert result["detected_hz"] == 500
    assert result["label_error_hz"] == -100
    assert abs(result["harmonics"]["2"]["median_dbc"] - 20 * np.log10(0.2)) < 0.3
