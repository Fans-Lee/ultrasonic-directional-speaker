"""Capture, preprocess, packetize, and publish one selected live audio source."""

from __future__ import annotations

import queue
import threading
from collections.abc import Mapping
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
    AudioSourceKind,
    AudioStreamTelemetry,
)
from ..ports.device_link import DeviceLink
from ..ports.microphone import AudioCaptureSource
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
        sources: Mapping[AudioSourceKind, AudioCaptureSource],
        preprocessor: AudioPreprocessor,
        device_link: DeviceLink,
        spectrum: RealtimeSpectrumAnalyzer | None = None,
    ) -> None:
        self.config = config
        self.sources = dict(sources)
        if not self.sources:
            raise ValueError("at least one audio capture source is required")
        self._selected_source = AudioSourceKind(config.capture.source)
        if self._selected_source not in self.sources:
            raise ValueError(
                f"audio source {self._selected_source.value} is not configured"
            )
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
        self._active_source: AudioSourceKind | None = None
        self._source_open = False
        self._device_stream_active = False
        self._capture_generation = 0
        self._silent_samples = 0
        self._silence_threshold = 10.0 ** (
            config.activity_gate.silence_threshold_dbfs / 20.0
        )
        self._resume_threshold = 10.0 ** (
            config.activity_gate.resume_threshold_dbfs / 20.0
        )
        self._silence_release_samples = round(
            config.stream.sample_rate * config.activity_gate.release_ms / 1000
        )
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
                target=self._run, name="live-audio", daemon=True
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
            raise RuntimeError("音频链路已在配置中禁用")
        with self._state_lock:
            if self._thread is None or not self._thread.is_alive():
                raise RuntimeError("音频服务尚未启动")
            if self._transmitting:
                return
            settings = self._settings
            source_kind = self._selected_source
            source = self.sources[source_kind]
            self._capture_generation += 1
            generation = self._capture_generation
        parameters = self._stream_parameters(settings)
        gate_active = self._activity_gate_applies(source_kind)
        try:
            with self._processing_lock:
                self._clear_capture_queue()
                with self._state_lock:
                    self.preprocessor.reset()
                    self._clock_sync.reset()
                    self._pending_pcm.clear()
                    self._sample_index = 0
                    self._recorder.start()
                    self._transmitting = True
                    self._active_source = source_kind
                    self._source_open = False
                    self._device_stream_active = False
                    self._silent_samples = 0
            if gate_active:
                self.device_link.set_mute(True)
            else:
                self.device_link.start_audio_stream(parameters)
                self.device_link.set_mute(False)
                with self._state_lock:
                    self._device_stream_active = True
            source.start(
                lambda block, current_generation=generation: self._capture_callback(
                    current_generation, block
                )
            )
            with self._state_lock:
                self._source_open = True
                self._last_error = ""
            if self.spectrum is not None:
                self.spectrum.activate()
        except Exception as error:
            cleanup_errors = []
            try:
                source.close()
            except Exception as cleanup_error:  # noqa: BLE001 - rollback
                cleanup_errors.append(str(cleanup_error))
            try:
                self.device_link.set_mute(True)
                self.device_link.stop_audio_stream()
            except Exception as cleanup_error:  # noqa: BLE001 - rollback
                cleanup_errors.append(str(cleanup_error))
            with self._state_lock:
                self._transmitting = False
                self._active_source = None
                self._source_open = False
                self._device_stream_active = False
                self._capture_generation += 1
                self._silent_samples = 0
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
                active_source = self._active_source
                self._transmitting = False
                self._active_source = None
                self._source_open = False
                self._device_stream_active = False
                self._capture_generation += 1
                self._silent_samples = 0
                self._pending_pcm.clear()
            try:
                self._recorder.close()
            except Exception as error:  # noqa: BLE001 - ordered best-effort stop
                errors.append(str(error))
        if self.spectrum is not None:
            self.spectrum.deactivate()
        if active_source is not None:
            try:
                self.sources[active_source].close()
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

    def select_source(self, source: AudioSourceKind) -> None:
        """Select a capture source; an active stream is restarted safely."""
        source = AudioSourceKind(source)
        if source not in self.sources:
            raise ValueError(f"audio source {source.value} is not configured")
        with self._state_lock:
            if source is self._selected_source:
                return
            restart = self._transmitting
        if restart:
            self.stop_transmitting()
        with self._state_lock:
            self._selected_source = source
        if restart:
            self.start_transmitting()

    def record_error(self, error: Exception | str) -> None:
        with self._state_lock:
            self._last_error = str(error)

    def control_status(self) -> AudioControlStatus:
        with self._state_lock:
            transmitting = self._transmitting
            selected_source = self._selected_source
            active_source = self._active_source
            source_open = self._source_open
            array_active = self._device_stream_active
            settings = self._settings
            last_error = self._last_error
            source = self.sources.get(active_source) if active_source else None
        source_error = getattr(source, "last_error", "")
        if source_error:
            last_error = source_error
        return AudioControlStatus(
            enabled=self.config.enabled,
            transmitting=transmitting,
            selected_source=selected_source,
            active_source=active_source,
            source_open=source_open,
            array_active=array_active,
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

    def _capture_callback(
        self, generation: int, block: NDArray[np.float32]
    ) -> None:
        with self._state_lock:
            if (
                not self._transmitting
                or generation != self._capture_generation
            ):
                return
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
                if self._apply_activity_gate(processed.post_limiter_samples):
                    self._packetize(processed.samples)
                if self.spectrum is not None:
                    self.spectrum.submit(processed.post_limiter_samples)

    def _activity_gate_applies(self, source: AudioSourceKind) -> bool:
        gate = self.config.activity_gate
        return gate.enabled and (
            not gate.system_loopback_only
            or source is AudioSourceKind.SYSTEM_LOOPBACK
        )

    def _apply_activity_gate(
        self, samples: NDArray[np.float32]
    ) -> bool:
        with self._state_lock:
            source = self._active_source
            device_stream_active = self._device_stream_active
        if source is None or not self._activity_gate_applies(source):
            return device_stream_active

        values = np.asarray(samples, dtype=np.float32)
        rms = (
            float(np.sqrt(np.mean(np.square(values), dtype=np.float64)))
            if values.size
            else 0.0
        )
        if device_stream_active:
            if rms <= self._silence_threshold:
                self._silent_samples += values.size
            else:
                self._silent_samples = 0
            if self._silent_samples >= self._silence_release_samples:
                self._suspend_device_stream()
                return False
            return True

        if rms < self._resume_threshold:
            return False
        return self._resume_device_stream()

    def _suspend_device_stream(self) -> None:
        errors = []
        try:
            self.device_link.set_mute(True)
        except Exception as error:  # noqa: BLE001 - device safety boundary
            errors.append(str(error))
        try:
            self.device_link.stop_audio_stream()
        except Exception as error:  # noqa: BLE001 - device safety boundary
            errors.append(str(error))
        with self._state_lock:
            self._device_stream_active = False
            self._pending_pcm.clear()
            self._sample_index = 0
            self._silent_samples = 0
        if errors:
            self.record_error("；".join(errors))

    def _resume_device_stream(self) -> bool:
        with self._state_lock:
            if not self._transmitting:
                return False
            settings = self._settings
            self._pending_pcm.clear()
            self._sample_index = 0
            self._silent_samples = 0
            self._clock_sync.reset()
        try:
            self.device_link.start_audio_stream(
                self._stream_parameters(settings)
            )
            self.device_link.set_mute(False)
        except Exception as error:  # noqa: BLE001 - device safety boundary
            try:
                self.device_link.set_mute(True)
                self.device_link.stop_audio_stream()
            except Exception:
                pass
            self.record_error(error)
            return False
        with self._state_lock:
            self._device_stream_active = True
            self._last_error = ""
        return True

    def _stream_parameters(self, settings: AudioModeSettings) -> StreamStart:
        return StreamStart(
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
