#!/usr/bin/env python3
"""注意：该脚本的平方反比关系是理论分析的结果，在未经过实测前不应当直接使用"""
"""Pre-compensate a PCM WAV for a device whose amplitude response is f squared.

If the device response is

    H(f) = (f / reference_frequency) ** 2,

this script applies the regularized inverse

    G(f) = (reference_frequency**2 + regularization_frequency**2)
           / (f**2 + regularization_frequency**2).

Consequently, ``H(f) * G(f)`` is approximately one above the regularization
frequency and is exactly one at the reference frequency.  Regularization is
necessary because an exact inverse is unbounded at 0 Hz.  DC is removed.

Run from the project root with uv:

    uv run python utils/wav_frequency_squared_compensation.py input.wav
    uv run python utils/wav_frequency_squared_compensation.py \
        input.wav output.wav --reference-frequency 1000 --regularization-frequency 20

Only uncompressed integer PCM WAV files with 8/16/24/32-bit samples are
accepted.  The output keeps the input sample rate, channel count, and bit depth.
Each channel is filtered independently, and one common gain is then applied to
all channels to preserve their relative levels while preventing clipping.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import wave
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class WavData:
    """Decoded interleaved PCM audio represented as frames x channels."""

    samples: NDArray[np.float64]
    sample_rate: int
    sample_width: int

    @property
    def channels(self) -> int:
        return self.samples.shape[1]

    @property
    def frame_count(self) -> int:
        return self.samples.shape[0]


@dataclass(frozen=True)
class ProcessingResult:
    """Information useful for displaying and testing a conversion."""

    samples: NDArray[np.float64]
    unnormalized_peak: float
    normalization_gain: float


def _decode_pcm(raw: bytes, sample_width: int) -> NDArray[np.float64]:
    """Decode little-endian integer PCM samples to the range [-1, 1)."""
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


def _encode_pcm(samples: NDArray[np.float64], sample_width: int) -> bytes:
    """Encode frames x channels floating-point audio as integer PCM."""
    flat = np.clip(samples.reshape(-1), -1.0, 1.0)

    if sample_width == 1:
        values = np.clip(np.rint(flat * 128.0 + 128.0), 0, 255).astype(np.uint8)
        return values.tobytes()

    scale = float(1 << (sample_width * 8 - 1))
    minimum = -(1 << (sample_width * 8 - 1))
    maximum = (1 << (sample_width * 8 - 1)) - 1
    values = np.clip(np.rint(flat * scale), minimum, maximum).astype(np.int64)

    if sample_width == 2:
        return values.astype("<i2").tobytes()
    if sample_width == 3:
        packed = np.empty((values.size, 3), dtype=np.uint8)
        packed[:, 0] = values & 0xFF
        packed[:, 1] = (values >> 8) & 0xFF
        packed[:, 2] = (values >> 16) & 0xFF
        return packed.tobytes()
    if sample_width == 4:
        return values.astype("<i4").tobytes()
    raise ValueError(f"unsupported PCM sample width: {sample_width * 8} bit")


def read_pcm_wav(path: pathlib.Path) -> WavData:
    """Read an uncompressed 8/16/24/32-bit integer PCM WAV."""
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
    return WavData(decoded.reshape(-1, channels), sample_rate, sample_width)


def write_pcm_wav(path: pathlib.Path, wav_data: WavData) -> None:
    """Write a WavData object as an uncompressed integer PCM WAV."""
    raw = _encode_pcm(wav_data.samples, wav_data.sample_width)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(wav_data.channels)
        wav_file.setsampwidth(wav_data.sample_width)
        wav_file.setframerate(wav_data.sample_rate)
        wav_file.writeframes(raw)


def make_compensation_curve(
    frequencies: NDArray[np.float64],
    reference_frequency: float,
    regularization_frequency: float,
) -> NDArray[np.float64]:
    """Return the stable inverse-f-squared amplitude curve for FFT bins."""
    if reference_frequency <= 0:
        raise ValueError("reference frequency must be positive")
    if regularization_frequency <= 0:
        raise ValueError("regularization frequency must be positive")

    numerator = reference_frequency**2 + regularization_frequency**2
    curve = numerator / (frequencies**2 + regularization_frequency**2)
    # The device cannot reproduce DC because H(0) is zero.  Removing it also
    # prevents an input offset from consuming nearly all available headroom.
    curve[frequencies == 0.0] = 0.0
    return curve


def compensate_frequency_squared_response(
    samples: NDArray[np.float64],
    sample_rate: int,
    reference_frequency: float = 1000.0,
    regularization_frequency: float = 20.0,
    target_peak: float = 0.95,
    padding_ms: float = 250.0,
) -> ProcessingResult:
    """Apply regularized inverse-f-squared compensation to every channel."""
    if samples.ndim != 2 or samples.shape[0] == 0 or samples.shape[1] == 0:
        raise ValueError("samples must be a non-empty frames x channels array")
    if not np.all(np.isfinite(samples)):
        raise ValueError("samples contain NaN or infinity")
    if sample_rate < 1:
        raise ValueError("sample rate must be positive")
    nyquist = sample_rate / 2.0
    if not 0.0 < reference_frequency <= nyquist:
        raise ValueError(
            f"reference frequency must satisfy 0 < frequency <= {nyquist:g} Hz"
        )
    if not 0.0 < regularization_frequency < nyquist:
        raise ValueError(
            f"regularization frequency must satisfy 0 < frequency < {nyquist:g} Hz"
        )
    if not 0.0 < target_peak <= 1.0:
        raise ValueError("target peak must satisfy 0 < peak <= 1")
    if padding_ms < 0.0:
        raise ValueError("padding duration cannot be negative")

    # Work on a copy so callers retain their original decoded audio.  Removing
    # the mean makes the intentional DC rejection exact even with finite data.
    centered = samples.astype(np.float64, copy=True)
    centered -= centered.mean(axis=0, keepdims=True)

    requested_padding = round(sample_rate * padding_ms / 1000.0)
    padding = min(requested_padding, max(0, centered.shape[0] - 1))
    if padding:
        padded = np.pad(centered, ((padding, padding), (0, 0)), mode="reflect")
    else:
        padded = centered

    frequencies = np.fft.rfftfreq(padded.shape[0], d=1.0 / sample_rate)
    compensation = make_compensation_curve(
        frequencies, reference_frequency, regularization_frequency
    )
    spectrum = np.fft.rfft(padded, axis=0)
    spectrum *= compensation[:, np.newaxis]
    filtered_padded = np.fft.irfft(spectrum, n=padded.shape[0], axis=0)
    filtered = (
        filtered_padded[padding:-padding, :].copy()
        if padding
        else filtered_padded
    )

    unnormalized_peak = float(np.max(np.abs(filtered)))
    if unnormalized_peak > np.finfo(np.float64).eps:
        normalization_gain = target_peak / unnormalized_peak
        filtered *= normalization_gain
    else:
        normalization_gain = 1.0
        filtered.fill(0.0)

    return ProcessingResult(filtered, unnormalized_peak, normalization_gain)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Pre-compensate a PCM WAV for a device whose amplitude response "
            "is proportional to frequency squared."
        )
    )
    parser.add_argument("input_wav", type=pathlib.Path, help="input PCM WAV file")
    parser.add_argument(
        "output_wav",
        type=pathlib.Path,
        nargs="?",
        help="output WAV (default: <input_stem>_inverse_f2.wav)",
    )
    parser.add_argument(
        "--reference-frequency",
        type=float,
        default=1000.0,
        help="frequency in Hz at which compensation gain is 1 (default: 1000)",
    )
    parser.add_argument(
        "--regularization-frequency",
        type=float,
        default=20.0,
        help=(
            "low-frequency stabilization corner in Hz; lower values give a "
            "closer but more noise-sensitive inverse (default: 20)"
        ),
    )
    parser.add_argument(
        "--target-peak",
        type=float,
        default=0.95,
        help="normalized output peak in the range (0, 1] (default: 0.95)",
    )
    parser.add_argument(
        "--padding-ms",
        type=float,
        default=250.0,
        help="reflected edge padding used to reduce FFT boundary artifacts (default: 250)",
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="allow replacing an existing output WAV"
    )
    return parser


def run(args: argparse.Namespace) -> tuple[pathlib.Path, WavData, ProcessingResult]:
    input_path = args.input_wav.expanduser().resolve()
    if not input_path.is_file():
        raise ValueError(f"input WAV does not exist: {input_path}")

    if args.output_wav is None:
        output_path = input_path.with_name(f"{input_path.stem}_inverse_f2.wav")
    else:
        output_path = args.output_wav.expanduser().resolve()
    if output_path.suffix.lower() != ".wav":
        raise ValueError("output filename must end with .wav")
    if output_path == input_path and not args.overwrite:
        raise ValueError("refusing to replace the input; choose another output or use --overwrite")
    if output_path.exists() and not args.overwrite:
        raise ValueError(f"output already exists (use --overwrite): {output_path}")

    wav_data = read_pcm_wav(input_path)
    result = compensate_frequency_squared_response(
        wav_data.samples,
        wav_data.sample_rate,
        reference_frequency=args.reference_frequency,
        regularization_frequency=args.regularization_frequency,
        target_peak=args.target_peak,
        padding_ms=args.padding_ms,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_pcm_wav(
        output_path,
        WavData(result.samples, wav_data.sample_rate, wav_data.sample_width),
    )
    return output_path, wav_data, result


def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()
    try:
        output_path, wav_data, result = run(args)
    except (OSError, ValueError) as error:
        parser.exit(2, f"error: {error}\n")

    duration = wav_data.frame_count / wav_data.sample_rate
    gain_db = 20.0 * np.log10(result.normalization_gain)
    print(
        f"Processed {duration:.3f} s, {wav_data.sample_rate} Hz, "
        f"{wav_data.channels} channel(s), {wav_data.sample_width * 8}-bit PCM"
    )
    print(
        f"Inverse f^2: reference={args.reference_frequency:g} Hz, "
        f"regularization={args.regularization_frequency:g} Hz"
    )
    print(
        f"Peak before normalization: {result.unnormalized_peak:.6g}; "
        f"normalization gain: {result.normalization_gain:.6g} ({gain_db:+.2f} dB)"
    )
    print(f"WAV: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
