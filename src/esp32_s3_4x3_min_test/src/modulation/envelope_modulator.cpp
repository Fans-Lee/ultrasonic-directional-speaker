#include "envelope_modulator.h"

#include <math.h>

#include "modulation_math.h"

namespace ultrasonic {
namespace {

constexpr float kPi = 3.14159265358979323846f;
constexpr float kStandardBias = 0.55f;
constexpr float kStandardDepth = 0.40f;
constexpr float kBoostBias = 0.50f;
constexpr float kBoostDepth = 0.48f;

}  // namespace

bool EnvelopeModulator::begin(const DutyConfig& dutyConfig) {
  if (dutyConfig.periodCounts == 0 || dutyConfig.maximumDuty == 0) {
    return false;
  }

  for (uint16_t sample = 0; sample < kSineTableSize; ++sample) {
    const float phase = 2.0f * kPi * static_cast<float>(sample) /
                        static_cast<float>(kSineTableSize);
    const float sine = sinf(phase);
    standardDutyTable_[sample] = modulation_math::envelopeToDuty(
        kStandardBias + kStandardDepth * sine, dutyConfig);
    boostDutyTable_[sample] = modulation_math::envelopeToDuty(
        kBoostBias + kBoostDepth * sine, dutyConfig);
  }

  initialized_ = true;
  return reset(1000, AudioDriveMode::kBoost);
}

bool EnvelopeModulator::reset(uint32_t toneHz, AudioDriveMode driveMode) {
  if (!initialized_ || toneHz < kMinimumToneHz ||
      toneHz > kMaximumToneHz) {
    return false;
  }

  activeDutyTable_ = driveMode == AudioDriveMode::kStandard
                         ? standardDutyTable_
                         : boostDutyTable_;
  phaseAccumulator_ = 0;
  phaseIncrement_ = static_cast<uint32_t>(
      (static_cast<uint64_t>(toneHz) * (1ULL << 32) + kSampleRate / 2) /
      kSampleRate);
  return true;
}

ModulationFrame EnvelopeModulator::nextFrame() {
  ModulationFrame frame = {};
  if (!initialized_ || activeDutyTable_ == nullptr) return frame;

  frame.status = ModulationFrameStatus::kRunning;
  const uint8_t tableIndex = static_cast<uint8_t>(phaseAccumulator_ >> 24);
  frame.duty = activeDutyTable_[tableIndex];
  frame.sampleRateHz = kSampleRate;
  phaseAccumulator_ += phaseIncrement_;
  return frame;
}

ModulationFrameStatus EnvelopeModulator::skipFrames(uint32_t frameCount) {
  if (!initialized_) return ModulationFrameStatus::kIdle;

  phaseAccumulator_ += static_cast<uint32_t>(
      static_cast<uint64_t>(phaseIncrement_) * frameCount);
  return ModulationFrameStatus::kRunning;
}

}  // namespace ultrasonic
