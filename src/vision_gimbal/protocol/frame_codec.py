"""COBS-delimited framing for the host/device binary protocol."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .crc16 import crc16_ccitt_false

MAGIC = b"UA"
PROTOCOL_VERSION = 1
MAX_PAYLOAD_LENGTH = 512
MAX_ENCODED_FRAME_LENGTH = 640
HEADER = struct.Struct("<2sBBHHIII")
CRC = struct.Struct("<H")


class FrameDecodeError(ValueError):
    """Raised when a complete wire frame is invalid."""


@dataclass(frozen=True)
class Frame:
    message_type: int
    payload: bytes = b""
    flags: int = 0
    session_id: int = 0
    sequence: int = 0
    sample_index: int = 0
    version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if not 0 <= self.message_type <= 0xFF:
            raise ValueError("message_type must fit uint8")
        if len(self.payload) > MAX_PAYLOAD_LENGTH:
            raise ValueError("payload exceeds protocol maximum")
        if not 0 <= self.flags <= 0xFFFF:
            raise ValueError("flags must fit uint16")
        for name in ("session_id", "sequence", "sample_index"):
            if not 0 <= getattr(self, name) <= 0xFFFFFFFF:
                raise ValueError(f"{name} must fit uint32")


def cobs_encode(data: bytes) -> bytes:
    """Encode one payload with Consistent Overhead Byte Stuffing."""

    output = bytearray()
    code_index = 0
    output.append(0)
    code = 1
    for value in data:
        if value == 0:
            output[code_index] = code
            code_index = len(output)
            output.append(0)
            code = 1
        else:
            output.append(value)
            code += 1
            if code == 0xFF:
                output[code_index] = code
                code_index = len(output)
                output.append(0)
                code = 1
    output[code_index] = code
    return bytes(output)


def cobs_decode(data: bytes) -> bytes:
    """Decode one COBS payload without its zero delimiter."""

    if not data:
        raise FrameDecodeError("empty COBS frame")
    output = bytearray()
    index = 0
    while index < len(data):
        code = data[index]
        if code == 0:
            raise FrameDecodeError("zero byte inside COBS frame")
        index += 1
        end = index + code - 1
        if end > len(data):
            raise FrameDecodeError("truncated COBS block")
        output.extend(data[index:end])
        index = end
        if code != 0xFF and index < len(data):
            output.append(0)
    return bytes(output)


def encode_frame(frame: Frame, *, leading_delimiter: bool = True) -> bytes:
    """Encode a frame for the wire, including resynchronizing delimiters."""

    header = HEADER.pack(
        MAGIC,
        frame.version,
        frame.message_type,
        frame.flags,
        len(frame.payload),
        frame.session_id,
        frame.sequence,
        frame.sample_index,
    )
    body = header + frame.payload
    raw = body + CRC.pack(crc16_ccitt_false(body))
    prefix = b"\x00" if leading_delimiter else b""
    return prefix + cobs_encode(raw) + b"\x00"


def decode_frame(encoded: bytes) -> Frame:
    """Decode one COBS payload without surrounding zero delimiters."""

    raw = cobs_decode(encoded)
    if len(raw) < HEADER.size + CRC.size:
        raise FrameDecodeError("frame is shorter than header and CRC")
    body, supplied_crc_bytes = raw[: -CRC.size], raw[-CRC.size :]
    supplied_crc = CRC.unpack(supplied_crc_bytes)[0]
    if crc16_ccitt_false(body) != supplied_crc:
        raise FrameDecodeError("CRC mismatch")
    (
        magic,
        version,
        message_type,
        flags,
        payload_length,
        session_id,
        sequence,
        sample_index,
    ) = HEADER.unpack(body[: HEADER.size])
    if magic != MAGIC:
        raise FrameDecodeError("bad frame magic")
    if version != PROTOCOL_VERSION:
        raise FrameDecodeError(f"unsupported protocol version: {version}")
    if payload_length > MAX_PAYLOAD_LENGTH:
        raise FrameDecodeError("payload exceeds protocol maximum")
    payload = body[HEADER.size :]
    if len(payload) != payload_length:
        raise FrameDecodeError("payload length mismatch")
    return Frame(
        message_type=message_type,
        payload=payload,
        flags=flags,
        session_id=session_id,
        sequence=sequence,
        sample_index=sample_index,
        version=version,
    )


class FrameStreamDecoder:
    """Incrementally split and validate zero-delimited COBS frames."""

    def __init__(self, maximum_encoded_length: int = MAX_ENCODED_FRAME_LENGTH) -> None:
        self.maximum_encoded_length = maximum_encoded_length
        self._encoded = bytearray()
        self.decode_error_count = 0
        self.oversize_frame_count = 0

    def reset(self) -> None:
        self._encoded.clear()

    def feed(self, data: bytes) -> list[Frame]:
        frames: list[Frame] = []
        for value in data:
            if value == 0:
                if not self._encoded:
                    continue
                try:
                    frames.append(decode_frame(bytes(self._encoded)))
                except FrameDecodeError:
                    self.decode_error_count += 1
                self._encoded.clear()
                continue
            if len(self._encoded) >= self.maximum_encoded_length:
                self.oversize_frame_count += 1
                self._encoded.clear()
                continue
            self._encoded.append(value)
        return frames
