#pragma once

#include <Arduino.h>
#include <stdint.h>

#include "audio_source.h"

namespace ultrasonic {

class StreamAudioSource final {
 public:
  static constexpr uint32_t kCapacitySamples = 2048;

  bool start(uint32_t sampleRateHz, uint32_t prebufferSamples);
  void stop();
  bool writeSamples(const uint8_t* samples, uint32_t sampleCount);
  AudioReadStatus readSample(uint8_t* sample);
  AudioReadStatus skipSamples(uint32_t sampleCount);
  bool readyToPlay() const;
  uint32_t sampleRateHz() const { return sampleRateHz_; }
  StreamBufferStats stats() const;

 private:
  mutable portMUX_TYPE mux_ = portMUX_INITIALIZER_UNLOCKED;
  uint8_t samples_[kCapacitySamples] = {};
  uint32_t readIndex_ = 0;
  uint32_t writeIndex_ = 0;
  uint32_t bufferedSamples_ = 0;
  uint32_t sampleRateHz_ = 0;
  uint32_t prebufferSamples_ = 0;
  uint32_t underrunCount_ = 0;
  uint32_t overrunCount_ = 0;
  bool running_ = false;
};

}  // namespace ultrasonic
