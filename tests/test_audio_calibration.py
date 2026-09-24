from __future__ import annotations

import json

import numpy as np

from utils.audio_calibration.calibrate import (
    HammersteinModel,
    ModelSpec,
    decode_pcm_u8,
    encode_pcm_u8,
    fit_model,
    load_take,
    polynomial_features,
    read_wav_mono,
    write_pcm16_wav,
    write_pcm_u8_wav,
)
from utils.audio_calibration.calibrate import PairedTake


def test_pcm_wav_round_trip_uses_actual_8bit_codes(tmp_path):
    pcm = np.array([0, 1, 127, 128, 254, 255], dtype=np.uint8)
    path = tmp_path / "input.wav"
    write_pcm_u8_wav(path, pcm)
    values, rate = read_wav_mono(path)
    assert rate == 8000
    assert np.array_equal(encode_pcm_u8(values), pcm)


def test_polynomial_features_are_finite_with_oversampling():
    x = np.sin(2 * np.pi * 900 * np.arange(800) / 8000) * 0.4
    features = polynomial_features(x, (1, 2, 3), oversample=6)
    assert all(feature.shape == x.shape and np.all(np.isfinite(feature)) for feature in features)


def test_fit_recovers_a_delayed_linear_system_from_paired_wavs(tmp_path):
    rng = np.random.default_rng(2)
    x = np.clip(rng.normal(0, 0.18, 4096), -0.6, 0.6)
    pcm = encode_pcm_u8(x)
    actual_x = decode_pcm_u8(pcm)
    reference = HammersteinModel(ModelSpec((1,), 3, 1, (1.0,), 0.015), (np.array([0.55, -0.14, 0.05]),))
    y = reference.predict(actual_x)
    input_path = tmp_path / "input.wav"
    recording_path = tmp_path / "recorded.wav"
    write_pcm_u8_wav(input_path, pcm)
    write_pcm16_wav(recording_path, np.concatenate([np.zeros(23), y]))
    take = PairedTake("known", input_path, recording_path, "train", max_lag_ms=20)
    x_aligned, y_aligned, delay = load_take(take)
    assert delay == 23
    fitted = fit_model([take], (1,), taps=3, ridge=1e-8, oversample=1, batch_size=512)
    prediction = fitted.predict(x_aligned)
    assert np.mean((prediction[8:] - y_aligned[8:]) ** 2) < 2e-7


def test_model_gradient_matches_a_finite_difference():
    model = HammersteinModel(
        ModelSpec((1, 2, 3), 3, 1, (1.0, 1.0, 1.0), 0.0),
        (np.array([0.6, -0.1, 0.04]), np.array([0.15, 0.02, -0.03]), np.array([0.04, -0.01, 0.01])),
    )
    rng = np.random.default_rng(4)
    x = rng.normal(0, 0.15, 80)
    direction = rng.normal(0, 1, x.size)
    residual_weight = rng.normal(0, 1, x.size)
    analytic = float(np.dot(model.gradient(x, residual_weight), direction))
    epsilon = 1e-6
    numerical = float(np.dot(residual_weight, model.predict(x + epsilon * direction) - model.predict(x - epsilon * direction)) / (2 * epsilon))
    assert np.isclose(analytic, numerical, rtol=1e-5, atol=1e-6)
