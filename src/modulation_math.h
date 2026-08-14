#pragma once

#include <math.h>

#include "modulation_types.h"

namespace ultrasonic {
namespace modulation_math {

// 方波基波幅度约与 sin(pi * duty_ratio) 成正比，因此使用反正弦映射。
inline uint32_t envelopeToDuty(float envelope, const DutyConfig& config) {
  if (config.periodCounts == 0 || config.maximumDuty == 0) return 0;

  if (envelope < 0.0f) envelope = 0.0f;
  if (envelope > 1.0f) envelope = 1.0f;

  constexpr float kPi = 3.14159265358979323846f;
  const float dutyRatio = asinf(envelope) / kPi;
  uint32_t duty = static_cast<uint32_t>(
      lroundf(dutyRatio * static_cast<float>(config.periodCounts)));
  if (duty < 1) duty = 1;
  if (duty > config.maximumDuty) duty = config.maximumDuty;
  return duty;
}

}  // namespace modulation_math
}  // namespace ultrasonic
