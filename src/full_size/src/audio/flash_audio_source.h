#pragma once

#include <stdint.h>

#include "audio_source.h"
#include "../modulation/modulation_types.h"

namespace ultrasonic {

class FlashAudioSource final {
 public:
  bool start(bool loop);
  void stop();
  AudioReadStatus readSample(uint8_t* sample);
  AudioReadStatus skipSamples(uint32_t sampleCount);
  AudioInfo info() const;

 private:
  uint32_t sampleIndex_ = 0;
  bool loop_ = false;
  bool running_ = false;
};

}  // namespace ultrasonic
