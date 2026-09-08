#include "audio_modulator.h"

#include <math.h>

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
  return true;
}

uint32_t AudioModulator::dutyForSample(
    uint8_t sample, AudioModulationMode modulationMode,
    AudioProcessingMode processingMode, AudioDriveMode driveMode) const {
  if (!initialized_) return 0;
  const uint8_t processedSample =
      processingMode == AudioProcessingMode::kLoudnessEnhanced
          ? loudnessLut_[sample]
          : sample;
  if (driveMode == AudioDriveMode::kBoost) {
    switch (modulationMode) {
      case AudioModulationMode::kSram:
        return boostSramModulator_.dutyForSample(processedSample);
      case AudioModulationMode::kDsbAm:
      default:
        return boostDsbAmModulator_.dutyForSample(processedSample);
    }
  }
  switch (modulationMode) {
    case AudioModulationMode::kSram:
      return standardSramModulator_.dutyForSample(processedSample);
    case AudioModulationMode::kDsbAm:
    default:
      return standardDsbAmModulator_.dutyForSample(processedSample);
  }
}

}  // namespace ultrasonic
