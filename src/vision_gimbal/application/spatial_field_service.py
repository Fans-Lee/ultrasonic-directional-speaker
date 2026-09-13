"""Single-slot background worker for optional depth and acoustic-field analysis."""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol

import cv2
import numpy as np
from numpy.typing import NDArray

from ..application.latest_snapshot import LatestSnapshotStore
from ..config.schema import SpatialFieldConfig
from ..domain.spatial_field import SpatialFieldSnapshot, empty_spatial_map
from ..domain.tracking import VisionSnapshot
from ..spatial.field import RelativeFreeFieldModel
from ..spatial.temporal import TemporalDepthStabilizer


class DepthEstimator(Protocol):
    def estimate(self, image: Any) -> NDArray[np.float32]: ...


@dataclass(frozen=True)
class _Submission:
    image: Any
    vision: VisionSnapshot


class SpatialFieldService:
    """Analyze occasional frames without queueing work in the main vision loop."""

    def __init__(
        self,
        config: SpatialFieldConfig,
        estimator: DepthEstimator,
        field_model: RelativeFreeFieldModel,
        snapshots: LatestSnapshotStore[SpatialFieldSnapshot] | None = None,
        now=time.monotonic,
    ) -> None:
        self.config = config
        self.estimator = estimator
        self.field_model = field_model
        self._temporal = TemporalDepthStabilizer(config.depth.temporal)
        self.snapshots = snapshots or LatestSnapshotStore()
        self._now = now
        self._queue: queue.Queue[_Submission | None] = queue.Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._next_submit_at = 0.0
        self._sequence = 0
        self._dropped_frames = 0
        self._consecutive_overruns = 0
        self._active = False
        self._status = "已禁用" if not config.enabled else "等待深度模型"

    @property
    def refresh_hz(self) -> float:
        return self.config.refresh_hz

    def start(self) -> None:
        if not self.config.enabled:
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._temporal.reset()
            self._thread = threading.Thread(
                target=self._run,
                name="spatial-field",
                daemon=True,
            )
            self._thread.start()

    def submit(self, image: Any, vision: VisionSnapshot) -> None:
        """Offer one immutable camera frame without ever waiting for analysis."""
        if not self.config.enabled or self._stop_event.is_set():
            return
        now = self._now()
        if not self._lock.acquire(blocking=False):
            return
        try:
            if now < self._next_submit_at:
                return
            self._next_submit_at = now + self.config.interval_s
        finally:
            self._lock.release()
        submission = _Submission(image=image, vision=vision)
        try:
            self._queue.put_nowait(submission)
            return
        except queue.Full:
            pass
        try:
            self._queue.get_nowait()
            self._increment_dropped_nonblocking()
        except queue.Empty:
            return
        try:
            self._queue.put_nowait(submission)
        except queue.Full:
            self._increment_dropped_nonblocking()

    def snapshot(self) -> SpatialFieldSnapshot | None:
        snapshot = self.snapshots.get()
        if snapshot is None:
            return None
        if self._now() - snapshot.completed_at > self.config.result_ttl_s:
            return None
        return snapshot

    def close(self) -> None:
        if not self.config.enabled:
            return
        self._stop_event.set()
        self._enqueue_stop()
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        with self._lock:
            self._thread = None
            self._active = False
        self._clear_queue()
        self.snapshots.clear()
        self._temporal.reset()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                submission = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if submission is None:
                return
            self._analyze(submission)

    def _analyze(self, submission: _Submission) -> None:
        started_at = self._now()
        source_frame = None
        try:
            source_frame = np.ascontiguousarray(submission.image).copy()
            depth_full = self.estimator.estimate(source_frame)
            depth = self._downsample_depth(depth_full, submission.vision.frame_size)
            depth = self._temporal.update(depth, submission.vision.captured_at)
            intensity = self.field_model.evaluate(depth, submission.vision.frame_size)
            completed_at = self._now()
            elapsed_ms = (completed_at - started_at) * 1000.0
            with self._lock:
                if elapsed_ms > self.config.max_inference_ms:
                    self._consecutive_overruns += 1
                else:
                    self._consecutive_overruns = 0
                self._sequence += 1
                sequence = self._sequence
                dropped = self._dropped_frames
                self._active = self._consecutive_overruns < self.config.max_consecutive_overruns
                if not self._active:
                    self._status = "性能预算超限，附加分析已暂停"
                    self._stop_event.set()
                else:
                    self._status = "运行中"
            self.snapshots.set(
                SpatialFieldSnapshot(
                    sequence=sequence,
                    frame_id=submission.vision.frame_id,
                    captured_at=submission.vision.captured_at,
                    completed_at=completed_at,
                    source_size=submission.vision.frame_size,
                    depth_m=depth,
                    intensity_db_relative=intensity,
                    inference_ms=elapsed_ms,
                    dropped_frames=dropped,
                    active=self._active,
                    status=self._status,
                    display_floor_db=self.config.acoustics.display_floor_db,
                    overlay_opacity=self.config.acoustics.overlay_opacity,
                    source_frame_bgr=source_frame,
                )
            )
        except Exception as error:  # noqa: BLE001 - optional worker boundary
            completed_at = self._now()
            with self._lock:
                self._sequence += 1
                self._active = False
                self._status = f"分析不可用：{error}"
                self._stop_event.set()
                sequence = self._sequence
                dropped = self._dropped_frames
            self.snapshots.set(
                SpatialFieldSnapshot(
                    sequence=sequence,
                    frame_id=submission.vision.frame_id,
                    captured_at=submission.vision.captured_at,
                    completed_at=completed_at,
                    source_size=submission.vision.frame_size,
                    depth_m=empty_spatial_map(),
                    intensity_db_relative=empty_spatial_map(),
                    inference_ms=(completed_at - started_at) * 1000.0,
                    dropped_frames=dropped,
                    active=False,
                    status=self._status,
                    display_floor_db=self.config.acoustics.display_floor_db,
                    overlay_opacity=self.config.acoustics.overlay_opacity,
                    source_frame_bgr=source_frame,
                )
            )

    def _downsample_depth(
        self,
        depth_full: NDArray[np.float32],
        source_size: tuple[int, int],
    ) -> NDArray[np.float32]:
        depth = np.asarray(depth_full, dtype=np.float32)
        if depth.ndim != 2 or depth.size == 0:
            raise ValueError("depth estimator returned an invalid map")
        source_width, source_height = source_size
        if source_width <= 0 or source_height <= 0:
            raise ValueError("source frame dimensions must be positive")
        target_width = min(self.config.depth.input_width, source_width)
        target_height = max(1, round(target_width * source_height / source_width))
        if depth.shape == (target_height, target_width):
            return depth.copy()
        return cv2.resize(depth, (target_width, target_height), interpolation=cv2.INTER_AREA)

    def _clear_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    def _increment_dropped_nonblocking(self) -> None:
        if not self._lock.acquire(blocking=False):
            return
        try:
            self._dropped_frames += 1
        finally:
            self._lock.release()

    def _enqueue_stop(self) -> None:
        try:
            self._queue.put_nowait(None)
            return
        except queue.Full:
            pass
        try:
            self._queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
