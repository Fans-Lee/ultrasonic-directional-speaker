"""No-op device link used when no serial port is configured."""

from ..domain.audio import AudioPacket, AudioStreamTelemetry
from ..domain.control import GimbalSetpoint, SerialLinkStatus
from ..protocol.messages import StreamStart


class NullDeviceLink:
    def start(self) -> None:
        pass

    def close(self) -> None:
        pass

    def publish_gimbal(self, setpoint: GimbalSetpoint) -> None:
        del setpoint

    def start_audio_stream(self, parameters: StreamStart) -> None:
        del parameters

    def send_audio(self, packet: AudioPacket) -> None:
        del packet

    def stop_audio_stream(self) -> None:
        pass

    def set_mute(self, enabled: bool) -> None:
        del enabled

    def serial_status(self) -> SerialLinkStatus:
        return SerialLinkStatus(enabled=False, connected=False)

    def audio_status(self) -> AudioStreamTelemetry:
        return AudioStreamTelemetry()
