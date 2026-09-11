"""Conservative temporal stabilization for low-rate monocular depth maps."""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray

from ..config.schema import SpatialDepthTemporalConfig


class TemporalDepthStabilizer:
    """Stabilize proportional monocular-depth noise without smearing changes.

    The model is intentionally unaware of camera motion. It estimates a global
    log-scale correction only when the overlapping maps are already internally
    consistent, then blends pixels that agree after that correction. Pixels
    with a large residual use the new value immediately, which prevents
    occlusions and moving objects from leaving a trail in the sound-field map.
    """

    def __init__(self, config: SpatialDepthTemporalConfig) -> None:
        self.config = config
        self._previous_depth: NDArray[np.float32] | None = None
        self._previous_at: float | None = None

    def reset(self) -> None:
        self._previous_depth = None
        self._previous_at = None

    def update(
        self,
        depth_m: NDArray[np.float32],
        captured_at: float,
    ) -> NDArray[np.float32]:
        """Return a stabilized copy and remember it as the next-frame prior."""
        depth = np.asarray(depth_m, dtype=np.float32)
        if depth.ndim != 2 or depth.size == 0:
            raise ValueError("depth map must be a non-empty two-dimensional matrix")
        if not math.isfinite(captured_at):
            raise ValueError("depth capture timestamp must be finite")

        current = depth.copy()
        previous = self._previous_depth
        previous_at = self._previous_at
        if (
            not self.config.enabled
            or previous is None
            or previous_at is None
            or previous.shape != current.shape
        ):
            return self._remember(current, captured_at)

        dt_s = captured_at - previous_at
        if not 0.0 < dt_s <= self.config.max_gap_s:
            return self._remember(current, captured_at)

        current_valid = _valid_depth(current)
        previous_valid = _valid_depth(previous)
        overlap = current_valid & previous_valid
        corrected = current.copy()
        log_scale = self._estimate_log_scale(current, previous, overlap)
        if log_scale != 0.0:
            corrected[current_valid] *= math.exp(log_scale)

        corrected_valid = _valid_depth(corrected)
        agreement = corrected_valid & previous_valid
        if np.any(agreement):
            log_ratio = np.zeros(corrected.shape, dtype=np.float32)
            log_ratio[agreement] = np.abs(
                np.log(corrected[agreement]) - np.log(previous[agreement])
            )
            agreement &= log_ratio <= math.log(self.config.pixel_gate_ratio)

        alpha = 1.0 - math.exp(-dt_s / self.config.time_constant_s)
        stabilized = corrected.copy()
        if np.any(agreement):
            stabilized[agreement] = np.exp(
                (1.0 - alpha) * np.log(previous[agreement])
                + alpha * np.log(corrected[agreement])
            ).astype(np.float32)
        return self._remember(stabilized, captured_at)

    def _estimate_log_scale(
        self,
        current: NDArray[np.float32],
        previous: NDArray[np.float32],
        overlap: NDArray[np.bool_],
    ) -> float:
        if not self.config.scale_alignment_enabled:
            return 0.0
        if np.count_nonzero(overlap) / overlap.size < self.config.min_overlap_ratio:
            return 0.0
        residuals = np.log(previous[overlap]) - np.log(current[overlap])
        median = float(np.median(residuals))
        mad = float(np.median(np.abs(residuals - median)))
        if math.exp(mad) > self.config.max_scale_residual_ratio:
            return 0.0
        limit = math.log(self.config.max_scale_correction_ratio)
        return float(np.clip(median, -limit, limit))

    def _remember(
        self,
        depth: NDArray[np.float32],
        captured_at: float,
    ) -> NDArray[np.float32]:
        self._previous_depth = depth.copy()
        self._previous_at = captured_at
        return depth


def _valid_depth(depth: NDArray[np.float32]) -> NDArray[np.bool_]:
    return np.isfinite(depth) & (depth > 0.0)
