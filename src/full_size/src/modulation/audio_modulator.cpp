#include "audio_modulator.h"

#include <Arduino.h>
#include <math.h>

#include "../data/audio_data.h"

namespace ultrasonic {
namespace {

constexpr float kStandardCarrierBase = 0.45f;
constexpr float kStandardModulationDepth = 0.40f;
// BOOST 把包络范围由 0.05..0.85 扩展到 0.02..0.98。
// 理想 Berktay 线性项相对 STANDARD 增加约 2.5 dB (DSB) / 2.8 dB (SRAM)。
constexpr float kBoostCarrierBase = 0.50f;
constexpr float kBoostModulationDepth = 0.48f;
// 小信号约提升 6 倍，接近满幅时逐渐压缩到 1，避免包络越界。
// 对当前内置 PCM 的整体 RMS 提升约 8 dB；2/128 的门限抑制静音底噪。
constexpr float kLoudnessSmallSignalGain = 6.0f;
constexpr float kLoudnessNoiseGate = 2.0f / 128.0f;

}  // namespace

bool AudioModulator::begin(const DutyConfig& dutyConfig) {
  const bool standardDsbReady = standardDsbAmModulator_.begin(
      dutyConfig, kStandardCarrierBase, kStandardModulationDepth);
  const bool standardSramReady = standardSramModulator_.begin(
      dutyConfig, kStandardCarrierBase, kStandardModulationDepth);
  const bool boostDsbReady = boostDsbAmModulator_.begin(
      dutyConfig, kBoostCarrierBase, kBoostModulationDepth);
  const bool boostSramReady = boostSramModulator_.begin(
      dutyConfig, kBoostCarrierBase, kBoostModulationDepth);
  if (!standardDsbReady || !standardSramReady ||
      !boostDsbReady || !boostSramReady) {
    return false;
  }

  for (uint16_t sample = 0; sample < 256; ++sample) {
    const float normalized =
        (static_cast<float>(sample) - 128.0f) / 128.0f;
    const float magnitude = fabsf(normalized);
    float enhanced = 0.0f;
    if (magnitude > kLoudnessNoiseGate) {
      const float gated =
          (magnitude - kLoudnessNoiseGate) /
          (1.0f - kLoudnessNoiseGate);
      enhanced =
          (kLoudnessSmallSignalGain * gated) /
          (1.0f + (kLoudnessSmallSignalGain - 1.0f) * gated);
      if (normalized < 0.0f) enhanced = -enhanced;
    }
    int32_t enhancedSample = static_cast<int32_t>(
        lroundf(128.0f + 128.0f * enhanced));
    if (enhancedSample < 0) enhancedSample = 0;
    if (enhancedSample > 255) enhancedSample = 255;
    loudnessLut_[sample] = static_cast<uint8_t>(enhancedSample);
  }

  initialized_ = true;
  stop();
  return true;
}

bool AudioModulator::start(AudioModulationMode modulationMode,
                           AudioProcessingMode processingMode,
                           AudioDriveMode driveMode, bool loop) {
  if (!initialized_ || kAudioSampleCount == 0 || kAudioSampleRate == 0) {
    return false;
  }

  sampleIndex_ = 0;
  modulationMode_ = modulationMode;
  processingMode_ = processingMode;
  driveMode_ = driveMode;
  loop_ = loop;
  running_ = true;
  return true;
}

void AudioModulator::stop() {
  sampleIndex_ = 0;
  loop_ = false;
  running_ = false;
}

ModulationFrame AudioModulator::nextFrame() {
  ModulationFrame frame = {};
  if (!running_) return frame;

  frame.status = ModulationFrameStatus::kRunning;
  const uint8_t sample = readSample(sampleIndex_);
  if (driveMode_ == AudioDriveMode::kBoost) {
    switch (modulationMode_) {
      case AudioModulationMode::kSram:
        frame.duty = boostSramModulator_.dutyForSample(sample);
        break;
      case AudioModulationMode::kDsbAm:
      default:
        frame.duty = boostDsbAmModulator_.dutyForSample(sample);
        break;
    }
  } else {
    switch (modulationMode_) {
      case AudioModulationMode::kSram:
        frame.duty = standardSramModulator_.dutyForSample(sample);
        break;
      case AudioModulationMode::kDsbAm:
      default:
        frame.duty = standardDsbAmModulator_.dutyForSample(sample);
        break;
    }
  }
  frame.sampleRateHz = kAudioSampleRate;

  ++sampleIndex_;
  if (sampleIndex_ >= kAudioSampleCount) {
    if (loop_) {
      sampleIndex_ = 0;
    } else {
      running_ = false;
      frame.status = ModulationFrameStatus::kCompleted;
    }
  }

  return frame;
}

ModulationFrameStatus AudioModulator::skipFrames(uint32_t frameCount) {
  if (!running_) return ModulationFrameStatus::kIdle;
  if (frameCount == 0) return ModulationFrameStatus::kRunning;

  if (loop_) {
    sampleIndex_ =
        (sampleIndex_ + frameCount % kAudioSampleCount) % kAudioSampleCount;
    return ModulationFrameStatus::kRunning;
  }

  const uint32_t remainingSamples = kAudioSampleCount - sampleIndex_;
  if (frameCount >= remainingSamples) {
    sampleIndex_ = kAudioSampleCount;
    running_ = false;
    return ModulationFrameStatus::kCompleted;
  }

  sampleIndex_ += frameCount;
  return ModulationFrameStatus::kRunning;
}

AudioInfo AudioModulator::info() const {
  AudioInfo result = {};
  result.sampleCount = kAudioSampleCount;
  result.sampleRate = kAudioSampleRate;
  return result;
}

uint8_t AudioModulator::readSample(uint32_t index) const {
  const uint8_t sample = pgm_read_byte(&kAudioSamples[index]);

  return processingMode_ == AudioProcessingMode::kLoudnessEnhanced
             ? loudnessLut_[sample]
             : sample;
}

}  // namespace ultrasonic
