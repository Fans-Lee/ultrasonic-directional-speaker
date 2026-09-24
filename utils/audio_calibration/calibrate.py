#!/usr/bin/env python3
"""Offline tools for fixed-configuration audio calibration.

This module deliberately has no dependency on the Qt application, serial port,
or a microphone device.  It works with paired files produced by a controlled
measurement session: the exact 8 kHz PCM sent to the ESP32 and a separately
recorded microphone WAV.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np


PCM_RATE = 8000
DEFAULT_BAND = (250.0, 3000.0)


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"cannot encode {type(value)!r}")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")


def read_wav_mono(path: Path) -> tuple[np.ndarray, int]:
    """Read uncompressed PCM WAV as float64 mono in approximately [-1, 1]."""
    with wave.open(str(path), "rb") as stream:
        if stream.getcomptype() != "NONE":
            raise ValueError(f"{path}: only PCM WAV is supported")
        channels = stream.getnchannels()
        width = stream.getsampwidth()
        rate = stream.getframerate()
        raw = stream.readframes(stream.getnframes())
    if channels < 1 or width not in (1, 2, 3, 4):
        raise ValueError(f"{path}: unsupported WAV format ({channels} channels, {width * 8} bit)")
    if width == 1:
        values = (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128.0) / 128.0
    elif width == 2:
        values = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    elif width == 3:
        raw_u8 = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        signed = (raw_u8[:, 0].astype(np.int32) | (raw_u8[:, 1].astype(np.int32) << 8) |
                  (raw_u8[:, 2].astype(np.int32) << 16))
        signed = np.where(signed & (1 << 23), signed - (1 << 24), signed)
        values = signed.astype(np.float64) / float(1 << 23)
    else:
        values = np.frombuffer(raw, dtype="<i4").astype(np.float64) / float(1 << 31)
    return values.reshape(-1, channels).mean(axis=1), rate


def write_pcm_u8_wav(path: Path, pcm: np.ndarray, rate: int = PCM_RATE) -> None:
    values = np.asarray(pcm, dtype=np.uint8).reshape(-1)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(1)
        stream.setframerate(rate)
        stream.writeframes(values.tobytes())


def write_pcm16_wav(path: Path, samples: np.ndarray, rate: int = PCM_RATE) -> None:
    encoded = np.clip(np.rint(np.asarray(samples) * 32767.0), -32768, 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(encoded.tobytes())


def decode_pcm_u8(pcm: np.ndarray) -> np.ndarray:
    return (np.asarray(pcm, dtype=np.float64).reshape(-1) - 128.0) / 128.0


def encode_pcm_u8(samples: np.ndarray) -> np.ndarray:
    return np.clip(np.rint(128.0 + 128.0 * np.asarray(samples)), 0, 255).astype(np.uint8)


def load_input_pcm(path: Path) -> np.ndarray:
    samples, rate = read_wav_mono(path)
    if rate != PCM_RATE:
        raise ValueError(f"{path}: input PCM must be {PCM_RATE} Hz, got {rate} Hz")
    # Measurement inputs must already be PCM_U8.  Reconstruct its actual code
    # values instead of accepting a separately normalized floating-point file.
    return np.clip(np.rint(128.0 + 128.0 * samples), 0, 255).astype(np.uint8)


def _sinc_lowpass(cutoff_cycles_per_sample: float, taps: int) -> np.ndarray:
    if not 0.0 < cutoff_cycles_per_sample < 0.5 or taps < 3 or taps % 2 == 0:
        raise ValueError("low-pass requires 0 < cutoff < 0.5 and odd taps >= 3")
    index = np.arange(taps, dtype=np.float64) - taps // 2
    kernel = 2.0 * cutoff_cycles_per_sample * np.sinc(2.0 * cutoff_cycles_per_sample * index)
    kernel *= np.kaiser(taps, beta=8.6)
    return kernel / np.sum(kernel)


def _same_filter(samples: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    return np.convolve(np.asarray(samples, dtype=np.float64), kernel, mode="same")


def resample_for_model(samples: np.ndarray, source_rate: int, target_rate: int = PCM_RATE) -> np.ndarray:
    """Offline, band-limited integer decimation; linear fallback for other ratios."""
    values = np.asarray(samples, dtype=np.float64).reshape(-1)
    if source_rate == target_rate:
        return values
    if source_rate > target_rate and source_rate % target_rate == 0:
        factor = source_rate // target_rate
        kernel = _sinc_lowpass(0.45 / factor, 12 * factor + 1)
        return _same_filter(values, kernel)[::factor]
    count = max(1, round(values.size * target_rate / source_rate))
    positions = np.linspace(0.0, max(0, values.size - 1), count)
    return np.interp(positions, np.arange(values.size), values)


def band_limit(samples: np.ndarray, rate: int = PCM_RATE, low_hz: float = DEFAULT_BAND[0], high_hz: float = DEFAULT_BAND[1]) -> np.ndarray:
    values = np.asarray(samples, dtype=np.float64).reshape(-1)
    if values.size == 0:
        return values
    spectrum = np.fft.rfft(values)
    frequencies = np.fft.rfftfreq(values.size, 1.0 / rate)
    spectrum[(frequencies < low_hz) | (frequencies > high_hz)] = 0.0
    return np.fft.irfft(spectrum, n=values.size)


def align_pair(input_samples: np.ndarray, recorded_samples: np.ndarray, max_lag_samples: int) -> tuple[np.ndarray, np.ndarray, int]:
    """Return aligned x/y and delay where positive delay means y starts later."""
    x = np.asarray(input_samples, dtype=np.float64).reshape(-1)
    y = np.asarray(recorded_samples, dtype=np.float64).reshape(-1)
    if x.size < 8 or y.size < 8:
        raise ValueError("input and recording must both have at least 8 samples")
    size = 1 << (x.size + y.size - 1).bit_length()
    correlation = np.fft.irfft(np.fft.rfft(y, size) * np.fft.rfft(x[::-1], size), size)[: x.size + y.size - 1]
    lags = np.arange(-(x.size - 1), y.size)
    valid = np.abs(lags) <= max_lag_samples
    delay = int(lags[valid][np.argmax(np.abs(correlation[valid]))])
    if delay >= 0:
        count = min(x.size, y.size - delay)
        return x[:count], y[delay:delay + count], delay
    count = min(x.size + delay, y.size)
    return x[-delay:-delay + count], y[:count], delay


def _feature_kernel(oversample: int) -> np.ndarray:
    if oversample < 1:
        raise ValueError("oversample must be at least 1")
    return np.array([1.0]) if oversample == 1 else _sinc_lowpass(0.45 / oversample, 12 * oversample + 1)


def polynomial_features(samples: np.ndarray, orders: tuple[int, ...], oversample: int) -> tuple[np.ndarray, ...]:
    """Return band-limited polynomial features at the original 8 kHz grid."""
    x = np.asarray(samples, dtype=np.float64).reshape(-1)
    if oversample == 1:
        return tuple(x ** order for order in orders)
    kernel = _feature_kernel(oversample)
    upsampled = np.zeros(x.size * oversample, dtype=np.float64)
    upsampled[::oversample] = x
    reconstructed = _same_filter(upsampled, kernel) * oversample
    result = []
    for order in orders:
        powered = reconstructed ** order
        result.append(_same_filter(powered, kernel)[::oversample])
    return tuple(result)


def _design_batch(features: tuple[np.ndarray, ...], start: int, end: int, taps: int, scales: np.ndarray) -> np.ndarray:
    row_count = end - start
    indices = np.arange(start, end)[:, None] + (taps - 1 - np.arange(taps))[None, :]
    columns = [np.ones((row_count, 1), dtype=np.float64)]
    for feature, scale in zip(features, scales, strict=True):
        padded = np.pad(feature, (taps - 1, 0))
        columns.append(padded[indices] / scale)
    return np.concatenate(columns, axis=1)


@dataclass(frozen=True)
class ModelSpec:
    orders: tuple[int, ...]
    taps: int
    oversample: int
    scales: tuple[float, ...]
    intercept: float
    sample_rate: int = PCM_RATE


@dataclass(frozen=True)
class HammersteinModel:
    spec: ModelSpec
    kernels: tuple[np.ndarray, ...]

    def predict(self, samples: np.ndarray) -> np.ndarray:
        features = polynomial_features(samples, self.spec.orders, self.spec.oversample)
        output = np.full(np.asarray(samples).size, self.spec.intercept, dtype=np.float64)
        for feature, kernel, scale in zip(features, self.kernels, self.spec.scales, strict=True):
            output += np.convolve(feature / scale, kernel, mode="full")[: output.size]
        return output

    def gradient(self, samples: np.ndarray, output_gradient: np.ndarray) -> np.ndarray:
        """Exact gradient of sum(output_gradient * predict(samples))."""
        x = np.asarray(samples, dtype=np.float64).reshape(-1)
        residual = np.asarray(output_gradient, dtype=np.float64).reshape(-1)
        if x.size != residual.size:
            raise ValueError("gradient length mismatch")
        features = polynomial_features(x, self.spec.orders, self.spec.oversample)
        base_gradient = np.zeros_like(x)
        kernel = _feature_kernel(self.spec.oversample)
        if self.spec.oversample > 1:
            expanded = np.zeros(x.size * self.spec.oversample, dtype=np.float64)
            expanded[::self.spec.oversample] = x
            reconstructed = _same_filter(expanded, kernel) * self.spec.oversample
        for order, response, scale in zip(self.spec.orders, self.kernels, self.spec.scales, strict=True):
            branch_gradient = np.convolve(residual, response[::-1], mode="full")[self.spec.taps - 1:self.spec.taps - 1 + x.size] / scale
            if self.spec.oversample == 1:
                base_gradient += branch_gradient * order * x ** (order - 1)
            else:
                lifted = np.zeros(x.size * self.spec.oversample, dtype=np.float64)
                lifted[::self.spec.oversample] = branch_gradient
                derivative = _same_filter(lifted, kernel)
                derivative *= order * reconstructed ** (order - 1)
                base_gradient += (_same_filter(derivative, kernel) * self.spec.oversample)[::self.spec.oversample]
        return base_gradient

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"metadata": np.array(json.dumps(asdict(self.spec), default=_json_default))}
        payload.update({f"kernel_{index}": kernel for index, kernel in enumerate(self.kernels)})
        np.savez_compressed(path, **payload)

    @classmethod
    def load(cls, path: Path) -> "HammersteinModel":
        with np.load(path, allow_pickle=False) as data:
            metadata = json.loads(str(data["metadata"]))
            spec = ModelSpec(orders=tuple(metadata["orders"]), taps=int(metadata["taps"]), oversample=int(metadata["oversample"]), scales=tuple(metadata["scales"]), intercept=float(metadata["intercept"]), sample_rate=int(metadata["sample_rate"]))
            kernels = tuple(np.asarray(data[f"kernel_{index}"], dtype=np.float64) for index in range(len(spec.orders)))
        return cls(spec, kernels)


@dataclass(frozen=True)
class PairedTake:
    identifier: str
    input_path: Path
    recording_path: Path
    split: str
    start_s: float = 0.0
    end_s: float | None = None
    max_lag_ms: float = 250.0


def load_manifest(path: Path) -> list[PairedTake]:
    document = json.loads(path.read_text(encoding="utf-8"))
    root = path.parent
    takes = []
    for item in document["takes"]:
        takes.append(PairedTake(identifier=str(item["id"]), input_path=root / item["input"], recording_path=root / item["recording"], split=str(item.get("split", "train")), start_s=float(item.get("start_s", 0.0)), end_s=float(item["end_s"]) if item.get("end_s") is not None else None, max_lag_ms=float(item.get("max_lag_ms", 250.0))))
    return takes


def load_take(take: PairedTake) -> tuple[np.ndarray, np.ndarray, int]:
    pcm = load_input_pcm(take.input_path)
    x = decode_pcm_u8(pcm)
    recorded, rate = read_wav_mono(take.recording_path)
    y = resample_for_model(recorded, rate)
    x, y, delay = align_pair(x, y, round(take.max_lag_ms * PCM_RATE / 1000.0))
    start = max(0, round(take.start_s * PCM_RATE))
    end = round(take.end_s * PCM_RATE) if take.end_s is not None else x.size
    end = min(end, x.size)
    if end - start < 1024:
        raise ValueError(f"{take.identifier}: effective segment is shorter than 1024 samples")
    return x[start:end], y[start:end], delay


def _feature_scales(takes: Iterable[PairedTake], orders: tuple[int, ...], oversample: int) -> np.ndarray:
    total = np.zeros(len(orders), dtype=np.float64)
    count = 0
    for take in takes:
        x, _, _ = load_take(take)
        features = polynomial_features(x, orders, oversample)
        total += np.array([np.dot(item, item) for item in features])
        count += x.size
    if count == 0:
        raise ValueError("no training takes")
    return np.maximum(np.sqrt(total / count), 1e-9)


def fit_model(train_takes: list[PairedTake], orders: tuple[int, ...], taps: int, ridge: float, oversample: int, batch_size: int = 4096) -> HammersteinModel:
    if taps < 1 or ridge < 0:
        raise ValueError("taps must be positive and ridge cannot be negative")
    scales = _feature_scales(train_takes, orders, oversample)
    width = 1 + len(orders) * taps
    normal = np.zeros((width, width), dtype=np.float64)
    rhs = np.zeros(width, dtype=np.float64)
    for take in train_takes:
        x, y, _ = load_take(take)
        features = polynomial_features(x, orders, oversample)
        for start in range(0, x.size, batch_size):
            end = min(start + batch_size, x.size)
            design = _design_batch(features, start, end, taps, scales)
            normal += design.T @ design
            rhs += design.T @ y[start:end]
    penalty = np.eye(width, dtype=np.float64) * ridge
    penalty[0, 0] = 0.0
    parameters = np.linalg.solve(normal + penalty, rhs)
    kernels = tuple(parameters[1 + index * taps:1 + (index + 1) * taps] for index in range(len(orders)))
    return HammersteinModel(ModelSpec(orders, taps, oversample, tuple(scales), float(parameters[0])), kernels)


def metrics_for_pair(model: HammersteinModel, x: np.ndarray, y: np.ndarray, band: tuple[float, float]) -> dict[str, float]:
    prediction = model.predict(x)
    valid_start = min(model.spec.taps, max(0, x.size // 8))
    actual = band_limit(y[valid_start:], low_hz=band[0], high_hz=band[1])
    predicted = band_limit(prediction[valid_start:], low_hz=band[0], high_hz=band[1])
    residual = actual - predicted
    signal_energy = float(np.dot(actual, actual))
    residual_energy = float(np.dot(residual, residual))
    return {"samples": int(actual.size), "nmse_db": float(10.0 * math.log10(max(residual_energy, 1e-30) / max(signal_energy, 1e-30))), "actual_rms": float(np.sqrt(np.mean(actual ** 2))), "prediction_rms": float(np.sqrt(np.mean(predicted ** 2)))}


def evaluate_model(model: HammersteinModel, takes: Iterable[PairedTake], band: tuple[float, float]) -> dict[str, Any]:
    entries = []
    for take in takes:
        x, y, delay = load_take(take)
        entry = metrics_for_pair(model, x, y, band)
        entry.update(id=take.identifier, split=take.split, alignment_delay_samples=delay)
        entries.append(entry)
    grouped: dict[str, list[float]] = {}
    for entry in entries:
        grouped.setdefault(entry["split"], []).append(entry["nmse_db"])
    return {"band_hz": list(band), "takes": entries, "mean_nmse_db_by_split": {name: float(np.mean(values)) for name, values in grouped.items()}}


def make_signal(kind: str, duration_s: float, peak: float, seed: int, f_low: float, f_high: float) -> np.ndarray:
    count = round(duration_s * PCM_RATE)
    if count < 8 or not 0.0 < peak <= 0.98 or not 0 < f_low < f_high < PCM_RATE / 2:
        raise ValueError("invalid signal parameters")
    time = np.arange(count, dtype=np.float64) / PCM_RATE
    rng = np.random.default_rng(seed)
    if kind == "multitone":
        bins = np.arange(math.ceil(f_low), math.floor(f_high) + 1)
        bins = bins[bins % 37 == 0]
        if bins.size < 4:
            bins = np.linspace(f_low, f_high, 16, dtype=int)
        signal = sum(np.cos(2.0 * np.pi * frequency * time + phase) for frequency, phase in zip(bins, rng.uniform(0, 2 * np.pi, bins.size), strict=True))
    elif kind == "noise":
        spectrum = np.zeros(count // 2 + 1, dtype=np.complex128)
        frequencies = np.fft.rfftfreq(count, 1 / PCM_RATE)
        active = (frequencies >= f_low) & (frequencies <= f_high)
        spectrum[active] = np.exp(1j * rng.uniform(0, 2 * np.pi, active.sum()))
        signal = np.fft.irfft(spectrum, count)
    elif kind == "chirp":
        rate = (f_high - f_low) / duration_s
        signal = np.sin(2 * np.pi * (f_low * time + 0.5 * rate * time ** 2))
    else:
        raise ValueError(f"unknown signal kind: {kind}")
    signal = peak * signal / max(float(np.max(np.abs(signal))), 1e-12)
    fade = min(round(0.02 * PCM_RATE), count // 8)
    envelope = np.ones(count)
    envelope[:fade] = np.linspace(0.0, 1.0, fade, endpoint=False)
    envelope[-fade:] = np.linspace(1.0, 0.0, fade, endpoint=False)
    return signal * envelope


def write_header(path: Path, pcm: np.ndarray) -> None:
    values = np.asarray(pcm, dtype=np.uint8)
    lines = ["#pragma once", "", "#include <Arduino.h>", "", f"static constexpr uint32_t kAudioSampleRate = {PCM_RATE};", "static constexpr bool kAudioIsDemo = false;", "static constexpr uint8_t kAudioSamples[] PROGMEM = {"]
    lines.extend("    " + ", ".join(str(value) for value in values[offset:offset + 16]) + "," for offset in range(0, values.size, 16))
    lines.extend(["};", "static constexpr uint32_t kAudioSampleCount = sizeof(kAudioSamples);", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def prepare_experiment(args: argparse.Namespace) -> int:
    destination = Path(args.output).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    takes = []
    index = 1
    for kind in args.kinds:
        for peak in args.peaks:
            for seed in range(args.seeds):
                identifier = f"{kind}_a{peak:.2f}_s{seed:02d}"
                signal = make_signal(kind, args.duration_s, peak, seed, args.low_hz, args.high_hz)
                pcm = encode_pcm_u8(signal)
                take_dir = destination / identifier
                take_dir.mkdir(exist_ok=True)
                write_pcm_u8_wav(take_dir / "input.wav", pcm)
                (take_dir / "input_u8.bin").write_bytes(pcm.tobytes())
                write_header(take_dir / "input.h", pcm)
                metadata = {"id": identifier, "signal": kind, "seed": seed, "requested_peak": peak, "actual_peak": float(np.max(np.abs(decode_pcm_u8(pcm)))), "actual_rms": float(np.sqrt(np.mean(decode_pcm_u8(pcm) ** 2))), "sample_rate": PCM_RATE, "input_sha256": hashlib.sha256(pcm.tobytes()).hexdigest(), "playback": {"processing": args.processing, "drive": args.drive, "modulation": args.modulation}}
                write_json(take_dir / "metadata.json", metadata)
                # Keep every amplitude of one signal family/seed in one split.
                # Otherwise the validation set would contain nearly the same
                # waveform as the training set at a different level.
                split_bucket = int.from_bytes(hashlib.sha256(f"{kind}:{seed}".encode()).digest()[:2], "little") % 5
                split = "train" if split_bucket < 3 else "validation" if split_bucket == 3 else "test"
                takes.append({"id": identifier, "input": f"{identifier}/input.wav", "recording": f"{identifier}/recorded.wav", "split": split})
                index += 1
    manifest = {"format": 1, "sample_rate": PCM_RATE, "note": "Copy independently recorded microphone WAV files to the recording paths before fitting. Splits are by complete generated signal.", "takes": takes}
    write_json(destination / "manifest.json", manifest)
    print(f"Prepared {len(takes)} takes in {destination}")
    return 0


def fit_command(args: argparse.Namespace) -> int:
    takes = load_manifest(Path(args.manifest).resolve())
    train = [take for take in takes if take.split == "train"]
    if not train:
        raise ValueError("manifest contains no train takes")
    orders = tuple(sorted(set(args.orders)))
    model = fit_model(train, orders, args.taps, args.ridge, args.oversample, args.batch_size)
    model_path = Path(args.model).resolve()
    model.save(model_path)
    report = evaluate_model(model, takes, (args.low_hz, args.high_hz))
    report["model"] = {"path": str(model_path), **asdict(model.spec), "ridge": args.ridge}
    write_json(model_path.with_suffix(".report.json"), report)
    print(json.dumps(report["mean_nmse_db_by_split"], ensure_ascii=False))
    return 0


def evaluate_command(args: argparse.Namespace) -> int:
    model = HammersteinModel.load(Path(args.model).resolve())
    takes = load_manifest(Path(args.manifest).resolve())
    if args.split:
        takes = [take for take in takes if take.split == args.split]
    report = evaluate_model(model, takes, (args.low_hz, args.high_hz))
    if args.output:
        write_json(Path(args.output).resolve(), report)
    print(json.dumps(report["mean_nmse_db_by_split"], ensure_ascii=False))
    return 0


def predistort_command(args: argparse.Namespace) -> int:
    model = HammersteinModel.load(Path(args.model).resolve())
    target, target_rate = read_wav_mono(Path(args.target).resolve())
    target = resample_for_model(target, target_rate)
    target = band_limit(target, low_hz=args.low_hz, high_hz=args.high_hz)
    if args.method == "linear":
        if 1 not in model.spec.orders:
            raise ValueError("linear predistortion requires an order-1 branch")
        index = model.spec.orders.index(1)
        active_model = HammersteinModel(
            ModelSpec((1,), model.spec.taps, model.spec.oversample, (model.spec.scales[index],), model.spec.intercept),
            (model.kernels[index],),
        )
        energy_weight = args.regularization
    else:
        active_model = model
        energy_weight = args.energy_weight
    # The fixed feature reconstruction can be non-causal at a block edge, so
    # use the model's exact gradient rather than inverting only h_1 in FFT.
    solution = np.clip(target, -args.peak_limit, args.peak_limit)
    step = args.step_size
    current = active_model.predict(solution) - target
    current_loss = float(np.mean(current ** 2) + energy_weight * np.mean(solution ** 2))
    accepted_steps = 0
    for _ in range(args.iterations):
        gradient = active_model.gradient(solution, current) / max(1, solution.size)
        gradient += energy_weight * solution / max(1, solution.size)
        candidate = np.clip(solution - step * gradient, -args.peak_limit, args.peak_limit)
        candidate_residual = active_model.predict(candidate) - target
        candidate_loss = float(np.mean(candidate_residual ** 2) + energy_weight * np.mean(candidate ** 2))
        if candidate_loss <= current_loss:
            solution, current, current_loss = candidate, candidate_residual, candidate_loss
            accepted_steps += 1
            step *= 1.05
        else:
            step *= 0.5
    pcm = encode_pcm_u8(np.clip(solution, -args.peak_limit, args.peak_limit))
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    write_pcm_u8_wav(output / "input.wav", pcm)
    (output / "input_u8.bin").write_bytes(pcm.tobytes())
    write_header(output / "input.h", pcm)
    actual = decode_pcm_u8(pcm)
    report = {"method": args.method, "model": str(Path(args.model).resolve()), "peak_limit": args.peak_limit, "iterations": args.iterations, "accepted_steps": accepted_steps, "final_step_size": step, "predicted_nmse_db": metrics_for_pair(model, actual, target, (args.low_hz, args.high_hz))["nmse_db"], "actual_peak": float(np.max(np.abs(actual))), "actual_rms": float(np.sqrt(np.mean(actual ** 2))), "target_rate": target_rate}
    write_json(output / "predistort_report.json", report)
    print(json.dumps(report, ensure_ascii=False))
    return 0


def smoke_command(args: argparse.Namespace) -> int:
    paths = [Path(path) for path in args.wav]
    if not paths:
        raise ValueError("provide one or more --wav paths; smoke never fits a model from data/")
    report = []
    for path in paths:
        samples, rate = read_wav_mono(path)
        reduced = resample_for_model(samples, rate)
        features = polynomial_features(reduced, (1, 2, 3), args.oversample)
        report.append({"path": str(path), "source_rate": rate, "source_samples": int(samples.size), "model_samples": int(reduced.size), "feature_finite": bool(all(np.all(np.isfinite(item)) for item in features))})
    print(json.dumps({"smoke_only": True, "files": report}, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="generate amplitude-preserving PCM experiment takes")
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--kinds", nargs="+", choices=("multitone", "noise", "chirp"), default=("multitone", "noise"))
    prepare.add_argument("--peaks", nargs="+", type=float, default=(0.10, 0.20, 0.40, 0.60))
    prepare.add_argument("--seeds", type=int, default=6)
    prepare.add_argument("--duration-s", type=float, default=8.0)
    prepare.add_argument("--low-hz", type=float, default=DEFAULT_BAND[0])
    prepare.add_argument("--high-hz", type=float, default=DEFAULT_BAND[1])
    prepare.add_argument("--processing", choices=("raw", "loud"), default="raw")
    prepare.add_argument("--drive", choices=("standard", "boost"), default="standard")
    prepare.add_argument("--modulation", choices=("dsb", "sram"), default="dsb")
    prepare.set_defaults(function=prepare_experiment)

    fit = commands.add_parser("fit", help="fit a fixed parallel Hammerstein model")
    fit.add_argument("--manifest", required=True)
    fit.add_argument("--model", required=True)
    fit.add_argument("--orders", nargs="+", type=int, choices=(1, 2, 3), default=(1, 2, 3))
    fit.add_argument("--taps", type=int, default=128)
    fit.add_argument("--ridge", type=float, default=1e-3)
    fit.add_argument("--oversample", type=int, default=6)
    fit.add_argument("--batch-size", type=int, default=4096)
    fit.add_argument("--low-hz", type=float, default=DEFAULT_BAND[0])
    fit.add_argument("--high-hz", type=float, default=DEFAULT_BAND[1])
    fit.set_defaults(function=fit_command)

    evaluate = commands.add_parser("evaluate", help="evaluate a frozen model against a manifest")
    evaluate.add_argument("--manifest", required=True)
    evaluate.add_argument("--model", required=True)
    evaluate.add_argument("--split", choices=("train", "validation", "test"))
    evaluate.add_argument("--output")
    evaluate.add_argument("--low-hz", type=float, default=DEFAULT_BAND[0])
    evaluate.add_argument("--high-hz", type=float, default=DEFAULT_BAND[1])
    evaluate.set_defaults(function=evaluate_command)

    predistort = commands.add_parser("predistort", help="create 8 kHz PCM from a frozen model and target WAV")
    predistort.add_argument("--model", required=True)
    predistort.add_argument("--target", required=True)
    predistort.add_argument("--output", required=True)
    predistort.add_argument("--method", choices=("linear", "nonlinear"), default="linear")
    predistort.add_argument("--regularization", type=float, default=1e-3)
    predistort.add_argument("--iterations", type=int, default=40)
    predistort.add_argument("--step-size", type=float, default=0.5)
    predistort.add_argument("--energy-weight", type=float, default=1e-4)
    predistort.add_argument("--peak-limit", type=float, default=0.60)
    predistort.add_argument("--low-hz", type=float, default=DEFAULT_BAND[0])
    predistort.add_argument("--high-hz", type=float, default=DEFAULT_BAND[1])
    predistort.set_defaults(function=predistort_command)

    smoke = commands.add_parser("smoke", help="load WAV files and exercise preprocessing only")
    smoke.add_argument("--wav", action="append", required=True)
    smoke.add_argument("--oversample", type=int, default=6)
    smoke.set_defaults(function=smoke_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.function(args))


if __name__ == "__main__":
    raise SystemExit(main())
