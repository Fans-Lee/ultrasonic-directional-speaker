"""Continuous fractional-position downsampler for pre-filtered audio."""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray


class StreamingLinearResampler:
    """Linearly sample an already anti-aliased stream at a new clock rate.

    The low-pass filter is deliberately separate so its attenuation and state
    can be tested independently.  This object only performs continuous-time
    position tracking and interpolation across arbitrary input block edges.
    """

    def __init__(self, source_rate: int, target_rate: int) -> None:
        if source_rate <= 0 or target_rate <= 0 or target_rate > source_rate:
            raise ValueError("resampler requires 0 < target_rate <= source_rate")
        self.source_rate = source_rate
        self.target_rate = target_rate
        self._rate_correction_ppm = 0.0
        self._step = source_rate / target_rate
        self._buffer = np.empty(0, dtype=np.float32)
        self._position = 0.0

    def reset(self) -> None:
        self._buffer = np.empty(0, dtype=np.float32)
        self._position = 0.0

    def set_rate_correction_ppm(self, correction_ppm: float) -> None:
        if not -1000.0 <= correction_ppm <= 1000.0:
            raise ValueError("resampler clock correction exceeds safe range")
        self._rate_correction_ppm = correction_ppm
        corrected_target_rate = self.target_rate * (1.0 - correction_ppm / 1.0e6)
        self._step = self.source_rate / corrected_target_rate

    def process(self, samples: NDArray[np.float32]) -> NDArray[np.float32]:
        incoming = np.asarray(samples, dtype=np.float32).reshape(-1)
        if incoming.size:
            self._buffer = np.concatenate((self._buffer, incoming))
        output: list[float] = []
        while math.floor(self._position) + 1 < self._buffer.size:
            left = math.floor(self._position)
            fraction = self._position - left
            value = (
                float(self._buffer[left]) * (1.0 - fraction)
                + float(self._buffer[left + 1]) * fraction
            )
            output.append(value)
            self._position += self._step

        discard = min(math.floor(self._position), self._buffer.size)
        if discard:
            self._buffer = self._buffer[discard:].copy()
            self._position -= discard
        return np.asarray(output, dtype=np.float32)
