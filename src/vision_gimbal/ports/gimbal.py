"""Gimbal command output boundary."""

from typing import Protocol

from ..domain.control import GimbalSetpoint, SerialLinkStatus


class GimbalSink(Protocol):
    def start(self) -> None: ...

    def publish(self, setpoint: GimbalSetpoint) -> None: ...

    def status(self) -> SerialLinkStatus: ...

    def close(self) -> None: ...
