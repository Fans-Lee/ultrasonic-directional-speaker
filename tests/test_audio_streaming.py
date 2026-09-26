"""Tests for live audio source preprocessing, switching, and packetization."""

import math
import sys
import threading
import time
import unittest
import wave
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from vision_gimbal.application.audio_service import AudioService
from vision_gimbal.audio.preprocessor import AudioPreprocessor
from vision_gimbal.audio.recording import PostLimiterWavRecorder
from vision_gimbal.audio.resampler import StreamingLinearResampler
from vision_gimbal.config.loader import load_config
from vision_gimbal.config.schema import (
    AudioCaptureConfig,
    AudioConfig,
    AudioRecordingConfig,
    AudioVolumeConfig,
)
from vision_gimbal.domain.audio import (
    AudioDriveMode,
    AudioModeSettings,
    AudioModulationMode,
    AudioProcessingMode,
    AudioSourceKind,
    AudioStreamTelemetry,
)
from vision_gimbal.infrastructure.wasapi_process_loopback import (
    WasapiProcessLoopbackSource,
)
from vision_gimbal.protocol.messages import (
    AudioDrive,
    AudioModulation,
    AudioProcessing,
    StreamStart,
    StreamState,
)


class _Microphone:
    def __init__(self) -> None:
        self.callback = None
        self.start_count = 0
        self.close_count = 0

    def start(self, callback) -> None:
        self.callback = callback
        self.start_count += 1

    def close(self) -> None:
        self.callback = None
        self.close_count += 1


class _DeviceLink:
    def __init__(self) -> None:
        self.parameters = None
        self.parameter_history = []
        self.packets = []
        self.mutes = []
        self.volumes = []
        self.stopped = False
        self.stop_count = 0
        self.telemetry = AudioStreamTelemetry()

    def start_audio_stream(self, parameters: StreamStart) -> None:
        self.parameters = parameters
        self.parameter_history.append(parameters)

    def send_audio(self, packet) -> None:
        self.packets.append(packet)

    def stop_audio_stream(self) -> None:
        self.stopped = True
        self.stop_count += 1

    def set_mute(self, enabled: bool) -> None:
        self.mutes.append(enabled)

    def set_volume(self, permille: int) -> None:
        self.volumes.append(permille)

    def audio_status(self) -> AudioStreamTelemetry:
        return self.telemetry


class _BlockingPipe:
    def __init__(self) -> None:
        self.released = threading.Event()

    def read(self, _size: int) -> bytes:
        self.released.wait(timeout=2.0)
        return b""


class _FakeProcess:
    def __init__(self, *, blocking_stdout: bool = False) -> None:
        self.stdout = _BlockingPipe() if blocking_stdout else BytesIO()
        self.stderr = BytesIO()
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -15
        if isinstance(self.stdout, _BlockingPipe):
            self.stdout.released.set()

    def kill(self) -> None:
        self.terminate()

    def wait(self, timeout=None):
        del timeout
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class _RecoveringLoopbackSource(WasapiProcessLoopbackSource):
    def __init__(self, config: AudioCaptureConfig) -> None:
        super().__init__(config)
        self.launch_count = 0
        self.monitor_count = 0

    def _resolve_helper(self) -> Path:
        return Path(__file__)

    def _ensure_helper(self, helper: Path) -> None:
        del helper

    def _launch_process(self, helper: Path):
        del helper
        self.launch_count += 1
        return _FakeProcess(), 2

    def _monitor_process(self, process, callback, channels):
        del callback, channels
        self.monitor_count += 1
        if self.monitor_count == 1:
            self._terminate_process(process)
            return "simulated EOF", True
        self._stop_event.wait(timeout=2.0)
        return "", True


