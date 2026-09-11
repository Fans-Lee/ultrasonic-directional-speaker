"""Capture, preprocess, packetize, and publish live microphone audio."""

from __future__ import annotations

import queue
import threading
from dataclasses import replace
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from ..audio.clock_sync import BufferClockSync
from ..audio.preprocessor import AudioPreprocessor
from ..audio.recording import PostLimiterWavRecorder
from ..audio.spectrum import AudioSpectrumSnapshot, RealtimeSpectrumAnalyzer
from ..config.schema import AudioConfig
from ..domain.audio import (
    AudioControlStatus,
    AudioDriveMode,
    AudioModeSettings,
    AudioModulationMode,
    AudioPacket,
    AudioProcessingMode,
    AudioStreamTelemetry,
)
from ..ports.device_link import DeviceLink
from ..ports.microphone import MicrophoneSource
from ..protocol.messages import (
    AudioDrive,
    AudioModulation,
    AudioProcessing,
    AudioSampleFormat,
    StreamStart,
    StreamState,
)


class AudioService:
    def __init__(
        self,
        config: AudioConfig,
        microphone: MicrophoneSource,
        preprocessor: AudioPreprocessor,
        device_link: DeviceLink,
        spectrum: RealtimeSpectrumAnalyzer | None = None,
    ) -> None:
        self.config = config
        self.microphone = microphone
        self.preprocessor = preprocessor
        self.device_link = device_link
        self.spectrum = spectrum
        queue_blocks = max(1, config.capture.queue_ms // config.capture.block_ms)
        self._capture_queue: queue.Queue[NDArray[np.float32]] = queue.Queue(
            maxsize=queue_blocks
        )
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._processing_lock = threading.Lock()
        self._transmitting = False
        self._microphone_open = False
        self._last_error = ""
        self._settings = AudioModeSettings(
            processing=AudioProcessingMode(config.stream.processing.lower()),
            drive=(
                AudioDriveMode.BOOST
                if config.stream.boost
                else AudioDriveMode.STANDARD
            ),
            modulation=AudioModulationMode(
                config.stream.modulation.lower().replace("-", "_")
            ),
        )
        self._pending_pcm = bytearray()
        self._sample_index = 0
        self._capture_overrun_count = 0
        self._quantizer_clip_count = 0
        self._clock_sync = BufferClockSync(config.stream.prebuffer_samples)
        self._recorder = PostLimiterWavRecorder(
            config.recording, config.stream.sample_rate
        )

    @property
    def recording_path(self) -> Path | None:
        return self._recorder.current_path

    @property
    def spectrum_refresh_hz(self) -> float:
        return self.spectrum.refresh_hz if self.spectrum is not None else 10.0

    def spectrum_snapshot(self) -> AudioSpectrumSnapshot | None:
        if self.spectrum is None or not self.spectrum.enabled:
            return None
        return self.spectrum.snapshot()

    def start(self) -> None:
        if not self.config.enabled:
            return
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run, name="microphone-audio", daemon=True
            )
            self._thread.start()
        if self.spectrum is not None:
            self.spectrum.start()
        if self.config.auto_start:
            self.start_transmitting()

    def close(self) -> None:
        if not self.config.enabled:
            return
        self.stop_transmitting()
        self._stop_event.set()
        try:
            self._capture_queue.put_nowait(np.empty(0, dtype=np.float32))
        except queue.Full:
            pass
        with self._state_lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        with self._state_lock:
            self._thread = None
        if self.spectrum is not None:
            self.spectrum.close()

    def start_transmitting(self) -> None:
        if not self.config.enabled:
            raise RuntimeError("麦克风链路已在配置中禁用")
        with self._state_lock:
            if self._thread is None or not self._thread.is_alive():
                raise RuntimeError("音频服务尚未启动")
            if self._transmitting:
                return
            settings = self._settings
        parameters = StreamStart(
            sample_rate=self.config.stream.sample_rate,
            packet_samples=self.config.stream.packet_samples,
            prebuffer_samples=self.config.stream.prebuffer_samples,
            sample_format=AudioSampleFormat.PCM_U8,
            channels=1,
            modulation=(
                AudioModulation.SRAM
                if settings.modulation is AudioModulationMode.SRAM
                else AudioModulation.DSB_AM
            ),
            processing=(
                AudioProcessing.LOUD
                if settings.processing is AudioProcessingMode.LOUD
                else AudioProcessing.RAW
            ),
            drive=(
                AudioDrive.BOOST
                if settings.drive is AudioDriveMode.BOOST
                else AudioDrive.STANDARD
            ),
            data_timeout_ms=self.config.stream.data_timeout_ms,
        )
        try:
            with self._processing_lock:
                self._clear_capture_queue()
                with self._state_lock:
                    self.preprocessor.reset()
                    self._clock_sync.reset()
                    self._pending_pcm.clear()
                    self._sample_index = 0
                    self._recorder.start()
            self.device_link.start_audio_stream(parameters)
            self.device_link.set_mute(False)
            self.microphone.start(self._capture_callback)
            with self._state_lock:
                self._transmitting = True
                self._microphone_open = True
                self._last_error = ""
            if self.spectrum is not None:
                self.spectrum.activate()
        except Exception as error:
            cleanup_errors = []
            try:
                self.microphone.close()
            except Exception as cleanup_error:  # noqa: BLE001 - rollback
                cleanup_errors.append(str(cleanup_error))
            try:
                self.device_link.set_mute(True)
                self.device_link.stop_audio_stream()
            except Exception as cleanup_error:  # noqa: BLE001 - rollback
                cleanup_errors.append(str(cleanup_error))
            with self._state_lock:
                self._transmitting = False
                self._microphone_open = False
                self._pending_pcm.clear()
                self._last_error = "；".join([str(error), *cleanup_errors])
            try:
                self._recorder.close()
            except Exception:  # noqa: BLE001 - preserve original startup error
                pass
            if self.spectrum is not None:
                self.spectrum.deactivate()
            raise

    def stop_transmitting(self) -> None:
        errors = []
        with self._processing_lock:
            with self._state_lock:
                was_transmitting = self._transmitting
                self._transmitting = False
                self._microphone_open = False
                self._pending_pcm.clear()
            try:
                self._recorder.close()
            except Exception as error:  # noqa: BLE001 - ordered best-effort stop
                errors.append(str(error))
        if self.spectrum is not None:
            self.spectrum.deactivate()
        try:
            self.microphone.close()
        except Exception as error:  # noqa: BLE001 - ordered best-effort stop
            errors.append(str(error))
        if was_transmitting:
            try:
                self.device_link.set_mute(True)
            except Exception as error:  # noqa: BLE001 - ordered best-effort stop
                errors.append(str(error))
            try:
                self.device_link.stop_audio_stream()
            except Exception as error:  # noqa: BLE001 - ordered best-effort stop
                errors.append(str(error))
        if errors:
            self.record_error("；".join(errors))

    def configure(self, settings: AudioModeSettings) -> None:
        """Apply modes now; an active stream is restarted with new parameters."""
        if not isinstance(settings, AudioModeSettings):
            raise TypeError("settings must be AudioModeSettings")
        with self._state_lock:
            if settings == self._settings:
                return
            restart = self._transmitting
        if restart:
            self.stop_transmitting()
        with self._state_lock:
            self._settings = settings
        if restart:
            self.start_transmitting()

    def record_error(self, error: Exception | str) -> None:
        with self._state_lock:
            self._last_error = str(error)

    def control_status(self) -> AudioControlStatus:
        with self._state_lock:
            transmitting = self._transmitting
            microphone_open = self._microphone_open
            settings = self._settings
            last_error = self._last_error
        return AudioControlStatus(
            enabled=self.config.enabled,
            transmitting=transmitting,
            microphone_open=microphone_open,
            settings=settings,
            telemetry=self.status(),
            last_error=last_error,
        )

    def status(self) -> AudioStreamTelemetry:
        status = self.device_link.audio_status()
        return replace(
            status,
            host_capture_overrun_count=self._capture_overrun_count,
            quantizer_clip_count=self._quantizer_clip_count,
        )

    def _capture_callback(self, block: NDArray[np.float32]) -> None:
        try:
            self._capture_queue.put_nowait(block)
            return
        except queue.Full:
            self._capture_overrun_count += 1
        try:
            self._capture_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self._capture_queue.put_nowait(block)
        except queue.Full:
            self._capture_overrun_count += 1

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                block = self._capture_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if block.size == 0 and self._stop_event.is_set():
                break
            with self._processing_lock:
                with self._state_lock:
                    transmitting = self._transmitting
                if not transmitting:
                    continue
                device_status = self.device_link.audio_status()
                correction_ppm = (
                    self._clock_sync.update(
                        device_status.buffer_fill_samples,
                        device_status.buffer_capacity_samples,
                    )
                    if device_status.state is StreamState.PLAYING
                    else 0.0
                )
                if device_status.state is not StreamState.PLAYING:
                    self._clock_sync.reset()
                self.preprocessor.set_rate_correction_ppm(correction_ppm)
                processed = self.preprocessor.process(block)
                self._quantizer_clip_count += processed.clipped_samples
                self._recorder.write(processed.post_limiter_samples)
                self._packetize(processed.samples)
                if self.spectrum is not None:
                    self.spectrum.submit(processed.post_limiter_samples)

    def _clear_capture_queue(self) -> None:
        while True:
            try:
                self._capture_queue.get_nowait()
            except queue.Empty:
                return

    def _packetize(self, samples: bytes) -> None:
        packet_samples = self.config.stream.packet_samples
        with self._state_lock:
            if not self._transmitting:
                return
            self._pending_pcm.extend(samples)
            packets: list[AudioPacket] = []
            while len(self._pending_pcm) >= packet_samples:
                payload = bytes(self._pending_pcm[:packet_samples])
                del self._pending_pcm[:packet_samples]
                packets.append(AudioPacket(self._sample_index, payload))
                self._sample_index = (self._sample_index + packet_samples) & 0xFFFFFFFF
        for packet in packets:
            self.device_link.send_audio(packet)
