"""Audio values shared without depending on capture, serial, or UI libraries."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..protocol.messages import StreamState


class AudioProcessingMode(str, Enum):
    RAW = "raw"
    LOUD = "loud"


class AudioDriveMode(str, Enum):
    STANDARD = "standard"
    BOOST = "boost"


class AudioModulationMode(str, Enum):
    DSB_AM = "dsb_am"
    SRAM = "sram"


class AudioSourceKind(str, Enum):
    MICROPHONE = "microphone"
    STEREO_MIX = "stereo_mix"
    SYSTEM_LOOPBACK = "system_loopback"


@dataclass(frozen=True)
class AudioModeSettings:
    processing: AudioProcessingMode = AudioProcessingMode.RAW
    drive: AudioDriveMode = AudioDriveMode.STANDARD
    modulation: AudioModulationMode = AudioModulationMode.DSB_AM

    def __post_init__(self) -> None:
        """Normalize strings returned by Qt's QVariant bridge to enums."""
        processing = (
            self.processing.value
            if isinstance(self.processing, AudioProcessingMode)
            else str(self.processing).lower()
        )
        drive = (
            self.drive.value
            if isinstance(self.drive, AudioDriveMode)
            else str(self.drive).lower()
        )
        modulation = (
            self.modulation.value
            if isinstance(self.modulation, AudioModulationMode)
            else str(self.modulation).lower().replace("-", "_")
        )
        object.__setattr__(self, "processing", AudioProcessingMode(processing))
        object.__setattr__(self, "drive", AudioDriveMode(drive))
        object.__setattr__(self, "modulation", AudioModulationMode(modulation))


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
    host_capture_restart_count: int = 0
    host_capture_block_age_ms: int | None = None
    host_tx_overrun_count: int = 0
    quantizer_clip_count: int = 0
    host_rx_error_count: int = 0
    host_sent_samples: int = 0
    host_tx_queue_packets: int = 0
    status_age_ms: int | None = None
    device_volume_permille: int | None = None


@dataclass(frozen=True)
class AudioControlStatus:
    enabled: bool = False
    transmitting: bool = False
    selected_source: AudioSourceKind = AudioSourceKind.MICROPHONE
    active_source: AudioSourceKind | None = None
    source_open: bool = False
    array_active: bool = False
    settings: AudioModeSettings = field(default_factory=AudioModeSettings)
    volume_percent: int = 50
    telemetry: AudioStreamTelemetry = field(default_factory=AudioStreamTelemetry)
    last_error: str = ""

    @property
    def microphone_open(self) -> bool:
        """Compatibility view for older presentation and diagnostic code."""
        return self.source_open and self.active_source is AudioSourceKind.MICROPHONE
