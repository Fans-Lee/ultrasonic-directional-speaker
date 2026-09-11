"""Non-blocking real-time spectrogram analysis for transmitted audio."""

from __future__ import annotations

import math
import queue
import threading
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from ..config.schema import AudioSpectrumConfig

_DB_FLOOR = -300.0


@dataclass(frozen=True)
class AudioSpectrumSnapshot:
    """One immutable, UI-ready view of the rolling spectrogram."""

    sequence: int
    active: bool
    sample_rate: int
    frequencies_hz: NDArray[np.float32]
    levels_dbfs: NDArray[np.float32]
    history_s: float
    window_ms: float
    hop_ms: float
    min_dbfs: float
    max_dbfs: float
    latest_peak_dbfs: float | None
    dropped_blocks: int


class RealtimeSpectrumAnalyzer:
    """Analyze copied audio blocks on a bounded background worker.

    ``submit`` never waits for FFT work. When analysis falls behind, queued
    backlog is discarded so that visualization cannot delay audio output.
    """

    def __init__(self, config: AudioSpectrumConfig, sample_rate: int) -> None:
        if sample_rate <= 0:
            raise ValueError("spectrum sample rate must be positive")
        self.config = config
        self.sample_rate = sample_rate
        self.window_length = max(
            16, round(sample_rate * config.window_ms / 1000.0)
        )
        self.hop_length = max(1, round(sample_rate * config.hop_ms / 1000.0))
        if self.hop_length > self.window_length:
            raise ValueError("spectrum hop cannot exceed its window")
        self.fft_length = 1 << math.ceil(math.log2(self.window_length))
        self.column_capacity = max(
            1, math.ceil(config.history_s * sample_rate / self.hop_length)
        )
        self._window = np.hanning(self.window_length).astype(np.float32)
        self._coherent_gain = float(np.sum(self._window))
        self._frequencies = np.fft.rfftfreq(
            self.fft_length, d=1.0 / sample_rate
        ).astype(np.float32)
        self._levels = np.full(
            (self._frequencies.size, self.column_capacity),
            np.nan,
            dtype=np.float32,
        )
        self._pending = np.empty(0, dtype=np.float32)
        self._write_index = 0
        self._column_count = 0
        self._sequence = 0
        self._latest_peak_dbfs: float | None = None

        self._queue: queue.Queue[
            tuple[int, NDArray[np.float32], bool] | None
        ] = queue.Queue(maxsize=config.queue_blocks)
        self._state_lock = threading.Lock()
        self._data_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._generation = 0
        self._active = False
        self._dropped_blocks = 0

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    @property
    def refresh_hz(self) -> float:
        return self.config.refresh_hz

    def start(self) -> None:
        if not self.enabled:
            return
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._active = False
            self._clear_queue()
            self._thread = threading.Thread(
                target=self._run,
                name="audio-spectrum",
                daemon=True,
            )
            self._thread.start()

    def close(self) -> None:
        if not self.enabled:
            return
        self.deactivate()
        self._stop_event.set()
        self._enqueue_stop()
        with self._state_lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        with self._state_lock:
            self._thread = None
        self._clear_queue()

    def activate(self) -> None:
        if not self.enabled:
            return
        self._clear_queue()
        with self._data_lock:
            with self._state_lock:
                self._generation += 1
                self._active = True
                self._dropped_blocks = 0
            self._reset_data()

    def deactivate(self) -> None:
        if not self.enabled:
            return
        with self._data_lock:
            with self._state_lock:
                self._generation += 1
                self._active = False
            self._reset_data()
        self._clear_queue()

    def submit(self, samples: NDArray[np.float32]) -> None:
        """Copy and queue samples without waiting for the analysis worker."""
        if not self.enabled:
            return
        values = np.asarray(samples, dtype=np.float32)
        if values.ndim != 1:
            raise ValueError("spectrum samples must be one-dimensional")
        if values.size == 0:
            return
        with self._state_lock:
            if not self._active:
                return
            generation = self._generation
        item = (generation, values.copy(), False)
        try:
            self._queue.put_nowait(item)
            return
        except queue.Full:
            pass

        queued_blocks = max(1, self._queue.qsize())
        with self._state_lock:
            if not self._active or generation != self._generation:
                return
            self._generation += 1
            generation = self._generation
            self._dropped_blocks += queued_blocks
        self._clear_queue()
        try:
            self._queue.put_nowait((generation, values.copy(), True))
        except queue.Full:
            with self._state_lock:
                self._dropped_blocks += 1

    def snapshot(self) -> AudioSpectrumSnapshot:
        """Copy the rolling matrix into chronological order for the UI."""
        with self._data_lock:
            with self._state_lock:
                active = self._active
                dropped_blocks = self._dropped_blocks
            ordered = np.full_like(self._levels, np.nan)
            if self._column_count < self.column_capacity:
                if self._column_count:
                    ordered[:, -self._column_count :] = self._levels[
                        :, : self._column_count
                    ]
            else:
                tail = self.column_capacity - self._write_index
                ordered[:, :tail] = self._levels[:, self._write_index :]
                if self._write_index:
                    ordered[:, tail:] = self._levels[:, : self._write_index]
            return AudioSpectrumSnapshot(
                sequence=self._sequence,
                active=active,
                sample_rate=self.sample_rate,
                frequencies_hz=self._frequencies.copy(),
                levels_dbfs=ordered,
                history_s=self.config.history_s,
                window_ms=self.config.window_ms,
                hop_ms=self.config.hop_ms,
                min_dbfs=self.config.min_dbfs,
                max_dbfs=self.config.max_dbfs,
                latest_peak_dbfs=self._latest_peak_dbfs,
                dropped_blocks=dropped_blocks,
            )

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is None:
                break
            generation, samples, discontinuity = item
            with self._data_lock:
                with self._state_lock:
                    valid = self._active and generation == self._generation
                if not valid:
                    continue
                if discontinuity:
                    self._pending = np.empty(0, dtype=np.float32)
                self._consume(samples)

    def _consume(self, samples: NDArray[np.float32]) -> None:
        if not np.all(np.isfinite(samples)):
            return
        self._pending = np.concatenate((self._pending, samples))
        while self._pending.size >= self.window_length:
            frame = self._pending[: self.window_length]
            self._pending = self._pending[self.hop_length :]
            magnitude = np.abs(
                np.fft.rfft(frame * self._window, n=self.fft_length)
            ) / self._coherent_gain
            if magnitude.size > 2:
                magnitude[1:-1] *= 2.0
            levels = 20.0 * np.log10(
                np.maximum(magnitude, 10.0 ** (_DB_FLOOR / 20.0))
            )
            column = levels.astype(np.float32)
            self._levels[:, self._write_index] = column
            self._write_index = (self._write_index + 1) % self.column_capacity
            self._column_count = min(
                self.column_capacity, self._column_count + 1
            )
            self._latest_peak_dbfs = float(np.max(column))
            self._sequence += 1

    def _reset_data(self) -> None:
        self._pending = np.empty(0, dtype=np.float32)
        self._levels.fill(np.nan)
        self._write_index = 0
        self._column_count = 0
        self._latest_peak_dbfs = None
        self._sequence += 1

    def _clear_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

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
