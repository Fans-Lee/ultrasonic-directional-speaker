#pragma once

#include <Arduino.h>

// 本文件可由 wav_to_audio_header.py 覆盖生成。
// 当前使用固件内置的 2 秒测试旋律，确保工程开箱即可编译和试播。
static constexpr uint32_t kAudioSampleRate = 8000;
static constexpr bool kAudioIsDemo = true;
static constexpr uint8_t kAudioSamples[] PROGMEM = {128};
static constexpr uint32_t kAudioSampleCount = 2 * kAudioSampleRate;
