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
from ..config.schema import AudioConfig
from ..domain.audio import AudioPacket, AudioStreamTelemetry
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
    ) -> None:
        self.config = config
        self.microphone = microphone
        self.preprocessor = preprocessor
        self.device_link = device_link
        queue_blocks = max(1, config.capture.queue_ms // config.capture.block_ms)
        self._capture_queue: queue.Queue[NDArray[np.float32]] = queue.Queue(
            maxsize=queue_blocks
        )
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._transmitting = False
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
        try:
            self.microphone.start(self._capture_callback)
        except Exception:
            self._stop_event.set()
            if self._thread is not None:
                self._thread.join(timeout=1.0)
            with self._state_lock:
                self._thread = None
            raise
        if self.config.auto_start:
            self.start_transmitting()

    def close(self) -> None:
        if not self.config.enabled:
            return
        self.stop_transmitting()
        self.microphone.close()
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

    def start_transmitting(self) -> None:
        if not self.config.enabled:
            return
        parameters = StreamStart(
            sample_rate=self.config.stream.sample_rate,
            packet_samples=self.config.stream.packet_samples,
            prebuffer_samples=self.config.stream.prebuffer_samples,
            sample_format=AudioSampleFormat.PCM_U8,
            channels=1,
            modulation=AudioModulation.DSB_AM,
            processing=AudioProcessing.RAW,
            drive=AudioDrive.STANDARD,
            data_timeout_ms=self.config.stream.data_timeout_ms,
        )
        with self._state_lock:
            self.preprocessor.reset()
            self._clock_sync.reset()
            self._pending_pcm.clear()
            self._sample_index = 0
            self._recorder.start()
            self._transmitting = True
        try:
            self.device_link.start_audio_stream(parameters)
            self.device_link.set_mute(False)
        except Exception:
            with self._state_lock:
                self._transmitting = False
                self._pending_pcm.clear()
            self._recorder.close()
            raise

    def stop_transmitting(self) -> None:
        with self._state_lock:
            was_transmitting = self._transmitting
            self._transmitting = False
            self._pending_pcm.clear()
        self._recorder.close()
        if was_transmitting:
            self.device_link.set_mute(True)
            self.device_link.stop_audio_stream()

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
