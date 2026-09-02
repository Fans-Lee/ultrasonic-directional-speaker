#!/usr/bin/env python3
"""Analyze PCM WAV files and export their time-frequency-intensity relations.

The script uses a Hann-window short-time Fourier transform (STFT) and creates:

1. ``<prefix>.png``: a spectrogram whose color is the level in dBFS.
2. ``<prefix>.csv``: the underlying time, frequency, and level values.

Examples (run from the project root):

    uv run python utils/wav_time_frequency.py input.wav
    uv run python utils/wav_time_frequency.py first.wav second.wav
    uv run python utils/wav_time_frequency.py data/ --recursive \
        --output-dir analysis/
    uv run python utils/wav_time_frequency.py input.wav \
        --output-prefix analysis/input --max-frequency 8000

Only uncompressed integer PCM WAV files with 8/16/24/32-bit samples are
accepted. Multi-channel audio is averaged to mono before analysis.
"""

from __future__ import annotations

import argparse
import csv
import math
import pathlib
import sys
import wave
from dataclasses import dataclass
from typing import Optional

import matplotlib

# A non-interactive backend makes the tool work in terminals and CI.
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from numpy.typing import NDArray


DB_FLOOR = -300.0


@dataclass(frozen=True)
class WavData:
    samples: NDArray[np.float64]
    sample_rate: int
    channels: int
    sample_width: int


@dataclass(frozen=True)
class Spectrogram:
    times: NDArray[np.float64]
    frequencies: NDArray[np.float64]
    level_dbfs: NDArray[np.float64]
    frame_length: int
    hop_length: int
    fft_length: int
    sample_rate: int


def _decode_pcm(raw: bytes, sample_width: int) -> NDArray[np.float64]:
    """Decode little-endian integer PCM samples and normalize them to [-1, 1)."""
    if sample_width == 1:
        values = np.frombuffer(raw, dtype=np.uint8).astype(np.float64)
        return (values - 128.0) / 128.0
    if sample_width == 2:
        values = np.frombuffer(raw, dtype="<i2").astype(np.float64)
        return values / 32768.0
    if sample_width == 3:
        octets = np.frombuffer(raw, dtype=np.uint8)
        if octets.size % 3:
            raise ValueError("24-bit PCM data has an incomplete sample")
        triples = octets.reshape(-1, 3).astype(np.int32)
        values = triples[:, 0] | (triples[:, 1] << 8) | (triples[:, 2] << 16)
        values = np.where(values & 0x800000, values - 0x1000000, values)
        return values.astype(np.float64) / 8388608.0
    if sample_width == 4:
        values = np.frombuffer(raw, dtype="<i4").astype(np.float64)
        return values / 2147483648.0
    raise ValueError(f"unsupported PCM sample width: {sample_width * 8} bit")


def read_pcm_wav(path: pathlib.Path) -> WavData:
    """Read an uncompressed integer PCM WAV and mix all channels to mono."""
    try:
        with wave.open(str(path), "rb") as wav_file:
            if wav_file.getcomptype() != "NONE":
                raise ValueError("only uncompressed PCM WAV files are supported")
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            sample_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
            raw = wav_file.readframes(frame_count)
    except (wave.Error, EOFError) as error:
        raise ValueError(f"invalid or unsupported WAV file: {error}") from error

    if channels < 1 or sample_rate < 1:
        raise ValueError("WAV channel count and sample rate must be positive")

    decoded = _decode_pcm(raw, sample_width)
    if decoded.size == 0:
        raise ValueError("WAV file contains no audio samples")
    if decoded.size % channels:
        raise ValueError("WAV data ends with an incomplete audio frame")

    frames = decoded.reshape(-1, channels)
    mono = frames.mean(axis=1, dtype=np.float64)
    return WavData(mono, sample_rate, channels, sample_width)


