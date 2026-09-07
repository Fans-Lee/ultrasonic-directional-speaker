"""Non-blocking serial transport for the current ESP32 gimbal protocol."""

import threading
from dataclasses import dataclass
from typing import Optional, Protocol

if __package__:
    from .control_models import GimbalSetpoint, SerialLinkStatus
else:
    from control_models import GimbalSetpoint, SerialLinkStatus


@dataclass(frozen=True)
class GimbalSerialConfig:
    port: Optional[str] = None
    baudrate: int = 115200
    read_timeout_s: float = 0.02
    write_timeout_s: float = 0.10
    reconnect_interval_s: float = 1.0
    startup_delay_s: float = 0.8

    def __post_init__(self) -> None:
        if self.baudrate <= 0:
            raise ValueError("baudrate must be positive")
        for name, value in (
            ("read_timeout_s", self.read_timeout_s),
            ("write_timeout_s", self.write_timeout_s),
            ("reconnect_interval_s", self.reconnect_interval_s),
            ("startup_delay_s", self.startup_delay_s),
        ):
            if value < 0.0:
                raise ValueError(f"{name} cannot be negative")


class GimbalCommandSink(Protocol):
    def start(self) -> None: ...
    def publish(self, setpoint: GimbalSetpoint) -> None: ...
    def status(self) -> SerialLinkStatus: ...
    def close(self) -> None: ...


def encode_gimbal_command(setpoint: GimbalSetpoint) -> bytes:
    """Encode the existing firmware command: ``(pan,tilt)``."""
    pan_degrees, tilt_degrees = setpoint.rounded_degrees()
    if not -90 <= pan_degrees <= 90 or not -90 <= tilt_degrees <= 90:
        raise ValueError("gimbal angles must be within -90..90 degrees")
    return f"({pan_degrees},{tilt_degrees})".encode("ascii")


class NullGimbalClient:
    """Dry-run sink used when no serial port is configured."""

    def start(self) -> None:
        pass

    def publish(self, setpoint: GimbalSetpoint) -> None:
        del setpoint

    def status(self) -> SerialLinkStatus:
        return SerialLinkStatus(enabled=False, connected=False)

    def close(self) -> None:
        pass


class SerialGimbalClient:
    """Own the serial port and always transmit only the newest setpoint."""

    def __init__(self, config: GimbalSerialConfig) -> None:
        if not config.port:
            raise ValueError("SerialGimbalClient requires a serial port")
        self.config = config
        self._condition = threading.Condition()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._latest_setpoint: Optional[GimbalSetpoint] = None
        self._published_version = 0
        self._connected = False
        self._last_response = ""
        self._last_error = ""

    def start(self) -> None:
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="gimbal-serial",
                daemon=True,
            )
            self._thread.start()

    def publish(self, setpoint: GimbalSetpoint) -> None:
        # Validate before publishing so worker failures do not hide bad control
        # configuration.
        encode_gimbal_command(setpoint)
        with self._condition:
            self._latest_setpoint = setpoint
            self._published_version += 1
            self._condition.notify_all()

    def status(self) -> SerialLinkStatus:
        with self._condition:
            return SerialLinkStatus(
                enabled=True,
                connected=self._connected,
                last_response=self._last_response,
                last_error=self._last_error,
            )

    def close(self) -> None:
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        with self._condition:
            self._thread = None
            self._connected = False

    def _run(self) -> None:
        try:
            import serial
        except ImportError:
            self._set_error(
                "pyserial is not installed; run the project dependency sync"
            )
            return

        while not self._stop_event.is_set():
            device = None
            try:
                device = serial.Serial(
                    port=self.config.port,
                    baudrate=self.config.baudrate,
                    timeout=self.config.read_timeout_s,
                    write_timeout=self.config.write_timeout_s,
                )
                if self._stop_event.wait(self.config.startup_delay_s):
                    break
                self._set_connected(True)
                sent_version = -1

                while not self._stop_event.is_set():
                    with self._condition:
                        setpoint = self._latest_setpoint
                        version = self._published_version
                    if setpoint is not None and version != sent_version:
                        device.write(encode_gimbal_command(setpoint))
                        sent_version = version

                    if device.in_waiting > 0:
                        response = device.readline().decode(
                            "utf-8", errors="replace"
                        ).strip()
                        if response:
                            with self._condition:
                                self._last_response = response
                                self._last_error = ""
                    self._stop_event.wait(0.01)
            except Exception as error:  # Serial backends use several exceptions.
                self._set_error(str(error))
            finally:
                self._set_connected(False)
                if device is not None:
                    try:
                        device.close()
                    except Exception:
                        pass

            if self._stop_event.wait(self.config.reconnect_interval_s):
                break

    def _set_connected(self, connected: bool) -> None:
        with self._condition:
            self._connected = connected
            if connected:
                self._last_error = ""

    def _set_error(self, error: str) -> None:
        with self._condition:
            self._connected = False
            self._last_error = error


def create_gimbal_client(config: GimbalSerialConfig) -> GimbalCommandSink:
    if config.port:
        return SerialGimbalClient(config)
    return NullGimbalClient()

