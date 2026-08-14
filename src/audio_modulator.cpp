#include "audio_modulator.h"

#include <Arduino.h>
#include <math.h>

#include "audio_data.h"
#include "modulation_math.h"

namespace ultrasonic {
namespace {

constexpr float kCarrierBase = 0.45f;
constexpr float kModulationDepth = 0.40f;

}  // namespace

bool AudioModulator::begin(const DutyConfig& dutyConfig) {
  if (dutyConfig.periodCounts == 0 || dutyConfig.maximumDuty == 0) {
    return false;
  }

  constexpr float kPi = 3.14159265358979323846f;
  for (uint16_t sample = 0; sample < 256; ++sample) {
    const float normalized =
        (static_cast<float>(sample) - 128.0f) / 128.0f;
    float envelope = kCarrierBase + kModulationDepth * normalized;
    if (envelope < 0.05f) envelope = 0.05f;
    if (envelope > 0.90f) envelope = 0.90f;
    dutyLut_[sample] =
        modulation_math::envelopeToDuty(envelope, dutyConfig);

    const float phase = 2.0f * kPi * static_cast<float>(sample) / 256.0f;
    demoSineLut_[sample] = static_cast<uint8_t>(
        lroundf(128.0f + 90.0f * sinf(phase)));
  }

  initialized_ = true;
  stop();
  return true;
}

bool AudioModulator::start(bool loop) {
  if (!initialized_ || kAudioSampleCount == 0 || kAudioSampleRate == 0) {
    return false;
  }

  sampleIndex_ = 0;
  loop_ = loop;
  running_ = true;
  return true;
}

void AudioModulator::stop() {
  sampleIndex_ = 0;
  loop_ = false;
  running_ = false;
}

ModulationFrame AudioModulator::nextFrame() {
  ModulationFrame frame = {};
  if (!running_) return frame;

  frame.status = ModulationFrameStatus::kRunning;
  frame.duty = dutyLut_[readSample(sampleIndex_)];
  frame.intervalUs = 1000000UL / kAudioSampleRate;

  ++sampleIndex_;
  if (sampleIndex_ >= kAudioSampleCount) {
    if (loop_) {
      sampleIndex_ = 0;
    } else {
      running_ = false;
      frame.status = ModulationFrameStatus::kCompleted;
    }
  }

  return frame;
}

AudioInfo AudioModulator::info() const {
  AudioInfo result = {};
  result.sampleCount = kAudioSampleCount;
  result.sampleRate = kAudioSampleRate;
  result.isDemo = kAudioIsDemo;
  return result;
}

uint8_t AudioModulator::readSample(uint32_t index) const {
  if (!kAudioIsDemo) return pgm_read_byte(&kAudioSamples[index]);

  // audio_data.h 尚未由真实 WAV 覆盖时，生成 2 秒八音测试旋律。
  static constexpr uint16_t kDemoNotesHz[] = {
      500, 600, 700, 800, 700, 600, 500, 0,
  };
  static constexpr uint32_t kSamplesPerNote = kAudioSampleRate / 4;
  static_assert(kSamplesPerNote > 0, "demo sample rate is too low");

  const uint32_t noteIndex =
      (index / kSamplesPerNote) %
      (sizeof(kDemoNotesHz) / sizeof(kDemoNotesHz[0]));
  const uint16_t frequency = kDemoNotesHz[noteIndex];
  if (frequency == 0) return 128;

  const uint32_t sampleInNote = index % kSamplesPerNote;
  const uint8_t phase = static_cast<uint8_t>(
      (sampleInNote * static_cast<uint32_t>(frequency) * 256UL) /
      kAudioSampleRate);
  return demoSineLut_[phase];
}

}  // namespace ultrasonic
