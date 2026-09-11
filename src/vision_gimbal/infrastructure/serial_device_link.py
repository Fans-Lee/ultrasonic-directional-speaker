"""One reconnecting serial owner for framed audio and gimbal traffic."""

from __future__ import annotations

import collections
import secrets
import threading
import time
from dataclasses import dataclass, replace

from ..config.schema import SerialConfig
from ..domain.audio import AudioPacket, AudioStreamTelemetry
from ..domain.control import GimbalSetpoint, SerialLinkStatus
from ..protocol.frame_codec import Frame, FrameStreamDecoder, encode_frame
from ..protocol.messages import (
    ACK,
    HELLO,
    HELLO_ACK,
    MUTE,
    PING,
    DeviceStatusPayload,
    FrameFlags,
    MessageType,
    StreamStart,
    StreamState,
    pack_gimbal_setpoint,
)


@dataclass
class _Outbound:
    message_type: MessageType
    payload: bytes
    ack_required: bool = False
    sample_index: int = 0
    end_of_stream: bool = False
    stream_revision: int = 0


@dataclass
class _PendingAck:
    wire: bytes
    message_type: MessageType
    sent_at: float
    stream_revision: int = 0
    retries: int = 0


class SerialDeviceLink:
    _ACK_TIMEOUT_S = 0.10
    _MAX_ACK_RETRIES = 3

    def __init__(self, config: SerialConfig, audio_queue_packets: int = 8) -> None:
        if not config.port:
            raise ValueError("SerialDeviceLink requires a serial port")
        self.config = config
        self.audio_queue_packets = audio_queue_packets
        self._condition = threading.Condition()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._control_queue: collections.deque[_Outbound] = collections.deque()
        self._audio_queue: collections.deque[AudioPacket] = collections.deque()
        self._latest_gimbal: bytes | None = None
        self._gimbal_dirty = False
        self._desired_stream: StreamStart | None = None
        self._stream_revision = 0
        self._protocol_ready = False
        self._stream_ready = False
        self._connected = False
        self._last_response = ""
        self._last_error = ""
        self._session_id = 0
        self._sequence = 0
        self._host_tx_overrun_count = 0
        self._host_rx_error_count = 0
        self._host_sent_samples = 0
        self._last_status_received_at: float | None = None
        self._audio_status = AudioStreamTelemetry()

    def start(self) -> None:
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run, name="device-serial", daemon=True
            )
            self._thread.start()

    def close(self) -> None:
        with self._condition:
            deadline = time.monotonic() + 0.25
            while (
                self._connected and self._control_queue and time.monotonic() < deadline
            ):
                self._condition.wait(timeout=0.01)
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        with self._condition:
            self._thread = None
            self._connected = False
            self._protocol_ready = False
            self._stream_ready = False
            self._audio_queue.clear()

    def publish_gimbal(self, setpoint: GimbalSetpoint) -> None:
        payload = pack_gimbal_setpoint(setpoint.pan_degrees, setpoint.tilt_degrees)
        with self._condition:
            self._latest_gimbal = payload
            self._gimbal_dirty = True
            self._condition.notify_all()

    def start_audio_stream(self, parameters: StreamStart) -> None:
        with self._condition:
            self._stream_revision += 1
            self._desired_stream = parameters
            self._stream_ready = False
            self._audio_queue.clear()
            if self._protocol_ready:
                self._queue_control_locked(
                    MessageType.STREAM_START,
                    parameters.pack(),
                    ack_required=True,
                    stream_revision=self._stream_revision,
                )

    def send_audio(self, packet: AudioPacket) -> None:
        with self._condition:
            if len(self._audio_queue) >= self.audio_queue_packets:
                self._audio_queue.popleft()
                self._host_tx_overrun_count += 1
            self._audio_queue.append(packet)
            self._condition.notify_all()

    def stop_audio_stream(self) -> None:
        with self._condition:
            self._stream_revision += 1
            self._desired_stream = None
            self._stream_ready = False
            self._audio_queue.clear()
            if self._protocol_ready:
                self._queue_control_locked(
                    MessageType.STREAM_STOP, b"\x00", ack_required=True
                )

    def set_mute(self, enabled: bool) -> None:
        with self._condition:
            if self._protocol_ready:
                self._queue_control_locked(
                    MessageType.SET_MUTE,
                    MUTE.pack(1 if enabled else 0),
                    ack_required=True,
                )

    def serial_status(self) -> SerialLinkStatus:
        with self._condition:
            return SerialLinkStatus(
                enabled=True,
                connected=self._connected,
                last_response=self._last_response,
                last_error=self._last_error,
            )

    def audio_status(self) -> AudioStreamTelemetry:
        with self._condition:
            return replace(
                self._audio_status,
                host_tx_overrun_count=self._host_tx_overrun_count,
                host_rx_error_count=self._host_rx_error_count,
                host_sent_samples=self._host_sent_samples,
                host_tx_queue_packets=len(self._audio_queue),
                status_age_ms=(
                    round((time.monotonic() - self._last_status_received_at) * 1000)
                    if self._last_status_received_at is not None else None
                ),
            )

    @property
    def stream_ready(self) -> bool:
        """True only after the requested STREAM_START has been acknowledged."""
        with self._condition:
            return self._connected and self._stream_ready

    def _queue_control_locked(
        self,
        message_type: MessageType,
        payload: bytes,
        *,
        ack_required: bool,
        stream_revision: int = 0,
    ) -> None:
        self._control_queue.append(
            _Outbound(
                message_type,
                payload,
                ack_required=ack_required,
                stream_revision=stream_revision,
            )
        )
        self._condition.notify_all()

    def _run(self) -> None:
        try:
            import serial
        except ImportError:
            self._set_error("pyserial is not installed")
            return

        while not self._stop_event.is_set():
            device = None
            try:
                device = serial.Serial(
                    port=self.config.port,
                    baudrate=self.config.baudrate,
                    timeout=0,
                    write_timeout=self.config.write_timeout_s,
                )
                if self._stop_event.wait(self.config.startup_delay_s):
                    break
                device.reset_input_buffer()
                decoder = FrameStreamDecoder()
                pending: dict[int, _PendingAck] = {}
                with self._condition:
                    self._session_id = secrets.randbits(32) or 1
                    self._sequence = 0
                    self._protocol_ready = False
                    self._stream_ready = False
                    self._connected = False
                    self._control_queue.clear()
                    self._audio_queue.clear()
                    self._last_status_received_at = None
                hello = HELLO.pack(512, 100, 0x00000003)
                self._send_outbound(
                    device,
                    _Outbound(MessageType.HELLO, hello, ack_required=True),
                    pending,
                )

                while not self._stop_event.is_set():
                    waiting = device.in_waiting
                    incoming = device.read(waiting) if waiting else b""
                    if incoming:
                        previous_errors = decoder.decode_error_count
                        frames = decoder.feed(incoming)
                        with self._condition:
                            self._host_rx_error_count += (
                                decoder.decode_error_count - previous_errors
                            )
                        for frame in frames:
                            self._handle_frame(frame, pending)
                    self._retry_pending(device, pending)
                    sent = 0
                    while sent < 4:
                        outbound = self._take_outbound(ack_pending=bool(pending))
                        if outbound is None:
                            break
                        self._send_outbound(device, outbound, pending)
                        sent += 1
                    if not incoming and sent == 0:
                        self._stop_event.wait(
                            min(0.005, max(0.001, self.config.read_timeout_s))
                        )
            except Exception as error:  # noqa: BLE001 - transport boundary
                self._set_error(str(error))
            finally:
                with self._condition:
                    self._connected = False
                    self._protocol_ready = False
                    self._stream_ready = False
                    self._audio_queue.clear()
                    self._audio_status = replace(
                        self._audio_status,
                        state=StreamState.MUTED,
                        muted=True,
                        buffer_fill_samples=0,
                    )
                if device is not None:
                    try:
                        device.close()
                    except Exception:  # noqa: BLE001, S110 - best effort
                        pass
            if self._stop_event.wait(self.config.reconnect_interval_s):
                break

    def _take_outbound(self, *, ack_pending: bool = False) -> _Outbound | None:
        with self._condition:
            # Firmware caches only the most recent command ACK. Sending another
            # reliable command before this ACK arrives can evict that cache and
            # make a retry execute STREAM_START again, clearing the audio buffer.
            if self._control_queue and not ack_pending:
                outbound = self._control_queue.popleft()
                self._condition.notify_all()
                return outbound
            if self._protocol_ready and self._gimbal_dirty and self._latest_gimbal:
                self._gimbal_dirty = False
                return _Outbound(MessageType.GIMBAL_SETPOINT, self._latest_gimbal)
            if self._stream_ready and self._audio_queue:
                packet = self._audio_queue.popleft()
                return _Outbound(
                    MessageType.AUDIO_DATA,
                    packet.samples,
                    sample_index=packet.sample_index,
                    end_of_stream=packet.end_of_stream,
                )
            return None

    def _send_outbound(self, device, outbound: _Outbound, pending) -> None:
        with self._condition:
            sequence = self._sequence
            self._sequence = (self._sequence + 1) & 0xFFFFFFFF
            session_id = self._session_id
        flags = FrameFlags.ACK_REQUIRED if outbound.ack_required else FrameFlags.NONE
        if outbound.end_of_stream:
            flags |= FrameFlags.END_OF_STREAM
        wire = encode_frame(
            Frame(
                message_type=int(outbound.message_type),
                payload=outbound.payload,
                flags=int(flags),
                session_id=session_id,
                sequence=sequence,
                sample_index=outbound.sample_index,
            )
        )
        written = device.write(wire)
        if written != len(wire):
            raise OSError(f"short serial write: {written}/{len(wire)}")
        if outbound.message_type is MessageType.AUDIO_DATA:
            with self._condition:
                self._host_sent_samples += len(outbound.payload)
        if outbound.ack_required:
            pending[sequence] = _PendingAck(
                wire,
                outbound.message_type,
                time.monotonic(),
                outbound.stream_revision,
            )

    def _retry_pending(self, device, pending: dict[int, _PendingAck]) -> None:
        now = time.monotonic()
        for sequence, item in list(pending.items()):
            if now - item.sent_at < self._ACK_TIMEOUT_S:
                continue
            if item.retries >= self._MAX_ACK_RETRIES:
                del pending[sequence]
                raise TimeoutError(f"timeout waiting for {item.message_type.name} ACK")
            written = device.write(item.wire)
            if written != len(item.wire):
                raise OSError(f"short serial retry: {written}/{len(item.wire)}")
            item.sent_at = now
            item.retries += 1

    def _handle_frame(self, frame: Frame, pending: dict[int, _PendingAck]) -> None:
        with self._condition:
            if frame.session_id != self._session_id:
                return
        try:
            message_type = MessageType(frame.message_type)
        except ValueError:
            return
        if message_type is MessageType.HELLO_ACK:
            if len(frame.payload) != HELLO_ACK.size:
                return
            pending_sequences = [
                sequence
                for sequence, item in pending.items()
                if item.message_type is MessageType.HELLO
            ]
            for sequence in pending_sequences:
                pending.pop(sequence, None)
            with self._condition:
                self._protocol_ready = True
                self._connected = True
                self._last_response = "protocol v1 connected"
                self._last_error = ""
                if self._desired_stream is not None:
                    self._queue_control_locked(
                        MessageType.STREAM_START,
                        self._desired_stream.pack(),
                        ack_required=True,
                        stream_revision=self._stream_revision,
                    )
            return
        if message_type is MessageType.COMMAND_ACK:
            if len(frame.payload) != ACK.size:
                return
            acked_type_value, result, detail, acked_sequence = ACK.unpack(frame.payload)
            item = pending.get(acked_sequence)
            if item is None or int(item.message_type) != acked_type_value:
                return
            pending.pop(acked_sequence, None)
            try:
                acked_type = MessageType(acked_type_value)
            except ValueError:
                acked_type = None
            with self._condition:
                if result != 0:
                    self._last_error = (
                        f"device rejected command {acked_type_value:#x}: {detail}"
                    )
                elif acked_type is MessageType.STREAM_START:
                    self._stream_ready = (
                        self._desired_stream is not None
                        and item.stream_revision == self._stream_revision
                    )
                elif acked_type is MessageType.STREAM_STOP:
                    self._stream_ready = False
                self._last_response = f"ACK {acked_type_value:#x} result={result}"
            return
        if message_type is MessageType.STATUS:
            status = DeviceStatusPayload.unpack(frame.payload)
            with self._condition:
                self._last_status_received_at = time.monotonic()
                self._audio_status = AudioStreamTelemetry(
                    state=status.state,
                    muted=status.muted,
                    buffer_fill_samples=status.buffer_fill_samples,
                    buffer_capacity_samples=status.buffer_capacity_samples,
                    underrun_count=status.underrun_count,
                    overrun_count=status.overrun_count,
                    crc_error_count=status.crc_error_count,
                    sequence_gap_count=status.sequence_gap_count,
                    timer_skipped_samples=status.timer_skipped_samples,
                    last_audio_age_ms=status.last_audio_age_ms,
                )
                self._last_response = (
                    f"audio={status.state.name} buffer="
                    f"{status.buffer_fill_samples}/{status.buffer_capacity_samples} "
                    f"under={status.underrun_count} over={status.overrun_count} "
                    f"crc={status.crc_error_count} gap={status.sequence_gap_count} "
                    f"skip={status.timer_skipped_samples} "
                    f"host_drop={self._host_tx_overrun_count}"
                )
            return
        if message_type is MessageType.ERROR:
            self._set_error(frame.payload.decode("utf-8", errors="replace"))
            return
        if message_type is MessageType.PONG and len(frame.payload) == PING.size:
            with self._condition:
                self._last_response = f"PONG {PING.unpack(frame.payload)[0]}"

    def _set_error(self, error: str) -> None:
        with self._condition:
            self._last_error = error
            self._connected = False


def create_device_link(config: SerialConfig, audio_queue_packets: int = 8):
    if config.port:
        return SerialDeviceLink(config, audio_queue_packets)
    from .null_device_link import NullDeviceLink

    return NullDeviceLink()
