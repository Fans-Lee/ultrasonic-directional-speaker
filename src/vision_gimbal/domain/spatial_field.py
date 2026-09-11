"""Immutable contracts for optional depth and relative acoustic-field analysis."""

from __future__ import annotations

from dataclasses import dataclass

from numpy.typing import NDArray
import numpy as np


@dataclass(frozen=True)
class SpatialFieldSnapshot:
    """UI-ready result for one source frame.

    Both matrices intentionally stay at the low analysis resolution. The UI may
    scale them for presentation, while all physical calculations remain bounded.
    ``intensity_db_relative`` is a direct-path simulation, not an SPL reading.
    ``source_frame_bgr`` is a private copy of the exact frame that produced the
    maps, so a delayed result is never overlaid onto a newer camera frame.
    """

    sequence: int
    frame_id: int
    captured_at: float
    completed_at: float
    source_size: tuple[int, int]
    depth_m: NDArray[np.float32]
    intensity_db_relative: NDArray[np.float32]
    inference_ms: float
    dropped_frames: int
    active: bool
    status: str
    display_floor_db: float = -40.0
    overlay_opacity: float = 0.42
    source_frame_bgr: NDArray[np.uint8] | None = None

    @property
    def age_s(self) -> float:
        return max(0.0, self.completed_at - self.captured_at)


def empty_spatial_map(height: int = 1, width: int = 1) -> NDArray[np.float32]:
    """Create a correctly typed unavailable map for error/status snapshots."""
    return np.full((height, width), np.nan, dtype=np.float32)
