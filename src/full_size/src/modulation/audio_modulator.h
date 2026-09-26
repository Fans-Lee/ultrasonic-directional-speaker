#pragma once

#include <stdint.h>

#include "dsb_am_modulator.h"
#include "modulation_types.h"
#include "sram_modulator.h"

namespace ultrasonic {

// 将一个 8-bit PCM 样本转换成超声载波占空比，不负责音源读取。
class AudioModulator final {
 public:
  bool begin(const DutyConfig& dutyConfig);
  uint32_t dutyForSample(uint8_t sample, AudioModulationMode modulationMode,
                         AudioProcessingMode processingMode,
                         AudioDriveMode driveMode, uint32_t gainQ15) const;

 private:
  DsbAmModulator standardDsbAmModulator_;
  SramModulator standardSramModulator_;
  DsbAmModulator boostDsbAmModulator_;
  SramModulator boostSramModulator_;
  uint8_t loudnessLut_[256] = {};
  bool initialized_ = false;
};

}  // namespace ultrasonic
