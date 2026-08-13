#!/usr/bin/env python3
"""把单个 WAV 转为 ESP32 固件使用的 8-bit/8 kHz/mono PCM 头文件。

仅使用 Python 标准库。输入 WAV 必须是未压缩 PCM（8/16/24/32 bit）。
用法：
  python wav_to_audio_header.py input.wav audio_data.h
"""

from __future__ import annotations

import argparse
import pathlib
import wave


TARGET_RATE = 8000
MAX_SECONDS = 30.0


def decode_sample(raw: bytes, offset: int, width: int) -> float:
    sample_bytes = raw[offset : offset + width]
    if width == 1:
        return (sample_bytes[0] - 128) / 128.0
    value = int.from_bytes(sample_bytes, byteorder="little", signed=True)
    return value / float(1 << (width * 8 - 1))


def decode_mono(raw: bytes, width: int, channels: int) -> list[float]:
    frame_bytes = width * channels
    mono: list[float] = []
    for frame_offset in range(0, len(raw) - frame_bytes + 1, frame_bytes):
        total = 0.0
        for channel in range(channels):
            total += decode_sample(raw, frame_offset + channel * width, width)
        mono.append(total / channels)
    return mono


def resample_linear(samples: list[float], source_rate: int) -> list[float]:
    if source_rate == TARGET_RATE:
        return samples
    output_count = max(1, round(len(samples) * TARGET_RATE / source_rate))
    result: list[float] = []
    for output_index in range(output_count):
        source_position = output_index * source_rate / TARGET_RATE
        left = min(int(source_position), len(samples) - 1)
        right = min(left + 1, len(samples) - 1)
        fraction = source_position - left
        result.append(samples[left] * (1.0 - fraction) + samples[right] * fraction)
    return result


def convert(input_path: pathlib.Path) -> bytes:
    with wave.open(str(input_path), "rb") as wav:
        if wav.getcomptype() != "NONE":
            raise ValueError("只支持未压缩 PCM WAV，请先用音频软件导出为 PCM WAV")
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        source_rate = wav.getframerate()
        frames = wav.getnframes()
        if channels < 1 or width not in (1, 2, 3, 4):
            raise ValueError(f"不支持的 WAV 格式：{channels} 声道、{width * 8} bit")
        if frames / source_rate > MAX_SECONDS:
            raise ValueError(f"音频最长 {MAX_SECONDS:.0f} 秒，请先剪短")
        raw = wav.readframes(frames)

    mono = decode_mono(raw, width, channels)
    resampled = resample_linear(mono, source_rate)

    # 去除直流、归一化到约 90%，并在首尾各做 10 ms 淡入淡出。
    if not resampled:
        raise ValueError("音频没有样本")
    average = sum(resampled) / len(resampled)
    centered = [value - average for value in resampled]
    peak = max(abs(value) for value in centered)
    gain = 0.90 / peak if peak > 0 else 1.0
    fade_samples = min(len(centered) // 2, TARGET_RATE // 100)
    output = bytearray()
    for index, value in enumerate(centered):
        fade = 1.0
        if index < fade_samples:
            fade = index / max(1, fade_samples)
        elif index >= len(centered) - fade_samples:
            fade = (len(centered) - 1 - index) / max(1, fade_samples)
        scaled = max(-1.0, min(1.0, value * gain * fade))
        output.append(max(0, min(255, round(128 + 127 * scaled))))
    return bytes(output)


def write_header(output_path: pathlib.Path, samples: bytes) -> None:
    lines = [
        "#pragma once",
        "",
        "#include <Arduino.h>",
        "",
        f"static constexpr uint32_t kAudioSampleRate = {TARGET_RATE};",
        "static constexpr bool kAudioIsDemo = false;",
        "static constexpr uint8_t kAudioSamples[] PROGMEM = {",
    ]
    for offset in range(0, len(samples), 16):
        chunk = samples[offset : offset + 16]
        lines.append("    " + ", ".join(str(value) for value in chunk) + ",")
    lines.extend(
        [
            "};",
            "static constexpr uint32_t kAudioSampleCount = sizeof(kAudioSamples);",
            "",
        ]
    )
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_wav", type=pathlib.Path)
    parser.add_argument("output_header", type=pathlib.Path, nargs="?", default="audio_data.h")
    args = parser.parse_args()
    samples = convert(args.input_wav)
    write_header(args.output_header, samples)
    print(
        f"已生成 {args.output_header}: {len(samples)} 样本，"
        f"{TARGET_RATE} Hz，{len(samples) / TARGET_RATE:.2f} 秒"
    )


if __name__ == "__main__":
    main()
