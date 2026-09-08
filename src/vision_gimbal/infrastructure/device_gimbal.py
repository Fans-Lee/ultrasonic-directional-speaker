"""Expose the shared device link through the existing gimbal port."""

from ..domain.control import GimbalSetpoint
from ..ports.device_link import DeviceLink


class DeviceGimbalSink:
    def __init__(self, link: DeviceLink) -> None:
        self._link = link

    def start(self) -> None:
        # ApplicationRuntime owns the shared physical link lifecycle.
        pass

    def publish(self, setpoint: GimbalSetpoint) -> None:
        self._link.publish_gimbal(setpoint)

    def status(self):
        return self._link.serial_status()

    def close(self) -> None:
        # Audio may still need the same connection during ordered shutdown.
        pass