def calculate_spectrogram(
    samples: NDArray[np.float64],
    sample_rate: int,
    window_ms: float,
    hop_ms: float,
) -> Spectrogram:
    """Calculate a single-sided Hann-window STFT with levels in dBFS."""
    if samples.ndim != 1 or samples.size == 0:
        raise ValueError("audio samples must be a non-empty one-dimensional array")
    if sample_rate < 1:
        raise ValueError("sample rate must be positive")
    if window_ms <= 0 or hop_ms <= 0:
        raise ValueError("window and hop durations must be positive")

    frame_length = max(16, round(sample_rate * window_ms / 1000.0))
    hop_length = max(1, round(sample_rate * hop_ms / 1000.0))
    fft_length = 1 << math.ceil(math.log2(frame_length))

    if samples.size <= frame_length:
        starts = np.array([0], dtype=np.int64)
    else:
        starts = np.arange(0, samples.size - frame_length + 1, hop_length)
        final_start = samples.size - frame_length
        if starts[-1] != final_start:
            starts = np.append(starts, final_start)

    window = np.hanning(frame_length)
    coherent_gain = window.sum()
    spectra = np.empty((fft_length // 2 + 1, starts.size), dtype=np.float64)

    for column, start in enumerate(starts):
        frame = np.zeros(frame_length, dtype=np.float64)
        available = min(frame_length, samples.size - start)
        frame[:available] = samples[start : start + available]
        magnitude = np.abs(np.fft.rfft(frame * window, n=fft_length)) / coherent_gain
        # Convert the two-sided transform to single-sided peak amplitude. DC and
        # the Nyquist bin do not have mirrored negative-frequency counterparts.
        if magnitude.size > 2:
            magnitude[1:-1] *= 2.0
        spectra[:, column] = magnitude

    level_dbfs = 20.0 * np.log10(np.maximum(spectra, 10.0 ** (DB_FLOOR / 20.0)))
    frequencies = np.fft.rfftfreq(fft_length, d=1.0 / sample_rate)
    times = np.minimum(
        (starts.astype(np.float64) + frame_length / 2.0) / sample_rate,
        samples.size / sample_rate,
    )
    return Spectrogram(
        times=times,
        frequencies=frequencies,
        level_dbfs=level_dbfs,
        frame_length=frame_length,
        hop_length=hop_length,
        fft_length=fft_length,
        sample_rate=sample_rate,
    )


def select_frequency_range(
    spectrogram: Spectrogram,
    min_frequency: float,
    max_frequency: float | None,
) -> Spectrogram:
    nyquist = float(spectrogram.frequencies[-1])
    upper = nyquist if max_frequency is None else max_frequency
    if min_frequency < 0 or upper <= min_frequency or upper > nyquist:
        raise ValueError(
            f"frequency range must satisfy 0 <= min < max <= {nyquist:g} Hz"
        )
    selected = (spectrogram.frequencies >= min_frequency) & (
        spectrogram.frequencies <= upper
    )
    if not np.any(selected):
        raise ValueError("selected frequency range contains no FFT bins")
    return Spectrogram(
        times=spectrogram.times,
        frequencies=spectrogram.frequencies[selected],
        level_dbfs=spectrogram.level_dbfs[selected, :],
        frame_length=spectrogram.frame_length,
        hop_length=spectrogram.hop_length,
        fft_length=spectrogram.fft_length,
        sample_rate=spectrogram.sample_rate,
    )


def _centers_to_edges(
    centers: NDArray[np.float64], default_spacing: float
) -> NDArray[np.float64]:
    if centers.size == 1:
        half_spacing = default_spacing / 2.0
        return np.array([centers[0] - half_spacing, centers[0] + half_spacing])
    midpoints = (centers[:-1] + centers[1:]) / 2.0
    first = centers[0] - (midpoints[0] - centers[0])
    last = centers[-1] + (centers[-1] - midpoints[-1])
    return np.concatenate(([first], midpoints, [last]))


def write_csv(path: pathlib.Path, spectrogram: Spectrogram) -> None:
    """Write tidy/long-form time-frequency-level data."""
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.writer(output_file)
        writer.writerow(("time_s", "frequency_hz", "intensity_dbfs"))
        for column, time_s in enumerate(spectrogram.times):
            for row, frequency_hz in enumerate(spectrogram.frequencies):
                writer.writerow(
                    (
                        f"{time_s:.9g}",
                        f"{frequency_hz:.9g}",
                        f"{spectrogram.level_dbfs[row, column]:.6f}",
                    )
                )


def write_plot(
    path: pathlib.Path,
    source_name: str,
    spectrogram: Spectrogram,
    dynamic_range_db: float,
    dpi: int,
) -> None:
    if dynamic_range_db <= 0:
        raise ValueError("dynamic range must be positive")
    if dpi < 50:
        raise ValueError("DPI must be at least 50")

    peak_dbfs = float(np.max(spectrogram.level_dbfs))
    time_spacing = spectrogram.hop_length / spectrogram.sample_rate
    frequency_spacing = (
        float(spectrogram.frequencies[1] - spectrogram.frequencies[0])
        if spectrogram.frequencies.size > 1
        else 1.0
    )
    time_edges = _centers_to_edges(spectrogram.times, time_spacing)
    frequency_edges = _centers_to_edges(spectrogram.frequencies, frequency_spacing)

    figure, axis = plt.subplots(figsize=(12, 6), constrained_layout=True)
    image = axis.pcolormesh(
        time_edges,
        frequency_edges,
        spectrogram.level_dbfs,
        shading="flat",
        cmap="magma",
        vmin=max(DB_FLOOR, peak_dbfs - dynamic_range_db),
        vmax=peak_dbfs,
        rasterized=True,
    )
    axis.set_title(f"Time-frequency intensity: {source_name}")
    axis.set_xlabel("Time (s)")
    axis.set_ylabel("Frequency (Hz)")
    axis.set_xlim(max(0.0, float(time_edges[0])), float(time_edges[-1]))
    axis.set_ylim(max(0.0, float(frequency_edges[0])), float(frequency_edges[-1]))
    colorbar = figure.colorbar(image, ax=axis)
    colorbar.set_label("Intensity level (dBFS)")
    figure.savefig(path, dpi=dpi)
    plt.close(figure)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate PNG and CSV time-frequency-intensity data from PCM WAV files."
        )
    )
    parser.add_argument(
        "input_wav",
        nargs="+",
        type=pathlib.Path,
        help="one or more input PCM WAV files or directories",
    )
    parser.add_argument(
        "--output-prefix",
        type=pathlib.Path,
        help="output path without extension (single input file only)",
    )
    parser.add_argument(
        "--output-dir",
        type=pathlib.Path,
        help="directory for all output files (default: beside each input WAV)",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="recursively find WAV files in input directories",
    )
    parser.add_argument(
        "--window-ms",
        type=float,
        default=40.0,
        help="STFT Hann-window length in milliseconds (default: 40)",
    )
    parser.add_argument(
        "--hop-ms",
        type=float,
        default=10.0,
        help="time step between STFT frames in milliseconds (default: 10)",
    )
    parser.add_argument(
        "--min-frequency",
        type=float,
        default=0.0,
        help="lowest plotted/exported frequency in Hz (default: 0)",
    )
    parser.add_argument(
        "--max-frequency",
        type=float,
        help="highest plotted/exported frequency in Hz (default: Nyquist)",
    )
    parser.add_argument(
        "--dynamic-range-db",
        type=float,
        default=80.0,
        help="spectrogram color range below its peak in dB (default: 80)",
    )
    parser.add_argument("--dpi", type=int, default=180, help="PNG resolution (default: 180)")
    parser.add_argument(
        "--no-csv", action="store_true", help="create only the PNG spectrogram"
    )
    return parser


