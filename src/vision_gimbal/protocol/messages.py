"""Message payload definitions for protocol version 1."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum, IntFlag


class FrameFlags(IntFlag):
    NONE = 0
    ACK_REQUIRED = 1 << 0
    IS_ACK = 1 << 1
    ERROR = 1 << 2
    END_OF_STREAM = 1 << 3


class MessageType(IntEnum):
    HELLO = 0x01
    STREAM_START = 0x02
    AUDIO_DATA = 0x03
    STREAM_STOP = 0x04
    SET_MUTE = 0x05
    GIMBAL_SETPOINT = 0x06
    PING = 0x07
    SET_VOLUME = 0x08

    HELLO_ACK = 0x81
    COMMAND_ACK = 0x82
    STATUS = 0x83
    LOG = 0x84
    ERROR = 0x85
    PONG = 0x87


class AudioSampleFormat(IntEnum):
    PCM_U8 = 1


class AudioModulation(IntEnum):
    DSB_AM = 0
    SRAM = 1


class AudioProcessing(IntEnum):
    RAW = 0
    LOUD = 1


class AudioDrive(IntEnum):
    STANDARD = 0
    BOOST = 1


class StreamState(IntEnum):
    IDLE = 0
    PREFILL = 1
    PLAYING = 2
    DRAINING = 3
    MUTED = 4
    FAULT = 5


HELLO = struct.Struct("<HHI")
HELLO_ACK = struct.Struct("<HHI")
STREAM_START = struct.Struct("<IHHBBBBBBH")
ACK = struct.Struct("<BBHI")
GIMBAL = struct.Struct("<hh")
MUTE = struct.Struct("<B")
VOLUME = struct.Struct("<H")
PING = struct.Struct("<I")
STATUS = struct.Struct("<BBHHHIIIIIHH")
VOLUME_CAPABILITY = 1 << 2


@dataclass(frozen=True)
class StreamStart:
    sample_rate: int = 8000
    packet_samples: int = 160
    prebuffer_samples: int = 960
    sample_format: AudioSampleFormat = AudioSampleFormat.PCM_U8
    channels: int = 1
    modulation: AudioModulation = AudioModulation.DSB_AM
    processing: AudioProcessing = AudioProcessing.RAW
    drive: AudioDrive = AudioDrive.STANDARD
    underflow_policy: int = 1
    data_timeout_ms: int = 500

    def __post_init__(self) -> None:
        if self.sample_rate != 8000 or self.channels != 1:
            raise ValueError("protocol version 1 requires 8 kHz mono audio")
        if not 1 <= self.packet_samples <= 512:
            raise ValueError("packet_samples must be in [1, 512]")
        if not 1 <= self.prebuffer_samples <= 2048:
            raise ValueError("prebuffer_samples must be in [1, 2048]")
        if self.underflow_policy != 1:
            raise ValueError("protocol version 1 requires underflow policy 1")
        if not 20 <= self.data_timeout_ms <= 2000:
            raise ValueError("data_timeout_ms must be in [20, 2000]")

    def pack(self) -> bytes:
        return STREAM_START.pack(
            self.sample_rate,
            self.packet_samples,
            self.prebuffer_samples,
            int(self.sample_format),
            self.channels,
            int(self.modulation),
            int(self.processing),
            int(self.drive),
            self.underflow_policy,
            self.data_timeout_ms,
        )

    @classmethod
    def unpack(cls, payload: bytes) -> StreamStart:
        if len(payload) != STREAM_START.size:
            raise ValueError("invalid STREAM_START payload length")
        values = STREAM_START.unpack(payload)
        return cls(
            sample_rate=values[0],
            packet_samples=values[1],
            prebuffer_samples=values[2],
            sample_format=AudioSampleFormat(values[3]),
            channels=values[4],
            modulation=AudioModulation(values[5]),
            processing=AudioProcessing(values[6]),
            drive=AudioDrive(values[7]),
            underflow_policy=values[8],
            data_timeout_ms=values[9],
        )


@dataclass(frozen=True)
class DeviceStatusPayload:
    state: StreamState
    muted: bool
    last_error: int
    buffer_fill_samples: int
    buffer_capacity_samples: int
    underrun_count: int
    overrun_count: int
    crc_error_count: int
    sequence_gap_count: int
    timer_skipped_samples: int
    last_audio_age_ms: int
    target_volume_permille: int

    @classmethod
    def unpack(cls, payload: bytes) -> DeviceStatusPayload:
        if len(payload) != STATUS.size:
            raise ValueError("invalid STATUS payload length")
        values = STATUS.unpack(payload)
        return cls(
            state=StreamState(values[0]),
            muted=bool(values[1]),
            last_error=values[2],
            buffer_fill_samples=values[3],
            buffer_capacity_samples=values[4],
            underrun_count=values[5],
            overrun_count=values[6],
            crc_error_count=values[7],
            sequence_gap_count=values[8],
            timer_skipped_samples=values[9],
            last_audio_age_ms=values[10],
            target_volume_permille=values[11],
        )


def pack_gimbal_setpoint(pan_degrees: float, tilt_degrees: float) -> bytes:
    pan_centidegrees = round(pan_degrees * 100.0)
    tilt_centidegrees = round(tilt_degrees * 100.0)
    if not -9000 <= pan_centidegrees <= 9000:
        raise ValueError("pan must be within -90..90 degrees")
    if not -9000 <= tilt_centidegrees <= 9000:
        raise ValueError("tilt must be within -90..90 degrees")
    return GIMBAL.pack(pan_centidegrees, tilt_centidegrees)
