#pragma once

#include <stdint.h>

namespace ultrasonic {

enum class AudioReadStatus : uint8_t {
  kIdle,
  kSample,
  kCompleted,
  kUnderrun,
};

struct StreamBufferStats {
  uint32_t bufferedSamples = 0;
  uint32_t capacitySamples = 0;
  uint32_t underrunCount = 0;
  uint32_t overrunCount = 0;
};

}  // namespace ultrasonic
