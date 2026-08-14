#include "modulation_engine.h"

namespace ultrasonic {

bool ModulationEngine::begin(const DutyConfig& dutyConfig) {
  const bool envelopeReady = envelopeModulator_.begin(dutyConfig);
  const bool audioReady = audioModulator_.begin(dutyConfig);
  initialized_ = envelopeReady && audioReady;
  stop();
  return initialized_;
}

void ModulationEngine::stop() {
  mode_ = Mode::kOff;
  audioModulator_.stop();
}

bool ModulationEngine::startEnvelopeTone() {
  if (!initialized_) return false;

  audioModulator_.stop();
  envelopeModulator_.reset();
  mode_ = Mode::kEnvelopeTone;
  return true;
}

bool ModulationEngine::startAudio(bool loop) {
  if (!initialized_ ||
      !audioModulator_.start(audioModulationMode_, loop)) {
    return false;
  }

  mode_ = Mode::kAudio;
  return true;
}

void ModulationEngine::setAudioModulationMode(AudioModulationMode mode) {
  audioModulationMode_ = mode;
}

AudioModulationMode ModulationEngine::audioModulationMode() const {
  return audioModulationMode_;
}

ModulationFrame ModulationEngine::nextFrame() {
  switch (mode_) {
    case Mode::kEnvelopeTone:
      return envelopeModulator_.nextFrame();
    case Mode::kAudio: {
      ModulationFrame frame = audioModulator_.nextFrame();
      if (frame.status == ModulationFrameStatus::kCompleted) {
        mode_ = Mode::kOff;
      }
      return frame;
    }
    case Mode::kOff:
    default:
      return {};
  }
}

ModulationFrameStatus ModulationEngine::skipFrames(uint32_t frameCount) {
  ModulationFrameStatus status = ModulationFrameStatus::kIdle;
  switch (mode_) {
    case Mode::kEnvelopeTone:
      status = envelopeModulator_.skipFrames(frameCount);
      break;
    case Mode::kAudio:
      status = audioModulator_.skipFrames(frameCount);
      break;
    case Mode::kOff:
    default:
      return status;
  }

  if (status == ModulationFrameStatus::kCompleted) mode_ = Mode::kOff;
  return status;
}

AudioInfo ModulationEngine::audioInfo() const {
  return audioModulator_.info();
}

}  // namespace ultrasonic
