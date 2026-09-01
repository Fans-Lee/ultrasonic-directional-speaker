#pragma once

#include <stdint.h>

#include "modulation_types.h"

namespace ultrasonic {

// Square-Root Amplitude Modulation，用于补偿空气自解调模型中的平方项。
// 这里的 SRAM 是调制算法名称，与 ESP32 的片上 SRAM 存储器无关。
class SramModulator final {
 public:
  bool begin(const DutyConfig& dutyConfig, float carrierLevel,
             float modulationDepth);
  uint32_t dutyForSample(uint8_t sample) const;

 private:
  uint32_t dutyLut_[256] = {};
  bool initialized_ = false;
};

}  // namespace ultrasonic
