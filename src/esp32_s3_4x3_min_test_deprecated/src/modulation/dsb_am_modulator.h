#pragma once

#include <stdint.h>

#include "modulation_types.h"

namespace ultrasonic {

// Double-Sideband AM: E(t) = carrierLevel + modulationDepth * s(t)。
class DsbAmModulator final {
 public:
  bool begin(const DutyConfig& dutyConfig, float carrierLevel,
             float modulationDepth);
  uint32_t dutyForSample(uint8_t sample) const;

 private:
  uint32_t dutyLut_[256] = {};
  bool initialized_ = false;
};

}  // namespace ultrasonic
