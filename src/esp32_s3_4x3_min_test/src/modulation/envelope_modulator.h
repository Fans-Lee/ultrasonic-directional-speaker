#pragma once

#include <stdint.h>

#include "modulation_types.h"

namespace ultrasonic {

// 产生用于链路测试的可调频正弦包络。
class EnvelopeModulator final {
 public:
  static constexpr uint32_t kMinimumToneHz = 20;
  static constexpr uint32_t kMaximumToneHz = 3000;

  bool begin(const DutyConfig& dutyConfig);
  bool reset(uint32_t toneHz, AudioDriveMode driveMode);
  ModulationFrame nextFrame();
  ModulationFrameStatus skipFrames(uint32_t frameCount);

 private:
  static constexpr uint32_t kSampleRate = 8000;
  static constexpr uint16_t kSineTableSize = 256;

  uint32_t standardDutyTable_[kSineTableSize] = {};
  uint32_t boostDutyTable_[kSineTableSize] = {};
  const uint32_t* activeDutyTable_ = nullptr;
  uint32_t phaseAccumulator_ = 0;
  uint32_t phaseIncrement_ = 0;
  bool initialized_ = false;
};

}  // namespace ultrasonic
