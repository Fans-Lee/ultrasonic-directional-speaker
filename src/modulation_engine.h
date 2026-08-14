#pragma once

#include "audio_modulator.h"
#include "envelope_modulator.h"
#include "modulation_types.h"

namespace ultrasonic {

// 向调度层提供统一接口，隐藏具体调制算法和播放索引。
class ModulationEngine final {
 public:
  bool begin(const DutyConfig& dutyConfig);
  void stop();
  bool startEnvelopeTone();
  bool startAudio(bool loop);
  ModulationFrame nextFrame();
  AudioInfo audioInfo() const;

 private:
  enum class Mode : uint8_t {
    kOff,
    kEnvelopeTone,
    kAudio,
  };

  EnvelopeModulator envelopeModulator_;
  AudioModulator audioModulator_;
  Mode mode_ = Mode::kOff;
  bool initialized_ = false;
};

}  // namespace ultrasonic