AnalysisResult = tuple[pathlib.Path, Optional[pathlib.Path], WavData, Spectrogram]


def collect_input_wavs(
    input_paths: list[pathlib.Path], recursive: bool
) -> list[pathlib.Path]:
    """Resolve files and expand directories into a stable, de-duplicated WAV list."""
    wav_paths: list[pathlib.Path] = []
    seen: set[pathlib.Path] = set()

    for supplied_path in input_paths:
        path = supplied_path.expanduser().resolve()
        if path.is_file():
            candidates = [path]
        elif path.is_dir():
            iterator = path.rglob("*") if recursive else path.iterdir()
            candidates = sorted(
                (
                    candidate.resolve()
                    for candidate in iterator
                    if candidate.is_file() and candidate.suffix.lower() == ".wav"
                ),
                key=lambda candidate: str(candidate).lower(),
            )
            if not candidates:
                scope = "recursively " if recursive else ""
                raise ValueError(f"no WAV files found {scope}in directory: {path}")
        else:
            raise ValueError(f"input WAV or directory does not exist: {path}")

        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                wav_paths.append(candidate)

    return wav_paths


def build_output_prefixes(
    input_paths: list[pathlib.Path], args: argparse.Namespace
) -> list[pathlib.Path]:
    """Choose one output prefix per input and reject ambiguous overwrites."""
    if args.output_prefix is not None and args.output_dir is not None:
        raise ValueError("--output-prefix and --output-dir cannot be used together")
    if args.output_prefix is not None:
        if len(input_paths) != 1:
            raise ValueError("--output-prefix can only be used with one input WAV")
        return [args.output_prefix.expanduser().resolve()]

    output_dir = (
        args.output_dir.expanduser().resolve()
        if args.output_dir is not None
        else None
    )
    prefixes = [
        (output_dir if output_dir is not None else path.parent)
        / f"{path.stem}_time_frequency"
        for path in input_paths
    ]
    if len(set(prefixes)) != len(prefixes):
        raise ValueError(
            "multiple inputs would produce the same name in --output-dir; "
            "rename the files or process them separately"
        )
    return prefixes


