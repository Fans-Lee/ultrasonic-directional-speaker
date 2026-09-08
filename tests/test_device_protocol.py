"""Golden behavior for the versioned COBS/CRC device protocol."""

import sys
import threading
import time
import types
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from vision_gimbal.config.schema import SerialConfig
from vision_gimbal.domain.audio import AudioPacket
from vision_gimbal.infrastructure.serial_device_link import SerialDeviceLink
from vision_gimbal.protocol.frame_codec import (
    Frame,
    FrameDecodeError,
    FrameStreamDecoder,
    cobs_decode,
    cobs_encode,
    decode_frame,
    encode_frame,
)
from vision_gimbal.protocol.messages import (
    ACK,
    HELLO_ACK,
    FrameFlags,
    MessageType,
    StreamStart,
    pack_gimbal_setpoint,
)


class CobsTests(unittest.TestCase):
    def test_round_trip_with_zeroes_and_long_runs(self):
        payload = bytes(range(256)) + b"\x00" * 4 + bytes(range(255, -1, -1))
        encoded = cobs_encode(payload)
        self.assertNotIn(0, encoded)
        self.assertEqual(cobs_decode(encoded), payload)


class FrameCodecTests(unittest.TestCase):
    def test_round_trip_audio_frame(self):
        original = Frame(
            message_type=MessageType.AUDIO_DATA,
            payload=bytes(range(160)),
            session_id=0x12345678,
            sequence=42,
            sample_index=320,
        )
        wire = encode_frame(original)
        self.assertEqual(wire[0], 0)
        self.assertEqual(wire[-1], 0)
        decoded = decode_frame(wire[1:-1])
        self.assertEqual(decoded, original)

    def test_stream_decoder_handles_fragmentation_and_noise(self):
        first = Frame(MessageType.PING, b"1234", session_id=7, sequence=1)
        second = Frame(MessageType.SET_MUTE, b"\x01", session_id=7, sequence=2)
        wire = b"unframed startup log" + encode_frame(first) + encode_frame(second)
        decoder = FrameStreamDecoder()
        frames = []
        for offset in range(0, len(wire), 3):
            frames.extend(decoder.feed(wire[offset : offset + 3]))
        self.assertEqual(frames, [first, second])
        self.assertEqual(decoder.decode_error_count, 1)

    def test_crc_failure_is_rejected(self):
        wire = bytearray(encode_frame(Frame(MessageType.PING, b"abcd")))
        wire[-3] ^= 0x20
        with self.assertRaises(FrameDecodeError):
            decode_frame(bytes(wire[1:-1]))

    def test_stream_start_has_fixed_sixteen_byte_payload(self):
        parameters = StreamStart()
        self.assertEqual(len(parameters.pack()), 16)
        self.assertEqual(StreamStart.unpack(parameters.pack()), parameters)

    def test_gimbal_uses_signed_centidegrees(self):
        self.assertEqual(pack_gimbal_setpoint(-10.25, 30.0), b"\xff\xfb\xb8\x0b")

    def test_flags_can_be_combined(self):
        flags = FrameFlags.ACK_REQUIRED | FrameFlags.END_OF_STREAM
        self.assertEqual(int(flags), 9)


class _ProtocolSerial:
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs
        self._lock = threading.Lock()
        self._incoming = bytearray()
        self._decoder = FrameStreamDecoder()
        self._device_sequence = 0
        self.received_types = []
        self.audio_payloads = []

    @property
    def in_waiting(self) -> int:
        with self._lock:
            return len(self._incoming)

    def read(self, count: int) -> bytes:
        with self._lock:
            result = bytes(self._incoming[:count])
            del self._incoming[:count]
            return result

    def write(self, data: bytes) -> int:
        for frame in self._decoder.feed(data):
            message_type = MessageType(frame.message_type)
            self.received_types.append(message_type)
            if message_type is MessageType.HELLO:
                self._respond(
                    frame,
                    MessageType.HELLO_ACK,
                    HELLO_ACK.pack(512, 2048, 3),
                )
            elif message_type in {
                MessageType.STREAM_START,
                MessageType.STREAM_STOP,
                MessageType.SET_MUTE,
            }:
                self._respond(
                    frame,
                    MessageType.COMMAND_ACK,
                    ACK.pack(message_type, 0, 0, frame.sequence),
                )
            elif message_type is MessageType.AUDIO_DATA:
                self.audio_payloads.append(frame.payload)
        return len(data)

    def _respond(
        self, request: Frame, message_type: MessageType, payload: bytes
    ) -> None:
        response = encode_frame(
            Frame(
                message_type=message_type,
                payload=payload,
                session_id=request.session_id,
                sequence=self._device_sequence,
            )
        )
        self._device_sequence += 1
        with self._lock:
            self._incoming.extend(response)

    def reset_input_buffer(self) -> None:
        with self._lock:
            self._incoming.clear()

    def close(self) -> None:
        pass


class SerialDeviceLinkTests(unittest.TestCase):
    def test_handshake_stream_ack_and_audio_send(self):
        fake = _ProtocolSerial()
        original_serial = sys.modules.get("serial")
        sys.modules["serial"] = types.SimpleNamespace(Serial=lambda **_: fake)
        link = SerialDeviceLink(
            SerialConfig(
                port="TEST",
                baudrate=460800,
                startup_delay_s=0.0,
                reconnect_interval_s=0.01,
            )
        )
        try:
            link.start()
            deadline = time.monotonic() + 1.0
            while not link.serial_status().connected and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertTrue(link.serial_status().connected)
            link.start_audio_stream(StreamStart())
            link.send_audio(AudioPacket(0, bytes([128]) * 160))
            deadline = time.monotonic() + 1.0
            while not fake.audio_payloads and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertEqual(fake.audio_payloads, [bytes([128]) * 160])
            self.assertIn(MessageType.STREAM_START, fake.received_types)
        finally:
            link.close()
            if original_serial is None:
                sys.modules.pop("serial", None)
            else:
                sys.modules["serial"] = original_serial


if __name__ == "__main__":
    unittest.main()
