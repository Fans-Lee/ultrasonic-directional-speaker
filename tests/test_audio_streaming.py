"""Tests for live microphone preprocessing and packetization."""

import math
import sys
import time
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from vision_gimbal.application.audio_service import AudioService
from vision_gimbal.audio.preprocessor import AudioPreprocessor
from vision_gimbal.audio.resampler import StreamingLinearResampler
from vision_gimbal.config.schema import AudioConfig
from vision_gimbal.domain.audio import AudioStreamTelemetry
from vision_gimbal.protocol.messages import StreamStart


class _Microphone:
    def __init__(self) -> None:
        self.callback = None

    def start(self, callback) -> None:
        self.callback = callback

    def close(self) -> None:
        self.callback = None


class _DeviceLink:
    def __init__(self) -> None:
        self.parameters = None
        self.packets = []
        self.mutes = []
        self.stopped = False

    def start_audio_stream(self, parameters: StreamStart) -> None:
        self.parameters = parameters

    def send_audio(self, packet) -> None:
        self.packets.append(packet)

    def stop_audio_stream(self) -> None:
        self.stopped = True

    def set_mute(self, enabled: bool) -> None:
        self.mutes.append(enabled)

    def audio_status(self) -> AudioStreamTelemetry:
        return AudioStreamTelemetry()


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


class AudioPreprocessorTests(unittest.TestCase):
    def test_emits_80_unsigned_samples_for_ten_milliseconds(self):
        config = AudioConfig(enabled=True)
        processor = AudioPreprocessor(config.capture, config.dsp, config.stream)
        time_axis = np.arange(480, dtype=np.float32) / config.capture.sample_rate
        mono = 0.1 * np.sin(2.0 * math.pi * 1000.0 * time_axis)
        stereo = np.column_stack((mono, mono)).astype(np.float32)
        result = processor.process(stereo)
        self.assertEqual(len(result.samples), 80)
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
    def test_two_capture_blocks_form_one_protocol_packet(self):
        config = replace(AudioConfig(enabled=True), auto_start=True)
        microphone = _Microphone()
        link = _DeviceLink()
        service = AudioService(
            config,
            microphone,
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


if __name__ == "__main__":
    unittest.main()
