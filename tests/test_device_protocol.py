"""Golden behavior for the versioned COBS/CRC device protocol."""

import sys
import io
import json
import threading
import time
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from vision_gimbal.config.schema import AppConfig, SerialConfig
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
    STATUS,
    FrameFlags,
    MessageType,
    StreamStart,
    StreamState,
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
    def test_obsolete_start_ack_cannot_enable_restarted_stream_early(self):
        class Writer:
            def write(self, data):
                return len(data)

        link = SerialDeviceLink(SerialConfig(port="TEST"))
        link._session_id = 9
        link._protocol_ready = True
        link._connected = True
        pending = {}

        old = StreamStart()
        new = StreamStart()
        link.start_audio_stream(old)
        link._send_outbound(Writer(), link._take_outbound(), pending)
        link.start_audio_stream(new)

        link._handle_frame(
            Frame(
                MessageType.COMMAND_ACK,
                ACK.pack(MessageType.STREAM_START, 0, 0, 0),
                session_id=9,
            ),
            pending,
        )
        self.assertFalse(link.stream_ready)

        link._send_outbound(Writer(), link._take_outbound(), pending)
        link._handle_frame(
            Frame(
                MessageType.COMMAND_ACK,
                ACK.pack(MessageType.STREAM_START, 0, 0, 1),
                session_id=9,
            ),
            pending,
        )
        self.assertTrue(link.stream_ready)

    def test_status_age_distinguishes_no_status_from_stale_status(self):
        link = SerialDeviceLink(SerialConfig(port="TEST"))
        self.assertIsNone(link.audio_status().status_age_ms)
        frame = Frame(
            MessageType.STATUS,
            STATUS.pack(StreamState.PLAYING, 0, 0, 480, 2048, 1, 2, 3, 4, 5, 6, 0),
        )
        with patch("vision_gimbal.infrastructure.serial_device_link.time.monotonic", return_value=10.0):
            link._handle_frame(frame, {})
        with patch("vision_gimbal.infrastructure.serial_device_link.time.monotonic", return_value=10.25):
            status = link.audio_status()
        self.assertEqual(status.status_age_ms, 250)
        self.assertEqual(status.crc_error_count, 3)
        self.assertEqual(status.timer_skipped_samples, 5)
        self.assertIn("gap=4", link.serial_status().last_response)

    def test_lost_start_ack_does_not_restart_stream_after_mute_ack(self):
        class LostStartAckSerial(_ProtocolSerial):
            """Model the firmware's one-entry duplicate ACK cache."""

            def __init__(self):
                super().__init__()
                self.last_command = None
                self.start_executions = 0
                self.dropped = False

            def _respond(self, request, message_type, payload):
                if message_type == MessageType.COMMAND_ACK:
                    command = (request.message_type, request.sequence)
                    if command != self.last_command:
                        if request.message_type == MessageType.STREAM_START:
                            self.start_executions += 1
                        self.last_command = command
                    if request.message_type == MessageType.STREAM_START and not self.dropped:
                        self.dropped = True
                        return
                super()._respond(request, message_type, payload)

        fake = LostStartAckSerial()
        original_serial = sys.modules.get("serial")
        sys.modules["serial"] = types.SimpleNamespace(Serial=lambda **_: fake)
        link = SerialDeviceLink(SerialConfig(port="TEST", startup_delay_s=0.0))
        try:
            link.start()
            deadline = time.monotonic() + 1.0
            while not link.serial_status().connected and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertTrue(link.serial_status().connected)
            link.start_audio_stream(StreamStart())
            link.set_mute(False)
            link.send_audio(AudioPacket(0, bytes(range(160))))
            deadline = time.monotonic() + 1.0
            while (
                not fake.audio_payloads or MessageType.SET_MUTE not in fake.received_types
            ) and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertEqual(fake.audio_payloads, [bytes(range(160))])
            self.assertTrue(fake.dropped)
            self.assertEqual(fake.start_executions, 1)
        finally:
            link.close()
            if original_serial is None:
                sys.modules.pop("serial", None)
            else:
                sys.modules["serial"] = original_serial

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


class AudioStreamProbeTests(unittest.TestCase):
    def test_probe_sends_exact_header_bytes_and_selected_modes(self):
        sys.path.insert(0, str(SRC_DIR.parent / "utils"))
        import audio_stream_probe as probe

        class StatusSerial(_ProtocolSerial):
            def __init__(self):
                super().__init__()
                self.parameters = None

            def _respond(self, request, message_type, payload):
                super()._respond(request, message_type, payload)
                if request.message_type == MessageType.STREAM_START:
                    self.parameters = StreamStart.unpack(request.payload)
                    super()._respond(request, MessageType.STATUS, STATUS.pack(
                        StreamState.PLAYING, 0, 0, 480, 2048, 0, 0, 0, 0, 0, 0, 0,
                    ))

        samples = bytes(range(256)) + bytes([0, 128, 255])
        fake = StatusSerial()
        with TemporaryDirectory() as folder:
            header = Path(folder) / "audio_data.h"
            header.write_text(
                "static constexpr uint32_t kAudioSampleRate = 8000;\n"
                "static constexpr uint8_t kAudioSamples[] PROGMEM = {"
                + ",".join(map(str, samples)) + ",};", encoding="utf-8",
            )
            log_path = Path(folder) / "probe.jsonl"
            with patch.dict(sys.modules, serial=types.SimpleNamespace(Serial=lambda **_: fake)), \
                 patch.object(probe, "load_config", return_value=AppConfig(
                     serial=SerialConfig(startup_delay_s=0.0))), redirect_stdout(io.StringIO()):
                result = probe.main([
                    "--serial-port", "TEST", "--audio-header", str(header),
                    "--repeats", "1", "--processing", "loud", "--drive", "boost",
                    "--log-jsonl", str(log_path),
                ])
            self.assertEqual(result, 0)
            transmitted = b"".join(fake.audio_payloads)
            self.assertEqual(transmitted, samples + bytes([128]) * (2048 + 160))
            self.assertEqual(int(fake.parameters.processing), 1)
            self.assertEqual(int(fake.parameters.drive), 1)
            records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(records[-1]["host_sent_samples"], len(transmitted))
            self.assertEqual(records[-1]["host_tx_overrun_count"], 0)
            self.assertEqual(records[-1]["timer_skipped_samples"], 0)


if __name__ == "__main__":
    unittest.main()
