#include "dsb_am_modulator.h"

#include "modulation_math.h"

namespace ultrasonic {

bool DsbAmModulator::begin(const DutyConfig& dutyConfig, float carrierLevel,
                           float modulationDepth) {
  if (dutyConfig.periodCounts == 0 || dutyConfig.maximumDuty == 0 ||
      carrierLevel <= 0.0f || modulationDepth < 0.0f ||
      carrierLevel < modulationDepth ||
      carrierLevel + modulationDepth > 1.0f) {
    return false;
  }

  for (uint16_t sample = 0; sample < 256; ++sample) {
    const float normalized =
        (static_cast<float>(sample) - 128.0f) / 128.0f;
    const float envelope = carrierLevel + modulationDepth * normalized;
    dutyLut_[sample] =
        modulation_math::envelopeToDuty(envelope, dutyConfig);
  }

  initialized_ = true;
  return true;
}

uint32_t DsbAmModulator::dutyForSample(uint8_t sample) const {
  return initialized_ ? dutyLut_[sample] : 0;
}

}  // namespace ultrasonic
