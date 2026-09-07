"""Compose detector/tracker output with per-track smoothing."""

from typing import Any

from ..domain.tracking import VisionSnapshot
from ..ports.people_tracker import PeopleTracker
from .kalman_smoother import PerTrackKalmanSmoother


class VisionPipeline:
    def __init__(
        self,
        tracker: PeopleTracker,
        smoother: PerTrackKalmanSmoother,
    ) -> None:
        self.tracker = tracker
        self.smoother = smoother
        self._last_timestamp = None

    def process(
        self,
        frame: Any,
        frame_id: int,
        captured_at: float,
    ) -> VisionSnapshot:
        height, width = frame.shape[:2]
        dt_s = 1.0 / 30.0
        if self._last_timestamp is not None:
            dt_s = captured_at - self._last_timestamp
        self._last_timestamp = captured_at
        observed = self.tracker.update(frame)
        tracks = tuple(self.smoother.update(observed, dt_s))
        return VisionSnapshot(
            frame_id=frame_id,
            captured_at=captured_at,
            frame_size=(width, height),
            tracks=tracks,
        )

    def reset(self) -> None:
        self._last_timestamp = None
        self.tracker.reset()
        self.smoother.reset()
