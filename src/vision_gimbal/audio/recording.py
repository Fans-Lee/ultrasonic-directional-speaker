"""Optional WAV sink for the post-limiter monitoring signal."""

from __future__ import annotations

import threading
import wave
from datetime import datetime
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from ..config.schema import AudioRecordingConfig


class PostLimiterWavRecorder:
    """Write normalized post-limiter samples as mono PCM16 WAV."""

    def __init__(self, config: AudioRecordingConfig, sample_rate: int) -> None:
        if sample_rate <= 0:
            raise ValueError("recording sample rate must be positive")
        self.config = config
        self.sample_rate = sample_rate
        self._lock = threading.Lock()
        self._stream = None
        self._current_path: Path | None = None

    @property
    def current_path(self) -> Path | None:
        with self._lock:
            return self._current_path

    def start(self) -> Path | None:
        if not self.config.enabled:
            return None
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = Path(self.config.path.replace("{timestamp}", timestamp))
        with self._lock:
            self._close_locked()
            path.parent.mkdir(parents=True, exist_ok=True)
            stream = wave.open(str(path), "wb")
            try:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(self.sample_rate)
            except Exception:
                stream.close()
                raise
            self._stream = stream
            self._current_path = path
        return path

    def write(self, samples: NDArray[np.float32]) -> None:
        values = np.asarray(samples, dtype=np.float32).reshape(-1)
        if values.size == 0:
            return
        pcm16 = np.clip(np.rint(values * 32767.0), -32768, 32767).astype("<i2")
        frames = pcm16.tobytes()
        with self._lock:
            if self._stream is not None:
                self._stream.writeframesraw(frames)

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def _close_locked(self) -> None:
        if self._stream is None:
            return
        stream = self._stream
        self._stream = None
        stream.close()
