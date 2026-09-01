#include "sram_modulator.h"

#include <math.h>

#include "modulation_math.h"

namespace ultrasonic {

bool SramModulator::begin(const DutyConfig& dutyConfig, float carrierLevel,
                          float modulationDepth) {
  if (dutyConfig.periodCounts == 0 || dutyConfig.maximumDuty == 0 ||
      carrierLevel <= 0.0f || modulationDepth < 0.0f ||
      carrierLevel < modulationDepth ||
      carrierLevel + modulationDepth > 1.0f) {
    return false;
  }

  const float peakEnvelope = carrierLevel + modulationDepth;
  for (uint16_t sample = 0; sample < 256; ++sample) {
    const float normalized =
        (static_cast<float>(sample) - 128.0f) / 128.0f;
    const float dsbEnvelope = carrierLevel + modulationDepth * normalized;

    // 等价于 peak * sqrt((1 + m*s) / (1 + m))，其中
    // m = modulationDepth / carrierLevel；因此与 DSB-AM 具有相同峰值包络。
    const float envelope = sqrtf(peakEnvelope * dsbEnvelope);
    dutyLut_[sample] =
        modulation_math::envelopeToDuty(envelope, dutyConfig);
  }

  initialized_ = true;
  return true;
}

uint32_t SramModulator::dutyForSample(uint8_t sample) const {
  return initialized_ ? dutyLut_[sample] : 0;
}

}  // namespace ultrasonic
