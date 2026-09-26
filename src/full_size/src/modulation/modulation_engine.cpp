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
  flashAudioSource_.stop();
  streamAudioSource_.stop();
}

bool ModulationEngine::startEnvelopeTone(uint32_t toneHz) {
  if (!initialized_) return false;

  flashAudioSource_.stop();
  streamAudioSource_.stop();
  if (!envelopeModulator_.reset(toneHz, audioDriveMode_)) return false;
  mode_ = Mode::kEnvelopeTone;
  return true;
}

bool ModulationEngine::startAudio(bool loop) {
  if (!initialized_ || !flashAudioSource_.start(loop)) {
    return false;
  }
  streamAudioSource_.stop();
  mode_ = Mode::kEmbeddedAudio;
  return true;
}

bool ModulationEngine::startStream(const AudioStreamParameters& parameters) {
  if (!initialized_ || parameters.sampleRate != 8000 ||
      !streamAudioSource_.start(parameters.sampleRate,
                                parameters.prebufferSamples)) {
    return false;
  }
  flashAudioSource_.stop();
  audioModulationMode_ = parameters.modulationMode;
  audioProcessingMode_ = parameters.processingMode;
  audioDriveMode_ = parameters.driveMode;
  mode_ = Mode::kStreamAudio;
  return true;
}

bool ModulationEngine::pushStreamSamples(const uint8_t* samples,
                                         uint32_t sampleCount) {
  return mode_ == Mode::kStreamAudio &&
         streamAudioSource_.writeSamples(samples, sampleCount);
}

bool ModulationEngine::streamReadyToPlay() const {
  return mode_ == Mode::kStreamAudio && streamAudioSource_.readyToPlay();
}

StreamBufferStats ModulationEngine::streamStats() const {
  return streamAudioSource_.stats();
}

bool ModulationEngine::streaming() const {
  return mode_ == Mode::kStreamAudio;
}

void ModulationEngine::setAudioModulationMode(AudioModulationMode mode) {
  audioModulationMode_ = mode;
}

AudioModulationMode ModulationEngine::audioModulationMode() const {
  return audioModulationMode_;
}

void ModulationEngine::setAudioProcessingMode(AudioProcessingMode mode) {
  audioProcessingMode_ = mode;
}

AudioProcessingMode ModulationEngine::audioProcessingMode() const {
  return audioProcessingMode_;
}

void ModulationEngine::setAudioDriveMode(AudioDriveMode mode) {
  audioDriveMode_ = mode;
}

AudioDriveMode ModulationEngine::audioDriveMode() const {
  return audioDriveMode_;
}

void ModulationEngine::setAudioVolume(uint16_t permille, bool immediate) {
  audioVolume_.setTargetPermille(permille, immediate);
}

uint16_t ModulationEngine::targetVolumePermille() const {
  return audioVolume_.targetPermille();
}

bool ModulationEngine::audioOutputMuted() const {
  return (mode_ == Mode::kEmbeddedAudio || mode_ == Mode::kStreamAudio) &&
         audioVolume_.off();
}

ModulationFrame ModulationEngine::nextFrame() {
  switch (mode_) {
    case Mode::kEnvelopeTone:
      return envelopeModulator_.nextFrame();
    case Mode::kEmbeddedAudio: {
      uint8_t sample = 128;
      const AudioReadStatus status = flashAudioSource_.readSample(&sample);
      if (status == AudioReadStatus::kIdle) return {};
      audioVolume_.advance(1);
      ModulationFrame frame = {
          status == AudioReadStatus::kCompleted
              ? ModulationFrameStatus::kCompleted
              : ModulationFrameStatus::kRunning,
          audioModulator_.dutyForSample(sample, audioModulationMode_,
                                        audioProcessingMode_, audioDriveMode_,
                                        audioVolume_.currentGainQ15()),
          flashAudioSource_.info().sampleRate,
      };
      if (status == AudioReadStatus::kCompleted) mode_ = Mode::kOff;
      return frame;
    }
    case Mode::kStreamAudio: {
      uint8_t sample = 128;
      const AudioReadStatus status = streamAudioSource_.readSample(&sample);
      if (status == AudioReadStatus::kUnderrun) {
        return {ModulationFrameStatus::kUnderrun, 0,
                streamAudioSource_.sampleRateHz()};
      }
      if (status != AudioReadStatus::kSample) return {};
      audioVolume_.advance(1);
      return {ModulationFrameStatus::kRunning,
              audioModulator_.dutyForSample(
                  sample, audioModulationMode_, audioProcessingMode_,
                  audioDriveMode_, audioVolume_.currentGainQ15()),
              streamAudioSource_.sampleRateHz()};
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
    case Mode::kEmbeddedAudio: {
      audioVolume_.advance(frameCount);
      const AudioReadStatus sourceStatus =
          flashAudioSource_.skipSamples(frameCount);
      status = sourceStatus == AudioReadStatus::kCompleted
                   ? ModulationFrameStatus::kCompleted
                   : ModulationFrameStatus::kRunning;
      break;
    }
    case Mode::kStreamAudio: {
      audioVolume_.advance(frameCount);
      const AudioReadStatus sourceStatus =
          streamAudioSource_.skipSamples(frameCount);
      status = sourceStatus == AudioReadStatus::kUnderrun
                   ? ModulationFrameStatus::kUnderrun
                   : ModulationFrameStatus::kRunning;
      break;
    }
    case Mode::kOff:
    default:
      return status;
  }

  if (status == ModulationFrameStatus::kCompleted) mode_ = Mode::kOff;
  return status;
}

AudioInfo ModulationEngine::audioInfo() const {
  return flashAudioSource_.info();
}

}  // namespace ultrasonic