class _SpectrumAnalyzer:
    enabled = True
    refresh_hz = 10.0

    def __init__(self) -> None:
        self.start_count = 0
        self.activate_count = 0
        self.deactivate_count = 0
        self.close_count = 0
        self.blocks = []

    def start(self) -> None:
        self.start_count += 1

    def activate(self) -> None:
        self.activate_count += 1

    def deactivate(self) -> None:
        self.deactivate_count += 1

    def submit(self, samples) -> None:
        self.blocks.append(np.asarray(samples).copy())

    def snapshot(self):
        return None

    def close(self) -> None:
        self.close_count += 1


class StreamingResamplerTests(unittest.TestCase):
    def test_preserves_output_count_across_arbitrary_blocks(self):
        source = np.linspace(-1.0, 1.0, 4800, dtype=np.float32)
        resampler = StreamingLinearResampler(48000, 8000)
        chunks = [source[:137], source[137:911], source[911:3000], source[3000:]]
        output = np.concatenate([resampler.process(chunk) for chunk in chunks])
        self.assertEqual(output.size, 800)
        self.assertAlmostEqual(float(output[0]), -1.0, places=5)

    def test_supports_44100_hz_blocks(self):
        resampler = StreamingLinearResampler(44100, 8000)
        first = resampler.process(np.zeros(441, dtype=np.float32))
        second = resampler.process(np.zeros(441, dtype=np.float32))
        self.assertEqual(first.size, 80)
        self.assertEqual(second.size, 80)


class WasapiProcessLoopbackSourceTests(unittest.TestCase):
    def test_supervisor_restarts_helper_after_unexpected_eof(self):
        config = replace(
            AudioCaptureConfig(),
            process_loopback_restart_initial_ms=10,
            process_loopback_restart_max_ms=20,
        )
        source = _RecoveringLoopbackSource(config)

        with patch(
            "vision_gimbal.infrastructure.wasapi_process_loopback.sys.platform",
            "win32",
        ):
            source.start(lambda _block: None)
            deadline = time.monotonic() + 1.0
            while source.restart_count == 0 and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(source.launch_count, 2)
            self.assertEqual(source.restart_count, 1)
            self.assertTrue(source.is_open)
            source.close()

        self.assertFalse(source.is_open)

    def test_monitor_terminates_helper_when_pcm_pipe_stalls(self):
        config = replace(AudioCaptureConfig(), process_loopback_stall_timeout_ms=100)
        source = WasapiProcessLoopbackSource(config)
        process = _FakeProcess(blocking_stdout=True)
        with source._lock:
            source._process = process
            source._last_block_at = time.monotonic()

        error, produced_blocks = source._monitor_process(
            process, lambda _block: None, 2
        )

        self.assertIn("PCM pipe stalled for 100 ms", error)
        self.assertFalse(produced_blocks)
        self.assertIsNotNone(process.poll())


class AudioPreprocessorTests(unittest.TestCase):
    def test_emits_80_unsigned_samples_for_ten_milliseconds(self):
        config = AudioConfig(enabled=True)
        processor = AudioPreprocessor(config.capture, config.dsp, config.stream)
        time_axis = np.arange(480, dtype=np.float32) / config.capture.sample_rate
        mono = 0.1 * np.sin(2.0 * math.pi * 1000.0 * time_axis)
        stereo = np.column_stack((mono, mono)).astype(np.float32)
        result = processor.process(stereo)
        self.assertEqual(len(result.samples), 80)
        self.assertEqual(result.post_limiter_samples.size, 80)
        self.assertTrue(all(0 <= value <= 255 for value in result.samples))

    def test_dc_input_decays_toward_silence_code(self):
        config = AudioConfig(enabled=True)
        processor = AudioPreprocessor(config.capture, config.dsp, config.stream)
        results = []
        for _ in range(50):
            results.append(
                processor.process(np.full((480, 1), 0.25, dtype=np.float32)).samples
            )
        tail = np.frombuffer(results[-1], dtype=np.uint8)
        self.assertLess(float(np.mean(np.abs(tail.astype(float) - 128.0))), 1.0)


