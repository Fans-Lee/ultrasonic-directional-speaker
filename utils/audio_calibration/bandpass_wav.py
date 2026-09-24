#!/usr/bin/env python3
"""Keep only a chosen frequency band in a PCM WAV recording.

This is an offline, zero-phase FFT filter.  It preserves the sample rate,
channel count and duration, and writes 24-bit PCM without normalization.
"""

from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

import numpy as np


def read_pcm_wav(path: Path) -> tuple[np.ndarray, int, int]:
    """Return frames x channels, sample rate, and source bit depth."""
    with wave.open(str(path), "rb") as source:
        if source.getcomptype() != "NONE":
            raise ValueError("Only uncompressed PCM WAV input is supported")
        channels = source.getnchannels()
        width = source.getsampwidth()
        rate = source.getframerate()
        raw = source.readframes(source.getnframes())
    if channels < 1 or rate < 1 or width not in (1, 2, 3, 4):
        raise ValueError("Unsupported PCM WAV format")
    if len(raw) % (width * channels):
        raise ValueError("WAV ends with an incomplete sample frame")
    if not raw:
        raise ValueError("WAV contains no samples")

    if width == 1:
        samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128.0) / 128.0
    elif width == 2:
        samples = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    elif width == 3:
        octets = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        signed = (octets[:, 0].astype(np.int32)
                  | (octets[:, 1].astype(np.int32) << 8)
                  | (octets[:, 2].astype(np.int32) << 16))
        samples = np.where(signed & 0x800000, signed - 0x1000000, signed).astype(np.float64) / 8388608.0
    else:
        samples = np.frombuffer(raw, dtype="<i4").astype(np.float64) / 2147483648.0
    return samples.reshape(-1, channels), rate, width * 8


def frequency_mask(length: int, sample_rate: int, low_hz: float, high_hz: float,
                   transition_hz: float) -> np.ndarray:
    """Exact zero outside [low, high], with optional cosine ramps inside it."""
    if length < 1 or sample_rate < 1:
        raise ValueError("Audio length and sample rate must be positive")
    if not 0 < low_hz < high_hz < sample_rate / 2:
        raise ValueError("Require 0 < low < high < the WAV Nyquist frequency")
    if not 0 <= transition_hz < (high_hz - low_hz) / 2:
        raise ValueError("Transition width must be nonnegative and less than half the passband")

    frequencies = np.fft.rfftfreq(length, d=1.0 / sample_rate)
    mask = np.zeros_like(frequencies)
    if transition_hz == 0:
        mask[(frequencies >= low_hz) & (frequencies <= high_hz)] = 1.0
        return mask
    interior = (frequencies >= low_hz + transition_hz) & (frequencies <= high_hz - transition_hz)
    lower = (frequencies > low_hz) & (frequencies < low_hz + transition_hz)
    upper = (frequencies > high_hz - transition_hz) & (frequencies < high_hz)
    mask[interior] = 1.0
    mask[lower] = 0.5 - 0.5 * np.cos(np.pi * (frequencies[lower] - low_hz) / transition_hz)
    mask[upper] = 0.5 - 0.5 * np.cos(np.pi * (high_hz - frequencies[upper]) / transition_hz)
    return mask


