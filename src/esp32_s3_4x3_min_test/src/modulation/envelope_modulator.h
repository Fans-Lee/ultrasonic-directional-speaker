#pragma once

#include <stdint.h>

#include "modulation_types.h"

namespace ultrasonic {

// 产生用于链路测试的 1 kHz 正弦包络。
class EnvelopeModulator final {
 public:
  bool begin(const DutyConfig& dutyConfig);
  void reset();
  ModulationFrame nextFrame();
  ModulationFrameStatus skipFrames(uint32_t frameCount);

 private:
  static constexpr uint32_t kSampleRate = 8000;
  static constexpr uint32_t kToneHz = 1000;
  static constexpr uint8_t kSampleCount = kSampleRate / kToneHz;

  uint32_t dutyTable_[kSampleCount] = {};
  uint8_t sampleIndex_ = 0;
  bool initialized_ = false;
};

}  // namespace ultrasonic
