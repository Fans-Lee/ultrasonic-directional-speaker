"""Audio values shared without depending on capture, serial, or UI libraries."""

from __future__ import annotations

from dataclasses import dataclass

from ..protocol.messages import StreamState


@dataclass(frozen=True)
class AudioPacket:
    sample_index: int
    samples: bytes
    end_of_stream: bool = False


@dataclass(frozen=True)
class AudioStreamTelemetry:
    state: StreamState = StreamState.IDLE
    muted: bool = True
    buffer_fill_samples: int = 0
    buffer_capacity_samples: int = 0
    underrun_count: int = 0
    overrun_count: int = 0
    crc_error_count: int = 0
    sequence_gap_count: int = 0
    timer_skipped_samples: int = 0
    last_audio_age_ms: int = 0
    host_capture_overrun_count: int = 0
    host_tx_overrun_count: int = 0
    quantizer_clip_count: int = 0