def filter_samples(samples: np.ndarray, sample_rate: int, low_hz: float = 250.0,
                   high_hz: float = 3000.0, transition_hz: float = 50.0,
                   edge_fade_ms: float = 10.0) -> np.ndarray:
    """Filter each channel independently, keeping exactly the original frame count."""
    values = np.asarray(samples, dtype=np.float64)
    if values.ndim != 2 or values.shape[0] == 0 or values.shape[1] == 0:
        raise ValueError("Audio must have shape (frames, channels)")
    if not np.all(np.isfinite(values)):
        raise ValueError("Audio contains a non-finite sample")
    if edge_fade_ms < 0:
        raise ValueError("Edge fade must be nonnegative")
    mask = frequency_mask(values.shape[0], sample_rate, low_hz, high_hz, transition_hz)
    windowed = values.copy()
    fade_count = min(round(edge_fade_ms * sample_rate / 1000), values.shape[0] // 2)
    if fade_count:
        fade = np.sin(0.5 * np.pi * np.arange(fade_count) / fade_count) ** 2
        windowed[:fade_count] *= fade[:, None]
        windowed[-fade_count:] *= fade[::-1, None]
    spectrum = np.fft.rfft(windowed, axis=0)
    spectrum *= mask[:, None]
    return np.fft.irfft(spectrum, n=values.shape[0], axis=0)


def write_pcm24_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    values = np.asarray(samples, dtype=np.float64)
    if values.ndim != 2 or values.size == 0:
        raise ValueError("Audio must have shape (frames, channels)")
    if float(np.max(np.abs(values))) >= 1.0:
        raise ValueError("Filtered output exceeds digital full scale; lower --gain-db before saving")
    encoded = np.rint(values * 8388608.0).astype("<i4")
    raw = np.ascontiguousarray(encoded.reshape(-1)).view(np.uint8).reshape(-1, 4)[:, :3].tobytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as destination:
        destination.setnchannels(values.shape[1])
        destination.setsampwidth(3)
        destination.setframerate(sample_rate)
        destination.writeframes(raw)


def _level_dbfs(samples: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    return 20.0 * float(np.log10(max(rms, 1e-15)))


def _spectral_band_level(samples: np.ndarray, sample_rate: int,
                         low_hz: float, high_hz: float) -> float:
    frequencies = np.fft.rfftfreq(samples.shape[0], 1.0 / sample_rate)
    selected = (frequencies >= low_hz) & (frequencies < high_hz)
    spectrum = np.fft.rfft(samples, axis=0)
    spectrum[~selected] = 0.0
    band = np.fft.irfft(spectrum, n=samples.shape[0], axis=0)
    return _level_dbfs(band)


def build_report(source: np.ndarray, filtered: np.ndarray, sample_rate: int,
                 low_hz: float, high_hz: float) -> dict:
    nyquist = sample_rate / 2
    bands = [(low_hz, high_hz)]
    if nyquist > 17000:
        bands.append((8000.0, 17000.0))
    report = {
        "sample_rate_hz": sample_rate,
        "channels": source.shape[1],
        "duration_s": source.shape[0] / sample_rate,
        "passed_band_hz": [low_hz, high_hz],
        "rms_dbfs": {"original": _level_dbfs(source), "filtered": _level_dbfs(filtered)},
        "peak_dbfs": {"original": 20.0 * float(np.log10(max(float(np.max(np.abs(source))), 1e-15))),
                      "filtered": 20.0 * float(np.log10(max(float(np.max(np.abs(filtered))), 1e-15)))},
        "per_channel_peak_dbfs": {
            "original": (20.0 * np.log10(np.maximum(np.max(np.abs(source), axis=0), 1e-15))).tolist(),
            "filtered": (20.0 * np.log10(np.maximum(np.max(np.abs(filtered), axis=0), 1e-15))).tolist(),
        },
        "per_channel_rms_dbfs": {
            "original": (20.0 * np.log10(np.maximum(np.sqrt(np.mean(source ** 2, axis=0)), 1e-15))).tolist(),
            "filtered": (20.0 * np.log10(np.maximum(np.sqrt(np.mean(filtered ** 2, axis=0)), 1e-15))).tolist(),
        },
        "band_rms_dbfs": {},
    }
    for low, high in bands:
        key = f"{low:g}-{high:g}Hz"
        report["band_rms_dbfs"][key] = {
            "original": _spectral_band_level(source, sample_rate, low, high),
            "filtered": _spectral_band_level(filtered, sample_rate, low, high),
        }
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="uncompressed PCM WAV to filter")
    parser.add_argument("output", type=Path, help="24-bit PCM WAV output")
    parser.add_argument("--low-hz", type=float, default=250.0)
    parser.add_argument("--high-hz", type=float, default=3000.0)
    parser.add_argument("--transition-hz", type=float, default=50.0,
                        help="cosine ramps inside passband; 0 gives hard frequency cut")
    parser.add_argument("--edge-fade-ms", type=float, default=10.0,
                        help="fade source endpoints to reduce FFT wraparound ringing")
    parser.add_argument("--gain-db", type=float, default=0.0,
                        help="optional fixed output gain; default preserves level")
    parser.add_argument("--channel", choices=("preserve", "left", "right", "mono"),
                        default="preserve", help="which input channels to filter and write")
    parser.add_argument("--no-report", action="store_true", help="skip writing a JSON report")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    source_path = arguments.input.resolve()
    output_path = arguments.output.resolve()
    if source_path == output_path:
        raise ValueError("Output path must differ from input path")
    if output_path.suffix.lower() != ".wav":
        raise ValueError("Output must have a .wav extension")
    if not np.isfinite(arguments.gain_db):
        raise ValueError("Output gain must be finite")
    source, sample_rate, source_bits = read_pcm_wav(source_path)
    input_channels = source.shape[1]
    if arguments.channel == "left":
        source = source[:, :1]
    elif arguments.channel == "right":
        if input_channels < 2:
            raise ValueError("--channel right requires at least two input channels")
        source = source[:, 1:2]
    elif arguments.channel == "mono":
        source = source.mean(axis=1, keepdims=True)
    filtered = filter_samples(source, sample_rate, arguments.low_hz,
                              arguments.high_hz, arguments.transition_hz,
                              arguments.edge_fade_ms)
    filtered *= 10.0 ** (arguments.gain_db / 20.0)
    write_pcm24_wav(output_path, filtered, sample_rate)
    # Report the actual saved PCM, including its quantization floor.
    saved, _, _ = read_pcm_wav(output_path)
    report = build_report(source, saved, sample_rate,
                          arguments.low_hz, arguments.high_hz)
    report.update(input=str(source_path), output=str(output_path),
                  input_bits=source_bits, output_bits=24,
                  input_channels=input_channels, channel_selection=arguments.channel,
                  transition_hz=arguments.transition_hz,
                  edge_fade_ms=arguments.edge_fade_ms, gain_db=arguments.gain_db)
    if not arguments.no_report:
        report_path = output_path.with_suffix(".report.json")
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
