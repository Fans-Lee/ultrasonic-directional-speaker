"""Non-blocking serial adapter for the ESP32 ``(pan,tilt)`` protocol."""

import threading
from typing import Optional

from ..config.schema import SerialConfig
from ..domain.control import GimbalSetpoint, SerialLinkStatus


def encode_gimbal_command(setpoint: GimbalSetpoint) -> bytes:
    pan_degrees, tilt_degrees = setpoint.rounded_degrees()
    if not -90 <= pan_degrees <= 90 or not -90 <= tilt_degrees <= 90:
        raise ValueError("gimbal angles must be within -90..90 degrees")
    return ("(%s,%s)" % (pan_degrees, tilt_degrees)).encode("ascii")


class SerialGimbalSink:
    def __init__(self, config: SerialConfig) -> None:
        if not config.port:
            raise ValueError("SerialGimbalSink requires a serial port")
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
            self._set_error("pyserial is not installed")
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
            except Exception as error:
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


def create_gimbal_sink(config: SerialConfig):
    if config.port:
        return SerialGimbalSink(config)
    from .null_gimbal import NullGimbalSink

    return NullGimbalSink()