def run(
    args: argparse.Namespace,
    input_path: pathlib.Path | None = None,
    output_prefix: pathlib.Path | None = None,
) -> AnalysisResult:
    """Analyze one WAV file.

    ``input_path`` and ``output_prefix`` are supplied by batch mode. Omitting
    them keeps programmatic use with the former single-file Namespace working.
    """
    if input_path is None:
        supplied_input = args.input_wav
        if isinstance(supplied_input, list):
            if len(supplied_input) != 1:
                raise ValueError("run() analyzes one file at a time")
            supplied_input = supplied_input[0]
        input_path = supplied_input.expanduser().resolve()
    else:
        input_path = input_path.expanduser().resolve()

    if not input_path.is_file():
        raise ValueError(f"input WAV does not exist: {input_path}")

    if output_prefix is None:
        output_prefix = (
            args.output_prefix.expanduser().resolve()
            if args.output_prefix is not None
            else input_path.with_name(f"{input_path.stem}_time_frequency")
        )
    output_prefix.parent.mkdir(parents=True, exist_ok=True)

    wav_data = read_pcm_wav(input_path)
    spectrogram = calculate_spectrogram(
        wav_data.samples, wav_data.sample_rate, args.window_ms, args.hop_ms
    )
    spectrogram = select_frequency_range(
        spectrogram, args.min_frequency, args.max_frequency
    )

    png_path = output_prefix.with_suffix(".png")
    csv_path = None if args.no_csv else output_prefix.with_suffix(".csv")
    write_plot(
        png_path,
        input_path.name,
        spectrogram,
        args.dynamic_range_db,
        args.dpi,
    )
    if csv_path is not None:
        write_csv(csv_path, spectrogram)
    return png_path, csv_path, wav_data, spectrogram


def print_result(
    input_path: pathlib.Path,
    result: AnalysisResult,
    item_number: int,
    item_count: int,
) -> None:
    png_path, csv_path, wav_data, spectrogram = result
    duration = wav_data.samples.size / wav_data.sample_rate
    frequency_resolution = wav_data.sample_rate / spectrogram.fft_length
    if item_count > 1:
        print(f"[{item_number}/{item_count}] {input_path}")
    print(
        f"Analyzed {duration:.3f} s, {wav_data.sample_rate} Hz, "
        f"{wav_data.channels} channel(s), {wav_data.sample_width * 8}-bit PCM"
    )
    print(
        f"STFT: {spectrogram.frame_length} samples/window, "
        f"{spectrogram.hop_length} samples/hop, "
        f"{frequency_resolution:.3f} Hz/bin"
    )
    print(f"PNG: {png_path}")
    if csv_path is not None:
        print(f"CSV: {csv_path}")


def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()
    try:
        input_paths = collect_input_wavs(args.input_wav, args.recursive)
        output_prefixes = build_output_prefixes(input_paths, args)
    except (OSError, ValueError) as error:
        parser.exit(2, f"error: {error}\n")

    failures: list[tuple[pathlib.Path, str]] = []
    for item_number, (input_path, output_prefix) in enumerate(
        zip(input_paths, output_prefixes), start=1
    ):
        try:
            result = run(args, input_path, output_prefix)
        except (OSError, ValueError) as error:
            failures.append((input_path, str(error)))
            print(
                f"[{item_number}/{len(input_paths)}] Failed: {input_path}: {error}",
                file=sys.stderr,
            )
            continue
        print_result(input_path, result, item_number, len(input_paths))

    succeeded = len(input_paths) - len(failures)
    if len(input_paths) > 1:
        print(
            f"Batch complete: {succeeded} succeeded, {len(failures)} failed, "
            f"{len(input_paths)} total"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
