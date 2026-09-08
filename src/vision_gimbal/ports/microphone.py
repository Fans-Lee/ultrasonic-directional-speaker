"""Microphone capture boundary."""

from collections.abc import Callable
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

AudioCaptureCallback = Callable[[NDArray[np.float32]], None]


class MicrophoneSource(Protocol):
    def start(self, callback: AudioCaptureCallback) -> None: ...

    def close(self) -> None: ...
