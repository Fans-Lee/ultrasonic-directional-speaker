"""Slow buffer-watermark controller for independent audio clocks."""

from __future__ import annotations

import time


class BufferClockSync:
    """Return a bounded output-rate reduction in parts per million.

    Positive correction means the device buffer is too full and the host must
    produce slightly fewer samples.  The small correction is applied by the
    streaming resampler, never by replaying stale packets.
    """

    def __init__(
        self,
        target_fill_samples: int,
        proportional_ppm: float = 400.0,
        integral_ppm_per_s: float = 40.0,
        maximum_ppm: float = 500.0,
    ) -> None:
        self.target_fill_samples = target_fill_samples
        self.proportional_ppm = proportional_ppm
        self.integral_ppm_per_s = integral_ppm_per_s
        self.maximum_ppm = maximum_ppm
        self._integral = 0.0
        self._last_update = time.monotonic()

    def reset(self) -> None:
        self._integral = 0.0
        self._last_update = time.monotonic()

    def update(self, fill_samples: int, capacity_samples: int) -> float:
        if capacity_samples <= 0:
            self.reset()
            return 0.0
        now = time.monotonic()
        elapsed = min(1.0, max(0.0, now - self._last_update))
        self._last_update = now
        error = (fill_samples - self.target_fill_samples) / capacity_samples
        self._integral += error * elapsed
        correction = (
            self.proportional_ppm * error + self.integral_ppm_per_s * self._integral
        )
        if correction > self.maximum_ppm:
            correction = self.maximum_ppm
            self._integral *= 0.9
        elif correction < -self.maximum_ppm:
            correction = -self.maximum_ppm
            self._integral *= 0.9
        return correction
