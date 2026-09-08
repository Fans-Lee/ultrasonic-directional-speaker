#!/usr/bin/env python3
"""Stream the computer microphone to the ESP32 without starting vision or Qt."""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from vision_gimbal.application.audio_service import AudioService
from vision_gimbal.audio.preprocessor import AudioPreprocessor
from vision_gimbal.config.loader import load_config
from vision_gimbal.infrastructure.serial_device_link import SerialDeviceLink
from vision_gimbal.infrastructure.sounddevice_microphone import SoundDeviceMicrophone


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stream 8 kHz PCM_U8 microphone audio to the ultrasonic firmware"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs" / "vision_gimbal.toml",
    )
    parser.add_argument("--serial-port", required=True, help="ESP32 COM port")
    parser.add_argument("--baudrate", type=int, default=460800)
    parser.add_argument("--input-device", default=None)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    serial_config = replace(
        config.serial, port=args.serial_port, baudrate=args.baudrate
    )
    capture_config = replace(
        config.audio.capture,
        device=args.input_device if args.input_device is not None else None,
    )
    audio_config = replace(
        config.audio,
        enabled=True,
        auto_start=True,
        capture=capture_config,
    )
    link = SerialDeviceLink(serial_config, audio_config.stream.host_queue_packets)
    service = AudioService(
        audio_config,
        SoundDeviceMicrophone(capture_config),
        AudioPreprocessor(capture_config, audio_config.dsp, audio_config.stream),
        link,
    )
    link.start()
    try:
        service.start()
        print("Microphone streaming started. Press Ctrl+C to mute and stop.")
        while True:
            time.sleep(1.0)
            serial_status = link.serial_status()
            audio_status = service.status()
            print(
                f"connected={serial_status.connected} "
                f"state={audio_status.state.name} "
                f"buffer={audio_status.buffer_fill_samples}/"
                f"{audio_status.buffer_capacity_samples} "
                f"under={audio_status.underrun_count} "
                f"over={audio_status.overrun_count} "
                f"host_drop={audio_status.host_tx_overrun_count}",
                flush=True,
            )
    except KeyboardInterrupt:
        return 0
    finally:
        service.close()
        link.close()


if __name__ == "__main__":
    raise SystemExit(main())
