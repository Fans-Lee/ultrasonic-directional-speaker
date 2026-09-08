#include "flash_audio_source.h"

#include <Arduino.h>

#include "../data/audio_data.h"

namespace ultrasonic {

bool FlashAudioSource::start(bool loop) {
  if (kAudioSampleCount == 0 || kAudioSampleRate == 0) return false;
  sampleIndex_ = 0;
  loop_ = loop;
  running_ = true;
  return true;
}

void FlashAudioSource::stop() {
  sampleIndex_ = 0;
  loop_ = false;
  running_ = false;
}

AudioReadStatus FlashAudioSource::readSample(uint8_t* sample) {
  if (!running_ || sample == nullptr) return AudioReadStatus::kIdle;
  *sample = pgm_read_byte(&kAudioSamples[sampleIndex_]);
  ++sampleIndex_;
  if (sampleIndex_ < kAudioSampleCount) return AudioReadStatus::kSample;
  if (loop_) {
    sampleIndex_ = 0;
    return AudioReadStatus::kSample;
  }
  running_ = false;
  return AudioReadStatus::kCompleted;
}

AudioReadStatus FlashAudioSource::skipSamples(uint32_t sampleCount) {
  if (!running_) return AudioReadStatus::kIdle;
  if (sampleCount == 0) return AudioReadStatus::kSample;
  if (loop_) {
    sampleIndex_ =
        (sampleIndex_ + sampleCount % kAudioSampleCount) % kAudioSampleCount;
    return AudioReadStatus::kSample;
  }
  const uint32_t remaining = kAudioSampleCount - sampleIndex_;
  if (sampleCount >= remaining) {
    sampleIndex_ = kAudioSampleCount;
    running_ = false;
    return AudioReadStatus::kCompleted;
  }
  sampleIndex_ += sampleCount;
  return AudioReadStatus::kSample;
}

AudioInfo FlashAudioSource::info() const {
  return {kAudioSampleCount, kAudioSampleRate};
}

}  // namespace ultrasonic
