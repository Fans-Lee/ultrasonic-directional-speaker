"""Stateful speech leveler, compressor, and final peak limiter."""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray


def _db_to_gain(value_db: float) -> float:
    return 10.0 ** (value_db / 20.0)


class SlowLeveler:
    def __init__(
        self,
        sample_rate: int,
        target_dbfs: float,
        maximum_gain_db: float,
        attack_ms: float,
        release_ms: float,
        freeze_below_dbfs: float,
    ) -> None:
        self.sample_rate = sample_rate
        self.target_dbfs = target_dbfs
        self.maximum_gain_db = maximum_gain_db
        self.attack_ms = attack_ms
        self.release_ms = release_ms
        self.freeze_below_dbfs = freeze_below_dbfs
        self._gain_db = 0.0

    def reset(self) -> None:
        self._gain_db = 0.0

    def process(self, samples: NDArray[np.float32]) -> NDArray[np.float32]:
        if samples.size == 0:
            return samples.copy()
        rms = math.sqrt(float(np.mean(np.square(samples, dtype=np.float64))))
        input_dbfs = 20.0 * math.log10(max(rms, 1.0e-9))
        if input_dbfs > self.freeze_below_dbfs:
            desired_db = min(self.maximum_gain_db, self.target_dbfs - input_dbfs)
            duration_s = samples.size / self.sample_rate
            time_ms = self.attack_ms if desired_db < self._gain_db else self.release_ms
            smoothing = math.exp(-duration_s / (time_ms / 1000.0))
            self._gain_db = smoothing * self._gain_db + (1.0 - smoothing) * desired_db
        return (samples * _db_to_gain(self._gain_db)).astype(np.float32)


class CompressorLimiter:
    def __init__(
        self,
        sample_rate: int,
        threshold_dbfs: float,
        ratio: float,
        attack_ms: float,
        release_ms: float,
        limiter_ceiling_dbfs: float,
    ) -> None:
        self.threshold_dbfs = threshold_dbfs
        self.ratio = ratio
        self._attack = math.exp(-1.0 / (sample_rate * attack_ms / 1000.0))
        self._release = math.exp(-1.0 / (sample_rate * release_ms / 1000.0))
        self._ceiling = _db_to_gain(limiter_ceiling_dbfs)
        self._envelope = 0.0

    def reset(self) -> None:
        self._envelope = 0.0

    def process(self, samples: NDArray[np.float32]) -> NDArray[np.float32]:
        output = np.empty(samples.size, dtype=np.float32)
        envelope = self._envelope
        for index, sample in enumerate(samples):
            magnitude = abs(float(sample))
            coefficient = self._attack if magnitude > envelope else self._release
            envelope = coefficient * envelope + (1.0 - coefficient) * magnitude
            envelope_db = 20.0 * math.log10(max(envelope, 1.0e-9))
            gain_db = 0.0
            if envelope_db > self.threshold_dbfs:
                compressed_db = (
                    self.threshold_dbfs
                    + (envelope_db - self.threshold_dbfs) / self.ratio
                )
                gain_db = compressed_db - envelope_db
            output[index] = float(sample) * _db_to_gain(gain_db)
        self._envelope = envelope
        return np.clip(output, -self._ceiling, self._ceiling).astype(np.float32)
