"""Small stateful biquad filters used by the live speech path."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class BiquadCoefficients:
    b0: float
    b1: float
    b2: float
    a1: float
    a2: float


class Biquad:
    """Direct-form-II-transposed biquad with block-persistent state."""

    def __init__(self, coefficients: BiquadCoefficients) -> None:
        self.coefficients = coefficients
        self._z1 = 0.0
        self._z2 = 0.0

    def reset(self) -> None:
        self._z1 = 0.0
        self._z2 = 0.0

    def process(self, samples: NDArray[np.float32]) -> NDArray[np.float32]:
        c = self.coefficients
        output = np.empty(samples.size, dtype=np.float32)
        z1 = self._z1
        z2 = self._z2
        for index, sample in enumerate(samples):
            value = c.b0 * float(sample) + z1
            z1 = c.b1 * float(sample) - c.a1 * value + z2
            z2 = c.b2 * float(sample) - c.a2 * value
            output[index] = value
        self._z1 = z1
        self._z2 = z2
        return output


class BiquadCascade:
    def __init__(self, sections: list[BiquadCoefficients]) -> None:
        self._sections = [Biquad(section) for section in sections]

    def reset(self) -> None:
        for section in self._sections:
            section.reset()

    def process(self, samples: NDArray[np.float32]) -> NDArray[np.float32]:
        result = np.asarray(samples, dtype=np.float32)
        for section in self._sections:
            result = section.process(result)
        return result


class StreamingFir:
    """Causal FIR filter that preserves its delay line between blocks."""

    def __init__(self, taps: NDArray[np.float64]) -> None:
        if taps.ndim != 1 or taps.size < 3:
            raise ValueError("FIR taps must be a one-dimensional array")
        self._taps = taps.astype(np.float64, copy=True)
        self._history = np.zeros(self._taps.size - 1, dtype=np.float64)

    @property
    def tap_count(self) -> int:
        return int(self._taps.size)

    def reset(self) -> None:
        self._history.fill(0.0)

    def process(self, samples: NDArray[np.float32]) -> NDArray[np.float32]:
        values = np.asarray(samples, dtype=np.float64).reshape(-1)
        if values.size == 0:
            return np.empty(0, dtype=np.float32)
        combined = np.concatenate((self._history, values))
        convolution = np.convolve(combined, self._taps, mode="full")
        start = self._taps.size - 1
        output = convolution[start : start + values.size]
        self._history = combined[-(self._taps.size - 1) :].copy()
        return output.astype(np.float32)


def _rbj_lowpass(sample_rate: int, cutoff_hz: float, q: float) -> BiquadCoefficients:
    omega = 2.0 * math.pi * cutoff_hz / sample_rate
    cosine = math.cos(omega)
    alpha = math.sin(omega) / (2.0 * q)
    a0 = 1.0 + alpha
    return BiquadCoefficients(
        b0=((1.0 - cosine) / 2.0) / a0,
        b1=(1.0 - cosine) / a0,
        b2=((1.0 - cosine) / 2.0) / a0,
        a1=(-2.0 * cosine) / a0,
        a2=(1.0 - alpha) / a0,
    )


def _rbj_highpass(sample_rate: int, cutoff_hz: float, q: float) -> BiquadCoefficients:
    omega = 2.0 * math.pi * cutoff_hz / sample_rate
    cosine = math.cos(omega)
    alpha = math.sin(omega) / (2.0 * q)
    a0 = 1.0 + alpha
    return BiquadCoefficients(
        b0=((1.0 + cosine) / 2.0) / a0,
        b1=(-(1.0 + cosine)) / a0,
        b2=((1.0 + cosine) / 2.0) / a0,
        a1=(-2.0 * cosine) / a0,
        a2=(1.0 - alpha) / a0,
    )


def speech_highpass(sample_rate: int, cutoff_hz: float) -> BiquadCascade:
    if not 0.0 < cutoff_hz < sample_rate / 2.0:
        raise ValueError("high-pass cutoff must be below Nyquist")
    return BiquadCascade([_rbj_highpass(sample_rate, cutoff_hz, math.sqrt(0.5))])


def antialias_lowpass(
    sample_rate: int, passband_hz: float, stopband_hz: float
) -> StreamingFir:
    """Design a Kaiser-window FIR between the requested pass/stop edges."""

    if not 0.0 < passband_hz < stopband_hz <= sample_rate / 2.0:
        raise ValueError("low-pass edges must satisfy 0 < pass < stop <= Nyquist")
    attenuation_db = 70.0
    transition_radians = 2.0 * math.pi * (stopband_hz - passband_hz) / sample_rate
    tap_count = math.ceil((attenuation_db - 8.0) / (2.285 * transition_radians)) + 1
    if tap_count % 2 == 0:
        tap_count += 1
    tap_count = max(63, tap_count)
    center = (tap_count - 1) / 2.0
    positions = np.arange(tap_count, dtype=np.float64) - center
    design_cutoff = (passband_hz + stopband_hz) / 2.0
    normalized_cutoff = design_cutoff / sample_rate
    taps = 2.0 * normalized_cutoff * np.sinc(2.0 * normalized_cutoff * positions)
    taps *= np.kaiser(tap_count, 6.76)
    taps /= np.sum(taps)
    return StreamingFir(taps)
