"""Versioned binary protocol shared by audio and gimbal traffic."""

from .frame_codec import Frame, FrameStreamDecoder, decode_frame, encode_frame
from .messages import MessageType

__all__ = [
    "Frame",
    "FrameStreamDecoder",
    "MessageType",
    "decode_frame",
    "encode_frame",
]
