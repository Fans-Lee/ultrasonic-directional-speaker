"""Dry-run gimbal output used without a serial port."""

from ..domain.control import GimbalSetpoint, SerialLinkStatus


class NullGimbalSink:
    def __init__(self) -> None:
        self.last_setpoint: GimbalSetpoint | None = None

    def start(self) -> None:
        pass

    def publish(self, setpoint: GimbalSetpoint) -> None:
        self.last_setpoint = setpoint

    def status(self) -> SerialLinkStatus:
        return SerialLinkStatus(enabled=False, connected=False)

    def close(self) -> None:
        pass
