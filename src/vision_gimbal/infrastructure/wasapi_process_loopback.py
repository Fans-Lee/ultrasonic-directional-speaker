"""Windows process-loopback capture that is independent of output endpoints."""

from __future__ import annotations

import os
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

from ..config.schema import AudioCaptureConfig
from ..ports.microphone import AudioCaptureCallback

_HEADER = struct.Struct("<4sIHH")
_MAGIC = b"UPCM"
_FLOAT32_FORMAT = 1


class WasapiProcessLoopbackSource:
    """Capture every render process except this application and its children."""

    def __init__(self, config: AudioCaptureConfig) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._process: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None
        self._last_error = ""
        self._last_block_at: float | None = None
        self._is_open = False
        self._restart_count = 0

    @property
    def last_error(self) -> str:
        with self._lock:
            return self._last_error

    @property
    def is_open(self) -> bool:
        with self._lock:
            process = self._process
            thread = self._thread
            is_open = self._is_open
        return bool(
            is_open
            and process is not None
            and process.poll() is None
            and thread is not None
            and thread.is_alive()
        )

    @property
    def restart_count(self) -> int:
        with self._lock:
            return self._restart_count

    @property
    def last_block_age_ms(self) -> int | None:
        with self._lock:
            last_block_at = self._last_block_at
        if last_block_at is None:
            return None
        return max(0, round((time.monotonic() - last_block_at) * 1000.0))

    def start(self, callback: AudioCaptureCallback) -> None:
        if sys.platform != "win32":
            raise RuntimeError("WASAPI process loopback is available only on Windows")
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            stale_process = self._process
            self._process = None
            self._thread = None
            self._is_open = False

        if stale_process is not None:
            self._terminate_process(stale_process)

        helper = self._resolve_helper()
        self._ensure_helper(helper)

        self._stop_event.clear()
        process, channels = self._launch_process(helper)
        thread = threading.Thread(
            target=self._supervise,
            args=(helper, process, callback, channels),
            name="wasapi-process-loopback-supervisor",
            daemon=True,
        )
        with self._lock:
            self._process = process
            self._thread = thread
            self._last_error = ""
            self._last_block_at = time.monotonic()
            self._is_open = True
        thread.start()

    def close(self) -> None:
        with self._lock:
            process = self._process
            thread = self._thread
            self._is_open = False
        self._stop_event.set()
        if process is not None:
            self._terminate_process(process)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        with self._lock:
            if self._thread is thread:
                self._process = None
                self._thread = None
                self._last_block_at = None

    def _launch_process(self, helper: Path) -> tuple[subprocess.Popen[bytes], int]:
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            [str(helper), "--exclude-pid", str(os.getpid())],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creation_flags,
        )
        assert process.stdout is not None
        header = self._read_exact(process.stdout, _HEADER.size)
        if header is None:
            error = self._stop_failed_process(process)
            raise RuntimeError(
                "WASAPI process loopback did not provide a stream header"
                + (f": {error}" if error else "")
            )

        magic, sample_rate, channels, sample_format = _HEADER.unpack(header)
        if (
            magic != _MAGIC
            or sample_format != _FLOAT32_FORMAT
            or sample_rate != self.config.sample_rate
            or channels != 2
        ):
            self._stop_failed_process(process)
            raise RuntimeError(
                "unexpected WASAPI process-loopback format: "
                f"magic={magic!r}, rate={sample_rate}, channels={channels}, "
                f"format={sample_format}"
            )
        return process, channels

    def _supervise(
        self,
        helper: Path,
        process: subprocess.Popen[bytes],
        callback: AudioCaptureCallback,
        channels: int,
    ) -> None:
        restart_delay_s = self.config.process_loopback_restart_initial_ms / 1000.0
        maximum_delay_s = self.config.process_loopback_restart_max_ms / 1000.0
        current_process = process
        current_channels = channels
        try:
            while not self._stop_event.is_set():
                error, produced_blocks = self._monitor_process(
                    current_process, callback, current_channels
                )
                if self._stop_event.is_set():
                    break

                with self._lock:
                    if self._process is current_process:
                        self._process = None
                        self._is_open = False
                    self._last_error = error

                if produced_blocks:
                    restart_delay_s = (
                        self.config.process_loopback_restart_initial_ms / 1000.0
                    )
                else:
                    restart_delay_s = min(restart_delay_s * 2.0, maximum_delay_s)

                while not self._stop_event.wait(restart_delay_s):
                    try:
                        current_process, current_channels = self._launch_process(helper)
                        break
                    except Exception as restart_error:  # noqa: BLE001
                        with self._lock:
                            self._last_error = f"WASAPI restart failed: {restart_error}"
                        restart_delay_s = min(restart_delay_s * 2.0, maximum_delay_s)
                else:
                    break

                with self._lock:
                    if self._stop_event.is_set():
                        stop_new_process = True
                    else:
                        stop_new_process = False
                        self._process = current_process
                        self._last_block_at = time.monotonic()
                        self._is_open = True
                        self._restart_count += 1
                if stop_new_process:
                    self._terminate_process(current_process)
                    break
        finally:
            self._terminate_process(current_process)
            with self._lock:
                if self._thread is threading.current_thread():
                    self._process = None
                    self._thread = None
                    self._last_block_at = None
                    self._is_open = False

    def _monitor_process(
        self,
        process: subprocess.Popen[bytes],
        callback: AudioCaptureCallback,
        channels: int,
    ) -> tuple[str, bool]:
        assert process.stdout is not None
        frames = round(self.config.sample_rate * self.config.block_ms / 1000)
        block_bytes = frames * channels * np.dtype("<f4").itemsize
        reader_done = threading.Event()
        produced_block = threading.Event()
        reader_errors: list[str] = []

        def read_pipe() -> None:
            try:
                while not self._stop_event.is_set():
                    payload = self._read_exact(process.stdout, block_bytes)
                    if payload is None:
                        reader_errors.append("PCM pipe closed")
                        break
                    block = np.frombuffer(payload, dtype="<f4").reshape(
                        frames, channels
                    )
                    with self._lock:
                        if self._process is process:
                            self._last_block_at = time.monotonic()
                            self._last_error = ""
                    produced_block.set()
                    callback(block.copy())
            except Exception as error:  # noqa: BLE001 - background adapter boundary
                reader_errors.append(str(error))
            finally:
                reader_done.set()

        reader = threading.Thread(
            target=read_pipe,
            name="wasapi-process-loopback-reader",
            daemon=True,
        )
        reader.start()
        stall_timeout_s = self.config.process_loopback_stall_timeout_ms / 1000.0
        monitor_interval_s = min(0.1, max(0.01, stall_timeout_s / 5.0))

        while not self._stop_event.is_set():
            if reader_done.wait(monitor_interval_s):
                break
            return_code = process.poll()
            if return_code is not None:
                reader_errors.append(f"helper exited with code {return_code}")
                break
            with self._lock:
                last_block_at = self._last_block_at
            if (
                last_block_at is not None
                and time.monotonic() - last_block_at > stall_timeout_s
            ):
                reader_errors.append(
                    "PCM pipe stalled for "
                    f"{self.config.process_loopback_stall_timeout_ms} ms"
                )
                break

        self._terminate_process(process)
        reader.join(timeout=2.0)
        if reader.is_alive():
            reader_errors.append("PCM reader did not stop")

        process_error = self._read_process_error(process)
        errors = [message for message in [process_error, *reader_errors] if message]
        if self._stop_event.is_set():
            return "", produced_block.is_set()
        if not errors:
            errors.append("WASAPI process loopback stopped")
        return "; ".join(dict.fromkeys(errors)), produced_block.is_set()

    @staticmethod
    def _terminate_process(process: subprocess.Popen[bytes]) -> None:
        try:
            running = process.poll() is None
        except OSError:
            running = False
        if running:
            try:
                process.terminate()
            except OSError:
                pass
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass
            try:
                process.wait(timeout=2.0)
            except (OSError, subprocess.TimeoutExpired):
                pass
        except OSError:
            pass

    def _resolve_helper(self) -> Path:
        configured = self.config.process_loopback_helper.strip()
        if configured:
            return Path(configured).expanduser().resolve()
        project_root = Path(__file__).resolve().parents[3]
        return project_root / "build" / "native" / "wasapi_process_loopback.exe"

    def _ensure_helper(self, helper: Path) -> None:
        if self.config.process_loopback_helper.strip():
            if not helper.exists():
                raise RuntimeError(f"configured WASAPI helper does not exist: {helper}")
            return

        project_root = Path(__file__).resolve().parents[3]
        build_inputs = [
            project_root / "native" / "wasapi_process_loopback" / "main.cpp",
            project_root / "utils" / "build_wasapi_process_loopback.ps1",
        ]
        rebuild = not helper.exists()
        if not rebuild:
            helper_mtime = helper.stat().st_mtime_ns
            rebuild = any(
                path.exists() and path.stat().st_mtime_ns > helper_mtime
                for path in build_inputs
            )
        if rebuild:
            self._build_helper(helper)

    @staticmethod
    def _build_helper(expected: Path) -> None:
        project_root = Path(__file__).resolve().parents[3]
        script = project_root / "utils" / "build_wasapi_process_loopback.ps1"
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                ],
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=60.0,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(
                "cannot build the WASAPI process-loopback helper; "
                "install g++ or build utils/build_wasapi_process_loopback.ps1"
            ) from error
        if result.returncode != 0 or not expected.exists():
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(
                "cannot build the WASAPI process-loopback helper"
                + (f": {detail}" if detail else "")
            )

    @staticmethod
    def _read_exact(stream, size: int) -> bytes | None:
        chunks = bytearray()
        while len(chunks) < size:
            chunk = stream.read(size - len(chunks))
            if not chunk:
                return None
            chunks.extend(chunk)
        return bytes(chunks)

    def _stop_failed_process(self, process: subprocess.Popen[bytes]) -> str:
        self._terminate_process(process)
        return self._read_process_error(process)

    @staticmethod
    def _read_process_error(process: subprocess.Popen[bytes]) -> str:
        if process.stderr is None:
            return ""
        try:
            if process.poll() is None:
                return "helper did not terminate"
        except OSError:
            return ""
        return process.stderr.read().decode("utf-8", errors="replace").strip()
