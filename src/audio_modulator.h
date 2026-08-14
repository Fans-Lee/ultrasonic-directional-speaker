#pragma once

#include <stdint.h>

#include "modulation_types.h"

namespace ultrasonic {

// 将固件内的 8-bit PCM 音频转换成超声载波占空比序列。
class AudioModulator final {
 public:
  bool begin(const DutyConfig& dutyConfig);
  bool start(bool loop);
  void stop();
  ModulationFrame nextFrame();
  AudioInfo info() const;

 private:
  uint8_t readSample(uint32_t index) const;

  uint32_t dutyLut_[256] = {};
  uint8_t demoSineLut_[256] = {};
  uint32_t sampleIndex_ = 0;
  bool loop_ = false;
  bool initialized_ = false;
  bool running_ = false;
};

}  // namespace ultrasonic
