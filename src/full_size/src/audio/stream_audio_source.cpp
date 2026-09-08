#include "stream_audio_source.h"

namespace ultrasonic {

bool StreamAudioSource::start(uint32_t sampleRateHz,
                              uint32_t prebufferSamples) {
  if (sampleRateHz == 0 || prebufferSamples == 0 ||
      prebufferSamples > kCapacitySamples) {
    return false;
  }
  portENTER_CRITICAL(&mux_);
  readIndex_ = 0;
  writeIndex_ = 0;
  bufferedSamples_ = 0;
  sampleRateHz_ = sampleRateHz;
  prebufferSamples_ = prebufferSamples;
  underrunCount_ = 0;
  overrunCount_ = 0;
  running_ = true;
  portEXIT_CRITICAL(&mux_);
  return true;
}

void StreamAudioSource::stop() {
  portENTER_CRITICAL(&mux_);
  readIndex_ = 0;
  writeIndex_ = 0;
  bufferedSamples_ = 0;
  running_ = false;
  portEXIT_CRITICAL(&mux_);
}

bool StreamAudioSource::writeSamples(const uint8_t* samples,
                                     uint32_t sampleCount) {
  if (samples == nullptr || sampleCount == 0 ||
      sampleCount > kCapacitySamples) {
    return false;
  }
  portENTER_CRITICAL(&mux_);
  if (!running_ || sampleCount > kCapacitySamples - bufferedSamples_) {
    if (running_) ++overrunCount_;
    portEXIT_CRITICAL(&mux_);
    return false;
  }
  for (uint32_t index = 0; index < sampleCount; ++index) {
    samples_[writeIndex_] = samples[index];
    writeIndex_ = (writeIndex_ + 1) % kCapacitySamples;
  }
  bufferedSamples_ += sampleCount;
  portEXIT_CRITICAL(&mux_);
  return true;
}

AudioReadStatus StreamAudioSource::readSample(uint8_t* sample) {
  if (sample == nullptr) return AudioReadStatus::kIdle;
  portENTER_CRITICAL(&mux_);
  if (!running_) {
    portEXIT_CRITICAL(&mux_);
    return AudioReadStatus::kIdle;
  }
  if (bufferedSamples_ == 0) {
    ++underrunCount_;
    portEXIT_CRITICAL(&mux_);
    return AudioReadStatus::kUnderrun;
  }
  *sample = samples_[readIndex_];
  readIndex_ = (readIndex_ + 1) % kCapacitySamples;
  --bufferedSamples_;
  portEXIT_CRITICAL(&mux_);
  return AudioReadStatus::kSample;
}

AudioReadStatus StreamAudioSource::skipSamples(uint32_t sampleCount) {
  if (sampleCount == 0) return AudioReadStatus::kSample;
  portENTER_CRITICAL(&mux_);
  if (!running_) {
    portEXIT_CRITICAL(&mux_);
    return AudioReadStatus::kIdle;
  }
  if (sampleCount > bufferedSamples_) {
    readIndex_ = writeIndex_;
    bufferedSamples_ = 0;
    ++underrunCount_;
    portEXIT_CRITICAL(&mux_);
    return AudioReadStatus::kUnderrun;
  }
  readIndex_ = (readIndex_ + sampleCount) % kCapacitySamples;
  bufferedSamples_ -= sampleCount;
  portEXIT_CRITICAL(&mux_);
  return AudioReadStatus::kSample;
}

bool StreamAudioSource::readyToPlay() const {
  portENTER_CRITICAL(&mux_);
  const bool ready = running_ && bufferedSamples_ >= prebufferSamples_;
  portEXIT_CRITICAL(&mux_);
  return ready;
}

StreamBufferStats StreamAudioSource::stats() const {
  portENTER_CRITICAL(&mux_);
  const StreamBufferStats result = {
      bufferedSamples_, kCapacitySamples, underrunCount_, overrunCount_};
  portEXIT_CRITICAL(&mux_);
  return result;
}

}  // namespace ultrasonic
