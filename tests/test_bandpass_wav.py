from __future__ import annotations

import numpy as np
import pytest

from utils.audio_calibration.bandpass_wav import (
    filter_samples,
    frequency_mask,
    main,
    read_pcm_wav,
)
from utils.audio_calibration.calibrate import write_pcm16_wav


def test_stereo_filter_keeps_in_band_tone_and_removes_ultrasonic_recording_artifact():
    sample_rate = 48000
    time = np.arange(sample_rate, dtype=np.float64) / sample_rate
    low_tone = 0.2 * np.sin(2 * np.pi * 1000 * time)
    high_tone = 0.2 * np.sin(2 * np.pi * 10000 * time)
    source = np.column_stack((low_tone + high_tone, low_tone - high_tone))
    result = filter_samples(source, sample_rate, edge_fade_ms=0)
    assert result.shape == source.shape
    assert np.max(np.abs(result[:, 0] - low_tone)) < 1e-10
    assert np.max(np.abs(result[:, 1] - low_tone)) < 1e-10
    mask = frequency_mask(sample_rate, sample_rate, 250, 3000, 50)
    frequencies = np.fft.rfftfreq(sample_rate, 1 / sample_rate)
    assert np.all(mask[(frequencies < 250) | (frequencies > 3000)] == 0)


def test_cli_writes_same_length_24bit_wav_and_report(tmp_path):
    sample_rate = 48000
    time = np.arange(sample_rate // 4, dtype=np.float64) / sample_rate
    source_path = tmp_path / "recorded.wav"
    output_path = tmp_path / "bandpass.wav"
    write_pcm16_wav(source_path, 0.3 * np.sin(2 * np.pi * 1000 * time), sample_rate)
    assert main([str(source_path), str(output_path)]) == 0
    filtered, rate, bits = read_pcm_wav(output_path)
    assert filtered.shape == (time.size, 1)
    assert (rate, bits) == (sample_rate, 24)
    assert output_path.with_suffix(".report.json").exists()


def test_stereo_24bit_wav_round_trip(tmp_path):
    from utils.audio_calibration.bandpass_wav import write_pcm24_wav

    samples = np.array([[0.0, 0.125], [-0.25, 0.375], [0.5, -0.625]])
    path = tmp_path / "stereo.wav"
    write_pcm24_wav(path, samples, 48000)
    decoded, rate, bits = read_pcm_wav(path)
    assert (rate, bits) == (48000, 24)
    assert decoded.shape == samples.shape
    assert np.max(np.abs(decoded - samples)) < 1 / 8388608


def test_cli_selects_right_channel(tmp_path):
    from utils.audio_calibration.bandpass_wav import write_pcm24_wav

    rate = 48000
    time = np.arange(rate // 10) / rate
    source = np.column_stack((0.01 * np.sin(2 * np.pi * 1000 * time),
                              0.3 * np.sin(2 * np.pi * 1000 * time)))
    source_path = tmp_path / "source.wav"
    output_path = tmp_path / "right.wav"
    write_pcm24_wav(source_path, source, rate)
    assert main([str(source_path), str(output_path), "--channel", "right"]) == 0
    filtered, _, _ = read_pcm_wav(output_path)
    assert filtered.shape == (len(time), 1)
    assert np.sqrt(np.mean(filtered ** 2)) > 0.1


def test_rejects_frequency_above_input_nyquist():
    with pytest.raises(ValueError, match="Nyquist"):
        frequency_mask(8000, 8000, 250, 5000, 50)
