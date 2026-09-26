#pragma once

#include <math.h>
#include <stdint.h>

namespace ultrasonic {

// Shared master gain for embedded and streamed PCM. No floating point work is
// performed on the 8 kHz playback path.
class AudioVolume final {
 public:
  static constexpr uint32_t kUnityGainQ15 = 32768;
  static constexpr uint32_t kRampSamples = 320;  // 40 ms at 8 kHz

  void setTargetPermille(uint16_t permille, bool immediate) {
    if (permille > 1000) permille = 1000;
    targetPermille_ = permille;
    targetGainQ15_ = gainForPermille(permille);
    startGainQ15_ = currentGainQ15_;
    elapsedSamples_ = 0;
    if (immediate) {
      currentGainQ15_ = targetGainQ15_;
      startGainQ15_ = targetGainQ15_;
      elapsedSamples_ = kRampSamples;
    }
  }

  void advance(uint32_t samples) {
    if (elapsedSamples_ >= kRampSamples || samples == 0) return;
    const uint32_t remaining = kRampSamples - elapsedSamples_;
    elapsedSamples_ += samples < remaining ? samples : remaining;
    if (elapsedSamples_ == kRampSamples) {
      currentGainQ15_ = targetGainQ15_;
      return;
    }
    const int32_t delta = static_cast<int32_t>(targetGainQ15_) -
                          static_cast<int32_t>(startGainQ15_);
    const int32_t change = static_cast<int32_t>(
        (static_cast<int64_t>(delta) * elapsedSamples_) / kRampSamples);
    currentGainQ15_ = static_cast<uint32_t>(
        static_cast<int32_t>(startGainQ15_) + change);
  }

  uint16_t targetPermille() const { return targetPermille_; }
  uint32_t currentGainQ15() const { return currentGainQ15_; }
  bool off() const { return currentGainQ15_ == 0; }

 private:
  static uint32_t gainForPermille(uint16_t permille) {
    if (permille == 0) return 0;
    if (permille >= 1000) return kUnityGainQ15;
    const float attenuationDb =
        -30.0f * static_cast<float>(1000 - permille) / 999.0f;
    return static_cast<uint32_t>(
        lroundf(powf(10.0f, attenuationDb / 20.0f) * kUnityGainQ15));
  }

  uint16_t targetPermille_ = 1000;
  uint32_t currentGainQ15_ = kUnityGainQ15;
  uint32_t startGainQ15_ = kUnityGainQ15;
  uint32_t targetGainQ15_ = kUnityGainQ15;
  uint32_t elapsedSamples_ = kRampSamples;
};

}  // namespace ultrasonic
