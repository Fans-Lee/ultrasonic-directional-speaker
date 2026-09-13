"""PortAudio capture adapter using the optional sounddevice dependency."""

from __future__ import annotations

import threading

import numpy as np

from ..config.schema import AudioCaptureConfig
from ..ports.microphone import AudioCaptureCallback


class SoundDeviceAudioSource:
    def __init__(self, config: AudioCaptureConfig) -> None:
        self.config = config
        self._stream = None
        self._lock = threading.Lock()
        self.input_overflow_count = 0

    def start(self, callback: AudioCaptureCallback) -> None:
        with self._lock:
            if self._stream is not None:
                return
            try:
                import sounddevice as sd
            except ImportError as error:
                raise RuntimeError(
                    "sounddevice is required for live audio streaming; "
                    "sync dependencies"
                ) from error

            block_size = round(self.config.sample_rate * self.config.block_ms / 1000)
            device = self.config.device
            if device == "":
                device = None

            def audio_callback(indata, frames, time_info, status) -> None:
                del frames, time_info
                if status.input_overflow:
                    self.input_overflow_count += 1
                callback(np.asarray(indata, dtype=np.float32).copy())

            stream = sd.InputStream(
                samplerate=self.config.sample_rate,
                blocksize=block_size,
                device=device,
                channels=self.config.channels,
                dtype="float32",
                callback=audio_callback,
            )
            stream.start()
            self._stream = stream

    def close(self) -> None:
        with self._lock:
            stream = self._stream
            self._stream = None
        if stream is not None:
            stream.stop()
            stream.close()


# Compatibility alias retained for the microphone-only command-line entry point.
SoundDeviceMicrophone = SoundDeviceAudioSource
