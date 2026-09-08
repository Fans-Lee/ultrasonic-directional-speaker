"""Convert normalized floating-point speech to the firmware PCM format."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class QuantizedAudio:
    samples: bytes
    clipped_samples: int


def quantize_pcm_u8(samples: NDArray[np.float32]) -> QuantizedAudio:
    values = np.asarray(samples, dtype=np.float32).reshape(-1)
    clipped_samples = int(np.count_nonzero((values <= -1.0) | (values >= 1.0)))
    encoded = np.clip(np.rint(128.0 + 128.0 * values), 0, 255).astype(np.uint8)
    return QuantizedAudio(encoded.tobytes(), clipped_samples)
