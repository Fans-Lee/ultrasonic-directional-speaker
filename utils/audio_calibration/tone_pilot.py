#!/usr/bin/env python3
"""Fit a small, recording-specific harmonic profile from unpaired tone WAVs.

The result describes the recordings, including their microphone and room. It
does not estimate the speaker's input-to-air transfer function or a usable
predistortion filter: source PCM levels and acoustic ground truth are unknown.
"""

from __future__ import annotations

import argparse
import json
import re
import wave
from pathlib import Path

import numpy as np


def read_pcm_channels(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wav:
        if wav.getcomptype() != "NONE":
            raise ValueError(f"{path}: only uncompressed PCM WAV is supported")
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        raw = wav.readframes(wav.getnframes())
    if width == 1:
        data = (np.frombuffer(raw, np.uint8).astype(np.float64) - 128) / 128
    elif width == 2:
        data = np.frombuffer(raw, "<i2").astype(np.float64) / 32768
    elif width == 3:
        octets = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
        signed = octets[:, 0] | (octets[:, 1] << 8) | (octets[:, 2] << 16)
        data = np.where(signed & 0x800000, signed - 0x1000000, signed) / 8388608
    elif width == 4:
        data = np.frombuffer(raw, "<i4").astype(np.float64) / 2147483648
    else:
        raise ValueError(f"{path}: unsupported PCM width")
    if channels < 1 or data.size % channels:
        raise ValueError(f"{path}: invalid channel data")
    return data.reshape(-1, channels), rate


def label_hz(path: Path) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*Hz", path.stem, re.IGNORECASE)
    return float(match.group(1)) if match else None


def tone_amplitude(spectrum: np.ndarray, frequencies: np.ndarray, center: float, width_hz: float = 15.0) -> tuple[float, float]:
    indices = np.flatnonzero(np.abs(frequencies - center) <= width_hz)
    if indices.size == 0:
        return 0.0, float("nan")
    index = int(indices[np.argmax(spectrum[indices])])
    return float(spectrum[index]), float(frequencies[index])


def inspect_tone(path: Path, max_harmonic: int = 4, window_s: float = 0.5, analysis_high_hz: float = 8000.0) -> dict:
    samples, rate = read_pcm_channels(path)
    if rate <= 2 * analysis_high_hz:
        raise ValueError(f"{path}: sampling rate is too low for {analysis_high_hz:g} Hz analysis")
    frame = round(window_s * rate)
    if frame < 1000 or samples.shape[0] < 3 * frame:
        raise ValueError(f"{path}: need at least three analysis windows")
    # Exclude start/stop edges. A recording may have silence or transients there.
    work = samples[frame // 2 : samples.shape[0] - frame // 2]
    windows = work[: (work.shape[0] // frame) * frame].reshape(-1, frame, samples.shape[1])
    taper = np.hanning(frame)
    spectra = np.abs(np.fft.rfft((windows - windows.mean(axis=1, keepdims=True)) * taper[None, :, None], axis=1)) / (taper.sum() / 2)
    frequencies = np.fft.rfftfreq(frame, 1 / rate)
    search = (frequencies >= 250) & (frequencies <= 3000)
    # A peak's median amplitude across windows is more robust than one transient.
    median_spectra = np.median(spectra, axis=0)
    candidates = median_spectra[search].max(axis=0)
    channel = int(np.argmax(candidates))
    search_indices = np.flatnonzero(search)
    fundamental_bin = int(search_indices[np.argmax(median_spectra[search, channel])])
    fundamental_hz = float(frequencies[fundamental_bin])
    fundamentals = np.array([tone_amplitude(row[:, channel], frequencies, fundamental_hz)[0] for row in spectra])
    active = fundamentals >= 0.35 * max(float(np.max(fundamentals)), 1e-12)
    if np.count_nonzero(active) < 2:
        raise ValueError(f"{path}: insufficient steady tone windows")
    observed = {}
    for harmonic in range(1, max_harmonic + 1):
        center = harmonic * fundamental_hz
        if center > analysis_high_hz:
            continue
        levels = []
        for row in spectra[active]:
            amplitude, _ = tone_amplitude(row[:, channel], frequencies, center)
            levels.append(amplitude)
        observed[str(harmonic)] = np.asarray(levels)
    fundamental_levels = observed["1"]
    ratios = {}
    for harmonic, levels in observed.items():
        if harmonic == "1":
            continue
        values = 20 * np.log10(np.maximum(levels, 1e-12) / np.maximum(fundamental_levels, 1e-12))
        ratios[harmonic] = {
            "median_dbc": round(float(np.median(values)), 2),
            "spread_mad_db": round(float(np.median(np.abs(values - np.median(values)))), 2),
            "frequency_hz": round(int(harmonic) * fundamental_hz, 2),
            "inside_project_audio_band": 250 <= int(harmonic) * fundamental_hz <= 3000,
        }
    label = label_hz(path)
    return {
        "file": str(path), "label_hz": label, "detected_hz": fundamental_hz,
        "label_error_hz": None if label is None else round(fundamental_hz - label, 2),
        "channel_index_zero_based": channel, "sample_rate_hz": rate,
        "duration_s": round(samples.shape[0] / rate, 3),
        "analyzed_windows": int(np.count_nonzero(active)),
        "fundamental_median_dbfs": round(float(20 * np.log10(max(float(np.median(fundamental_levels)), 1e-12))), 2),
        "channel_peak": round(float(np.max(np.abs(samples[:, channel]))), 6),
        "channel_samples_near_full_scale_percent": round(float(np.mean(np.abs(samples[:, channel]) >= 0.999) * 100), 6),
        "harmonics": ratios,
    }


def interpolate_ratio(rows: list[dict], frequency: float, harmonic: str) -> float:
    points = sorted((row["detected_hz"], row["harmonics"][harmonic]["median_dbc"])
                    for row in rows if harmonic in row["harmonics"])
    if len(points) < 2:
        raise ValueError(f"need at least two recordings for harmonic {harmonic}")
    frequencies, ratios = zip(*points)
    return float(np.interp(frequency, frequencies, ratios))


def fit_profile(rows: list[dict], max_harmonic: int) -> dict:
    if len(rows) < 3:
        raise ValueError("need at least three recordings for leave-one-out validation")
    frequency_values = [row["detected_hz"] for row in rows]
    if len(set(frequency_values)) != len(rows):
        raise ValueError("recordings contain duplicate detected fundamentals")
    curves = {}
    validation = []
    for harmonic in range(2, max_harmonic + 1):
        key = str(harmonic)
        supporting = [row for row in rows if key in row["harmonics"]]
        if len(supporting) < 3:
            continue
        supporting.sort(key=lambda row: row["detected_hz"])
        curves[key] = [{"frequency_hz": row["detected_hz"], "relative_db": row["harmonics"][key]["median_dbc"]} for row in supporting]
        for held_out in supporting:
            others = [row for row in supporting if row is not held_out]
            prediction = interpolate_ratio(others, held_out["detected_hz"], key)
            observed = held_out["harmonics"][key]["median_dbc"]
            validation.append({"harmonic": harmonic, "held_out_hz": held_out["detected_hz"], "observed_dbc": observed, "predicted_dbc": round(prediction, 2), "error_db": round(prediction - observed, 2)})
    by_harmonic = {}
    for harmonic in range(2, max_harmonic + 1):
        errors = [abs(row["error_db"]) for row in validation if row["harmonic"] == harmonic]
        if errors:
            by_harmonic[str(harmonic)] = round(float(np.median(errors)), 2)
    return {
        "model_type": "piecewise_linear_harmonic_ratio_vs_detected_frequency",
        "meaning": "phone/room recording profile only; no calibrated PCM input or physical acoustic reference",
        "valid_frequency_range_hz": [min(frequency_values), max(frequency_values)],
        "curves": curves, "leave_one_recording_out": validation,
        "median_absolute_validation_error_db": round(float(np.median([abs(row["error_db"]) for row in validation])), 2) if validation else None,
        "median_absolute_validation_error_db_by_harmonic": by_harmonic,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True, help="directory of single-tone PCM WAV recordings")
    parser.add_argument("--output", type=Path, required=True, help="JSON result path")
    parser.add_argument("--max-harmonic", type=int, default=4)
    parser.add_argument("--window-s", type=float, default=0.5)
    parser.add_argument("--analysis-high-hz", type=float, default=8000.0)
    args = parser.parse_args(argv)
    if args.max_harmonic < 2 or args.window_s <= 0:
        parser.error("max-harmonic must be >= 2 and window-s must be positive")
    paths = sorted(args.input_dir.glob("*.wav"))
    if not paths:
        parser.error(f"no WAV files in {args.input_dir}")
    observations = [inspect_tone(path, args.max_harmonic, args.window_s, args.analysis_high_hz) for path in paths]
    model = fit_profile(observations, args.max_harmonic)
    warnings = [f"{Path(row['file']).name}: filename says {row['label_hz']:g} Hz but measured {row['detected_hz']:g} Hz"
                for row in observations if row["label_hz"] is not None and abs(row["label_error_hz"]) > 15]
    result = {"input_dir": str(args.input_dir.resolve()), "recordings": observations, "warnings": warnings, "fitted_profile": model}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "detected_hz": {Path(row["file"]).name: row["detected_hz"] for row in observations}, "warnings": warnings, "median_absolute_validation_error_db_by_harmonic": model["median_absolute_validation_error_db_by_harmonic"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
