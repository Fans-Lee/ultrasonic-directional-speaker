#!/usr/bin/env python3
"""Stream the computer microphone to the ESP32 without starting vision or Qt."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from vision_gimbal.application.audio_service import AudioService
from vision_gimbal.audio.diagnostics import diagnostic_record, format_diagnostics
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
    parser.add_argument("--log-jsonl", type=Path, help="save complete transport status once per second")
    parser.add_argument(
        "--record-output",
        type=Path,
        default=None,
        help="record post-limiter audio to a mono 8 kHz PCM16 WAV file",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    serial_config = replace(
        config.serial, port=args.serial_port, baudrate=args.baudrate
    )
    capture_config = replace(
        config.audio.capture,
        device=args.input_device if args.input_device is not None else config.audio.capture.device,
    )
    recording_config = config.audio.recording
    if args.record_output is not None:
        recording_config = replace(
            recording_config,
            enabled=True,
            path=str(args.record_output.resolve()),
        )
    audio_config = replace(
        config.audio,
        enabled=True,
        auto_start=True,
        capture=capture_config,
        recording=recording_config,
    )
    link = SerialDeviceLink(serial_config, audio_config.stream.host_queue_packets)
    service = AudioService(
        audio_config,
        SoundDeviceMicrophone(capture_config),
        AudioPreprocessor(capture_config, audio_config.dsp, audio_config.stream),
        link,
    )
    log = None
    started_at = time.monotonic()
    try:
        if args.log_jsonl is not None:
            args.log_jsonl.parent.mkdir(parents=True, exist_ok=True)
            log = args.log_jsonl.open("w", encoding="utf-8")
        link.start()
        service.start()
        print("Microphone streaming started. Press Ctrl+C to mute and stop.")
        if service.recording_path is not None:
            print(f"Post-limiter recording: {service.recording_path}")
        while True:
            time.sleep(1.0)
            serial_status = link.serial_status()
            audio_status = service.status()
            record = diagnostic_record(serial_status, audio_status, time.monotonic() - started_at)
            print(format_diagnostics(record), flush=True)
            if log is not None:
                log.write(json.dumps(record, ensure_ascii=False) + "\n")
                log.flush()
    except KeyboardInterrupt:
        return 0
    finally:
        service.close()
        link.close()
        if log is not None:
            log.close()


if __name__ == "__main__":
    raise SystemExit(main())
