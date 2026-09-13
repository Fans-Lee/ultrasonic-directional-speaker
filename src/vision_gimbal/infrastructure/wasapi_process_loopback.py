"""Windows process-loopback capture that is independent of output endpoints."""

from __future__ import annotations

import os
import struct
import subprocess
import sys
import threading
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

    @property
    def last_error(self) -> str:
        with self._lock:
            return self._last_error

    def start(self, callback: AudioCaptureCallback) -> None:
        if sys.platform != "win32":
            raise RuntimeError("WASAPI process loopback is available only on Windows")
        with self._lock:
            if self._process is not None:
                return

        helper = self._resolve_helper()
        if not helper.exists():
            self._build_helper(helper)

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

        self._stop_event.clear()
        thread = threading.Thread(
            target=self._read_loop,
            args=(process, callback, channels),
            name="wasapi-process-loopback",
            daemon=True,
        )
        with self._lock:
            self._process = process
            self._thread = thread
            self._last_error = ""
        thread.start()

    def close(self) -> None:
        with self._lock:
            process = self._process
            thread = self._thread
            self._process = None
            self._thread = None
        self._stop_event.set()
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def _read_loop(
        self,
        process: subprocess.Popen[bytes],
        callback: AudioCaptureCallback,
        channels: int,
    ) -> None:
        assert process.stdout is not None
        frames = round(self.config.sample_rate * self.config.block_ms / 1000)
        block_bytes = frames * channels * np.dtype("<f4").itemsize
        try:
            while not self._stop_event.is_set():
                payload = self._read_exact(process.stdout, block_bytes)
                if payload is None:
                    break
                block = np.frombuffer(payload, dtype="<f4").reshape(
                    frames, channels
                )
                callback(block.copy())
        except Exception as error:  # noqa: BLE001 - background adapter boundary
            with self._lock:
                self._last_error = str(error)
        finally:
            if not self._stop_event.is_set():
                error = self._read_process_error(process)
                with self._lock:
                    self._last_error = error or "WASAPI process loopback stopped"

    def _resolve_helper(self) -> Path:
        configured = self.config.process_loopback_helper.strip()
        if configured:
            return Path(configured).expanduser().resolve()
        project_root = Path(__file__).resolve().parents[3]
        return project_root / "build" / "native" / "wasapi_process_loopback.exe"

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
        process.terminate()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2.0)
        return self._read_process_error(process)

    @staticmethod
    def _read_process_error(process: subprocess.Popen[bytes]) -> str:
        if process.stderr is None:
            return ""
        return process.stderr.read().decode("utf-8", errors="replace").strip()