class AudioServiceTests(unittest.TestCase):
    def test_volume_config_rejects_out_of_range_values(self):
        self.assertEqual(AudioVolumeConfig().default_percent, 50)
        for invalid in (-1, 101, True, 25.5):
            with self.assertRaises(ValueError):
                AudioVolumeConfig(default_percent=invalid)

    def test_volume_changes_do_not_restart_live_stream(self):
        config = replace(AudioConfig(enabled=True), auto_start=False)
        microphone = _Microphone()
        link = _DeviceLink()
        service = AudioService(
            config,
            {AudioSourceKind.MICROPHONE: microphone},
            AudioPreprocessor(config.capture, config.dsp, config.stream),
            link,
        )
        service.start()
        service.start_transmitting()
        service.set_volume(25)
        service.set_volume(0)
        self.assertEqual(link.volumes, [500, 250, 0])
        self.assertEqual(service.control_status().volume_percent, 0)
        self.assertEqual(len(link.parameter_history), 1)
        self.assertEqual(microphone.start_count, 1)
        service.close()

    def test_audio_mode_settings_normalize_string_values_from_qt(self):
        settings = AudioModeSettings(
            processing="loud",
            drive="boost",
            modulation="sram",
        )

        self.assertIs(settings.processing, AudioProcessingMode.LOUD)
        self.assertIs(settings.drive, AudioDriveMode.BOOST)
        self.assertIs(settings.modulation, AudioModulationMode.SRAM)

    def test_manual_start_stop_and_live_mode_change_own_microphone_lifecycle(self):
        stream = replace(
            AudioConfig().stream,
            processing="loud",
            boost=True,
            modulation="sram",
        )
        config = replace(AudioConfig(enabled=True), auto_start=False, stream=stream)
        microphone = _Microphone()
        link = _DeviceLink()
        service = AudioService(
            config,
            {AudioSourceKind.MICROPHONE: microphone},
            AudioPreprocessor(config.capture, config.dsp, config.stream),
            link,
        )

        service.start()
        self.assertIsNone(microphone.callback)
        self.assertFalse(service.control_status().transmitting)

        service.start_transmitting()
        self.assertIsNotNone(microphone.callback)
        self.assertEqual(link.parameters.processing, AudioProcessing.LOUD)
        self.assertEqual(link.parameters.drive, AudioDrive.BOOST)
        self.assertEqual(link.parameters.modulation, AudioModulation.SRAM)

        service.configure(
            AudioModeSettings(
                processing=AudioProcessingMode.RAW,
                drive=AudioDriveMode.STANDARD,
                modulation=AudioModulationMode.DSB_AM,
            )
        )
        self.assertEqual(len(link.parameter_history), 2)
        self.assertEqual(link.parameters.processing, AudioProcessing.RAW)
        self.assertEqual(link.parameters.drive, AudioDrive.STANDARD)
        self.assertEqual(link.parameters.modulation, AudioModulation.DSB_AM)
        self.assertEqual(microphone.start_count, 2)

        service.stop_transmitting()
        self.assertIsNone(microphone.callback)
        self.assertFalse(service.control_status().microphone_open)
        self.assertTrue(link.stopped)
        service.close()

    def test_live_source_change_closes_old_source_and_restarts_stream(self):
        config = replace(AudioConfig(enabled=True), auto_start=False)
        microphone = _Microphone()
        stereo_mix = _Microphone()
        link = _DeviceLink()
        service = AudioService(
            config,
            {
                AudioSourceKind.MICROPHONE: microphone,
                AudioSourceKind.STEREO_MIX: stereo_mix,
            },
            AudioPreprocessor(config.capture, config.dsp, config.stream),
            link,
        )

        service.start()
        service.start_transmitting()
        stale_callback = microphone.callback
        service.select_source(AudioSourceKind.STEREO_MIX)

        status = service.control_status()
        self.assertIs(status.selected_source, AudioSourceKind.STEREO_MIX)
        self.assertIs(status.active_source, AudioSourceKind.STEREO_MIX)
        self.assertTrue(status.source_open)
        self.assertEqual(microphone.close_count, 1)
        self.assertIsNone(microphone.callback)
        self.assertIsNotNone(stereo_mix.callback)
        self.assertEqual(len(link.parameter_history), 2)

        stale_callback(np.ones((480, 1), dtype=np.float32))
        stereo_mix.callback(np.zeros((480, 2), dtype=np.float32))
        stereo_mix.callback(np.zeros((480, 2), dtype=np.float32))
        deadline = time.monotonic() + 1.0
        while not link.packets and time.monotonic() < deadline:
            time.sleep(0.01)
        service.close()

        self.assertTrue(link.packets)
        self.assertEqual(set(link.packets[-1].samples), {128})

    def test_two_capture_blocks_form_one_protocol_packet(self):
        config = replace(AudioConfig(enabled=True), auto_start=True)
        microphone = _Microphone()
        link = _DeviceLink()
        service = AudioService(
            config,
            {AudioSourceKind.MICROPHONE: microphone},
            AudioPreprocessor(config.capture, config.dsp, config.stream),
            link,
        )
        service.start()
        self.assertIsNotNone(microphone.callback)
        block = np.zeros((480, 1), dtype=np.float32)
        microphone.callback(block)
        microphone.callback(block)
        deadline = time.monotonic() + 1.0
        while not link.packets and time.monotonic() < deadline:
            time.sleep(0.01)
        service.close()

        self.assertEqual(link.parameters.packet_samples, 160)
        self.assertTrue(link.packets)
        self.assertEqual(link.packets[0].sample_index, 0)
        self.assertEqual(len(link.packets[0].samples), 160)
        self.assertEqual(set(link.packets[0].samples), {128})
        self.assertEqual(link.mutes[0], False)
        self.assertEqual(link.mutes[-1], True)
        self.assertTrue(link.stopped)

    def test_system_loopback_activity_gate_stops_silent_carrier_and_resumes(self):
        base = AudioConfig(enabled=True)
        config = replace(
            base,
            auto_start=True,
            capture=replace(base.capture, source="system_loopback"),
            activity_gate=replace(base.activity_gate, release_ms=20),
        )
        system_loopback = _Microphone()
        link = _DeviceLink()
        service = AudioService(
            config,
            {AudioSourceKind.SYSTEM_LOOPBACK: system_loopback},
            AudioPreprocessor(config.capture, config.dsp, config.stream),
            link,
        )

        service.start()
        self.assertIsNotNone(system_loopback.callback)
        self.assertEqual(link.parameter_history, [])
        self.assertFalse(service.control_status().array_active)

        phase = np.arange(480, dtype=np.float32) / 48000.0
        active = np.sin(2.0 * math.pi * 1000.0 * phase).astype(np.float32)
        active = np.column_stack((active, active)) * 0.2
        for _ in range(2):
            system_loopback.callback(active)
        deadline = time.monotonic() + 1.0
        while not link.parameter_history and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(service.control_status().array_active)

        silence = np.zeros((480, 2), dtype=np.float32)
        for _ in range(50):
            system_loopback.callback(silence)
        deadline = time.monotonic() + 1.0
        while link.stop_count == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertGreaterEqual(link.stop_count, 1)
        self.assertFalse(service.control_status().array_active)

        for _ in range(2):
            system_loopback.callback(active)
        deadline = time.monotonic() + 1.0
        while len(link.parameter_history) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        service.close()

        self.assertGreaterEqual(len(link.parameter_history), 2)

    def test_fresh_muted_device_status_rearms_an_active_host_stream(self):
        config = replace(AudioConfig(enabled=True), auto_start=True)
        microphone = _Microphone()
        link = _DeviceLink()
        link.telemetry = AudioStreamTelemetry(
            state=StreamState.MUTED,
            muted=True,
            status_age_ms=0,
        )
        service = AudioService(
            config,
            {AudioSourceKind.MICROPHONE: microphone},
            AudioPreprocessor(config.capture, config.dsp, config.stream),
            link,
        )

        service.start()
        with service._state_lock:
            service._device_stream_started_at = time.monotonic() - 2.0
        block = np.zeros((480, 1), dtype=np.float32)
        microphone.callback(block)
        microphone.callback(block)
        deadline = time.monotonic() + 1.0
        while len(link.parameter_history) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        service.close()

        self.assertEqual(len(link.parameter_history), 2)
        self.assertGreaterEqual(link.mutes.count(False), 2)

    def test_spectrum_tap_follows_audio_lifecycle(self):
        config = replace(AudioConfig(enabled=True), auto_start=True)
        microphone = _Microphone()
        link = _DeviceLink()
        spectrum = _SpectrumAnalyzer()
        service = AudioService(
            config,
            {AudioSourceKind.MICROPHONE: microphone},
            AudioPreprocessor(config.capture, config.dsp, config.stream),
            link,
            spectrum,
        )

        service.start()
        microphone.callback(np.zeros((480, 1), dtype=np.float32))
        microphone.callback(np.zeros((480, 1), dtype=np.float32))
        deadline = time.monotonic() + 1.0
        while not spectrum.blocks and time.monotonic() < deadline:
            time.sleep(0.01)
        service.close()

        self.assertEqual(spectrum.start_count, 1)
        self.assertEqual(spectrum.activate_count, 1)
        self.assertTrue(spectrum.blocks)
        self.assertEqual(spectrum.blocks[0].size, 80)
        self.assertGreaterEqual(spectrum.deactivate_count, 1)
        self.assertEqual(spectrum.close_count, 1)

    def test_records_post_limiter_signal_as_pcm16_wav(self):
        with TemporaryDirectory() as directory:
            recording = AudioRecordingConfig(
                enabled=True,
                path=str(Path(directory) / "processed_{timestamp}.wav"),
            )
            config = replace(
                AudioConfig(enabled=True), auto_start=True, recording=recording
            )
            microphone = _Microphone()
            link = _DeviceLink()
            service = AudioService(
                config,
                {AudioSourceKind.MICROPHONE: microphone},
                AudioPreprocessor(config.capture, config.dsp, config.stream),
                link,
            )

            service.start()
            block = np.zeros((480, 1), dtype=np.float32)
            microphone.callback(block)
            microphone.callback(block)
            deadline = time.monotonic() + 1.0
            while not link.packets and time.monotonic() < deadline:
                time.sleep(0.01)
            recording_path = service.recording_path
            service.close()

            self.assertIsNotNone(recording_path)
            self.assertTrue(recording_path.exists())
            with wave.open(str(recording_path), "rb") as stream:
                self.assertEqual(stream.getnchannels(), 1)
                self.assertEqual(stream.getsampwidth(), 2)
                self.assertEqual(stream.getframerate(), 8000)
                self.assertEqual(stream.getnframes(), 160)


class PostLimiterWavRecorderTests(unittest.TestCase):
    def test_converts_normalized_float_samples_to_pcm16(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "monitor.wav"
            recorder = PostLimiterWavRecorder(
                AudioRecordingConfig(enabled=True, path=str(path)), 8000
            )
            self.assertEqual(recorder.start(), path)
            recorder.write(np.array([-0.5, 0.0, 0.5], dtype=np.float32))
            recorder.close()

            with wave.open(str(path), "rb") as stream:
                frames = stream.readframes(stream.getnframes())
            values = np.frombuffer(frames, dtype="<i2")
            np.testing.assert_array_equal(values, [-16384, 0, 16384])

    def test_loader_resolves_recording_path_from_config_directory(self):
        with TemporaryDirectory() as directory:
            config_path = Path(directory) / "app.toml"
            config_path.write_text(
                '[audio.recording]\nenabled = true\npath = "records/test.wav"\n',
                encoding="utf-8",
            )

            config = load_config(config_path)

            self.assertTrue(config.audio.recording.enabled)
            self.assertEqual(
                Path(config.audio.recording.path),
                (config_path.parent / "records" / "test.wav").resolve(),
            )


if __name__ == "__main__":
    unittest.main()
