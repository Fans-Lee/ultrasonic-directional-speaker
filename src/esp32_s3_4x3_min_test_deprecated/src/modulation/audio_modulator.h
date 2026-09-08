#pragma once

#include <stdint.h>

#include "dsb_am_modulator.h"
#include "modulation_types.h"
#include "sram_modulator.h"

namespace ultrasonic {

// 将固件内的 8-bit PCM 音频转换成超声载波占空比序列。
class AudioModulator final {
 public:
  bool begin(const DutyConfig& dutyConfig);
  bool start(AudioModulationMode modulationMode,
             AudioProcessingMode processingMode, AudioDriveMode driveMode,
             bool loop);
  void stop();
  ModulationFrame nextFrame();
  ModulationFrameStatus skipFrames(uint32_t frameCount);
  AudioInfo info() const;

 private:
  uint8_t readSample(uint32_t index) const;

  DsbAmModulator standardDsbAmModulator_;
  SramModulator standardSramModulator_;
  DsbAmModulator boostDsbAmModulator_;
  SramModulator boostSramModulator_;
  uint8_t demoSineLut_[256] = {};
  uint8_t loudnessLut_[256] = {};
  uint32_t sampleIndex_ = 0;
  AudioModulationMode modulationMode_ = AudioModulationMode::kDsbAm;
  AudioProcessingMode processingMode_ =
      AudioProcessingMode::kLoudnessEnhanced;
  AudioDriveMode driveMode_ = AudioDriveMode::kBoost;
  bool loop_ = false;
  bool initialized_ = false;
  bool running_ = false;
};

}  // namespace ultrasonic
