#!/usr/bin/env python3
"""Send the exact embedded PCM bytes over serial, without microphone DSP."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from vision_gimbal.audio.diagnostics import diagnostic_record, format_diagnostics
from vision_gimbal.config.loader import load_config
from vision_gimbal.domain.audio import AudioPacket
from vision_gimbal.infrastructure.serial_device_link import SerialDeviceLink
from vision_gimbal.protocol.messages import (
    AudioDrive, AudioModulation, AudioProcessing, StreamStart, StreamState,
)


def read_audio_header(path: Path) -> bytes:
    """Read generated literal data, never execute C/C++ or normalize samples."""
    text = path.read_text(encoding="utf-8-sig")
    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
    rate = re.search(r"\bkAudioSampleRate\s*=\s*(\d+)\s*;", text)
    array = re.search(r"\bkAudioSamples\s*\[\s*\]\s*(?:PROGMEM\s*)?=\s*\{([^}]*)\}", text)
    if rate is None or int(rate[1]) != 8000 or array is None:
        raise ValueError("需要 wav_to_audio_header.py 生成的 8 kHz kAudioSamples 头文件")
    body = array[1].strip().rstrip(",").strip()
    if not body or re.fullmatch(r"\d+(?:\s*,\s*\d+)*", body) is None:
        raise ValueError("kAudioSamples 必须是非空的十进制字节数组")
    return bytes(int(value.strip()) for value in body.split(","))


def packetize(samples: bytes, packet_samples: int):
    for offset in range(0, len(samples), packet_samples):
        yield AudioPacket(offset, samples[offset:offset + packet_samples])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial-port", help="required unless --inspect-only is used")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs/vision_gimbal.toml")
    parser.add_argument("--audio-header", type=Path, default=PROJECT_ROOT / "src/full_size/src/data/audio_data.h")
    parser.add_argument("--processing", choices=("raw", "loud"), default="raw")
    parser.add_argument("--drive", choices=("standard", "boost"), default="standard")
    parser.add_argument("--modulation", choices=("dsb", "sram"), default="dsb")
    parser.add_argument("--prebuffer-ms", type=int, default=120)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--log-jsonl", type=Path)
    parser.add_argument("--inspect-only", action="store_true", help="validate source and print hash without opening serial")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.inspect_only and not args.serial_port:
        parser.error("--serial-port is required for playback")
    if args.repeats < 1 or args.repeats > 100:
        raise ValueError("repeats must be in [1, 100]")
    if not 20 <= args.prebuffer_ms <= 256:
        raise ValueError("prebuffer-ms must be in [20, 256]")
    samples = read_audio_header(args.audio_header)
    parameters = StreamStart(
        prebuffer_samples=args.prebuffer_ms * 8,
        modulation=AudioModulation.SRAM if args.modulation == "sram" else AudioModulation.DSB_AM,
        processing=AudioProcessing.LOUD if args.processing == "loud" else AudioProcessing.RAW,
        drive=AudioDrive.BOOST if args.drive == "boost" else AudioDrive.STANDARD,
    )
    metadata = dict(
        event="source", path=str(args.audio_header.resolve()), samples=len(samples),
        seconds=len(samples) / 8000, sha256=hashlib.sha256(samples).hexdigest(),
        repeats=args.repeats, processing=args.processing, drive=args.drive,
        modulation=args.modulation, prebuffer_ms=args.prebuffer_ms,
    )
    print(json.dumps(metadata, ensure_ascii=False), flush=True)
    if args.inspect_only:
        return 0

    config = load_config(args.config)
    link = SerialDeviceLink(replace(config.serial, port=args.serial_port), config.audio.stream.host_queue_packets)
    log_path = args.log_jsonl or PROJECT_ROOT / "output" / (
        "audio_stream_probe_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".jsonl"
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started_at = time.monotonic()
    max_lateness_ms = 0.0
    next_report = 0.0
    last_record = None
    saw_playing = False

    with log_path.open("w", encoding="utf-8") as log:
        log.write(json.dumps(metadata, ensure_ascii=False) + "\n")

        def report(force=False):
            nonlocal next_report, last_record
            now = time.monotonic()
            if not force and now < next_report:
                return
            last_record = diagnostic_record(link.serial_status(), link.audio_status(), now - started_at)
            last_record.update(event="status", max_send_lateness_ms=round(max_lateness_ms, 3))
            print(format_diagnostics(last_record) + f" late_max_ms={max_lateness_ms:.1f}", flush=True)
            log.write(json.dumps(last_record, ensure_ascii=False) + "\n")
            log.flush()
            next_report = now + 1.0

        try:
            link.start()
            link.start_audio_stream(parameters)
            deadline = time.monotonic() + 8.0
            while not link.stream_ready:
                report()
                if time.monotonic() > deadline:
                    raise TimeoutError("STREAM_START 未确认；检查串口、固件和上面的 error")
                time.sleep(0.005)

            # Append more than one entire device buffer of silence so stopping
            # cannot truncate source audio. EOF is not treated as an underrun test.
            payload = samples * args.repeats + bytes([128]) * (2048 + parameters.packet_samples)
            sent_before = link.audio_status().host_sent_samples
            target_time = time.monotonic()
            for packet in packetize(payload, parameters.packet_samples):
                remaining = target_time - time.monotonic()
                if remaining > 0:
                    time.sleep(remaining)
                now = time.monotonic()
                max_lateness_ms = max(max_lateness_ms, (now - target_time) * 1000)
                if not link.stream_ready:
                    raise RuntimeError("传输中连接中断，停止本次对照以免混入重新建连的数据")
                status = link.audio_status()
                saw_playing = saw_playing or status.state is StreamState.PLAYING
                if status.status_age_ms is not None and status.status_age_ms > 1000:
                    raise RuntimeError("超过 1 秒未收到 STATUS，设备状态已过期")
                if status.status_age_ms is not None and status.state in {StreamState.MUTED, StreamState.FAULT}:
                    raise RuntimeError("设备已经静音或故障；检查日志中的 under/gap/skip/audio_age_ms")
                link.send_audio(packet)
                report()
                # Preserve ordinary timing jitter, but do not send a long burst
                # of stale packets after a large Windows scheduling stall.
                target_time = max(target_time + len(packet.samples) / 8000, now)

            deadline = time.monotonic() + 1.0
            # A packet leaves the queue before Serial.write finishes. Wait for
            # completed writes, not merely for an empty queue.
            while link.audio_status().host_sent_samples - sent_before < len(payload):
                if time.monotonic() > deadline:
                    raise TimeoutError("实际发送样本数不足；检查 host_drop、tx_queue 和串口状态")
                time.sleep(0.005)
            report(force=True)
            if last_record["status_age_ms"] is None:
                raise RuntimeError("设备从未返回 STATUS，不能据此判断传输正常")
            if not saw_playing and last_record["state"] != "PLAYING":
                raise RuntimeError("设备未报告 PLAYING，不能据此判断播放正常")
        except KeyboardInterrupt:
            print("已停止诊断。")
        except Exception as error:
            report(force=True)
            log.write(json.dumps(dict(event="error", error=str(error)), ensure_ascii=False) + "\n")
            print(f"诊断失败，日志：{log_path}", flush=True)
            raise
        finally:
            link.set_mute(True)
            link.stop_audio_stream()
            link.close()
    print(f"完整日志：{log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
