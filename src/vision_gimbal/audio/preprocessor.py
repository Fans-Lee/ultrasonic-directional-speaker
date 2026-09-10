"""End-to-end stateful preprocessing from microphone blocks to PCM_U8."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from ..config.schema import AudioCaptureConfig, AudioDspConfig, AudioStreamConfig
from .filters import antialias_lowpass, speech_highpass
from .level_control import CompressorLimiter, SlowLeveler
from .quantizer import quantize_pcm_u8
from .resampler import StreamingLinearResampler


@dataclass(frozen=True)
class ProcessedAudio:
    samples: bytes
    clipped_samples: int
    post_limiter_samples: NDArray[np.float32]


class AudioPreprocessor:
    def __init__(
        self,
        capture: AudioCaptureConfig,
        dsp: AudioDspConfig,
        stream: AudioStreamConfig,
    ) -> None:
        if dsp.lowpass_hz >= stream.sample_rate / 2.0:
            raise ValueError("audio low-pass must stay below stream Nyquist")
        if dsp.measured_eq_enabled:
            raise ValueError(
                "measured EQ is enabled but no measured coefficient profile is configured"
            )
        self.capture = capture
        self.dsp = dsp
        self.stream = stream
        self._highpass = speech_highpass(capture.sample_rate, dsp.highpass_hz)
        self._lowpass = antialias_lowpass(
            capture.sample_rate, dsp.lowpass_hz, stream.sample_rate / 2.0
        )
        self._resampler = StreamingLinearResampler(
            capture.sample_rate, stream.sample_rate
        )
        self._leveler = SlowLeveler(
            stream.sample_rate,
            dsp.level_target_dbfs,
            dsp.level_max_gain_db,
            dsp.level_attack_ms,
            dsp.level_release_ms,
            dsp.level_freeze_below_dbfs,
        )
        self._compressor = CompressorLimiter(
            stream.sample_rate,
            dsp.compressor_threshold_dbfs,
            dsp.compressor_ratio,
            dsp.compressor_attack_ms,
            dsp.compressor_release_ms,
            dsp.limiter_ceiling_dbfs,
        )

    def reset(self) -> None:
        self._highpass.reset()
        self._lowpass.reset()
        self._resampler.reset()
        self._leveler.reset()
        self._compressor.reset()

    def set_rate_correction_ppm(self, correction_ppm: float) -> None:
        self._resampler.set_rate_correction_ppm(correction_ppm)

    def process(self, block: NDArray[np.float32]) -> ProcessedAudio:
        values = np.asarray(block, dtype=np.float32)
        if values.ndim == 1:
            mono = values
        elif values.ndim == 2 and values.shape[1] >= 1:
            mono = np.mean(values, axis=1, dtype=np.float32)
        else:
            raise ValueError("microphone block must be samples or samples x channels")
        if not np.all(np.isfinite(mono)):
            raise ValueError("microphone block contains NaN or infinity")

        filtered = self._highpass.process(mono)
        # Measured EQ is deliberately disabled until coefficients derived from
        # a real array measurement are supplied; theoretical inverse-f^2 is not
        # safe to apply as an implicit default.
        filtered = self._lowpass.process(filtered)
        resampled = self._resampler.process(filtered)
        leveled = self._leveler.process(resampled)
        limited = self._compressor.process(leveled)
        quantized = quantize_pcm_u8(limited)
        return ProcessedAudio(
            quantized.samples,
            quantized.clipped_samples,
            limited,
        )
