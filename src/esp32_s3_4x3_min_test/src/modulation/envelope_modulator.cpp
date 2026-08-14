#include "envelope_modulator.h"

#include <math.h>

#include "modulation_math.h"

namespace ultrasonic {

bool EnvelopeModulator::begin(const DutyConfig& dutyConfig) {
  if (dutyConfig.periodCounts == 0 || dutyConfig.maximumDuty == 0) {
    return false;
  }

  constexpr float kPi = 3.14159265358979323846f;
  for (uint8_t sample = 0; sample < kSampleCount; ++sample) {
    const float phase = 2.0f * kPi * static_cast<float>(sample) /
                        static_cast<float>(kSampleCount);
    const float envelope = 0.55f + 0.40f * sinf(phase);
    dutyTable_[sample] =
        modulation_math::envelopeToDuty(envelope, dutyConfig);
  }

  initialized_ = true;
  reset();
  return true;
}

void EnvelopeModulator::reset() {
  sampleIndex_ = 0;
}

ModulationFrame EnvelopeModulator::nextFrame() {
  ModulationFrame frame = {};
  if (!initialized_) return frame;

  frame.status = ModulationFrameStatus::kRunning;
  frame.duty = dutyTable_[sampleIndex_];
  frame.intervalUs = 1000000UL / kSampleRate;
  sampleIndex_ = (sampleIndex_ + 1) % kSampleCount;
  return frame;
}

}  // namespace ultrasonic
