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
  bool startEnvelopeTone(uint32_t toneHz);
  bool startAudio(bool loop);
  void setAudioModulationMode(AudioModulationMode mode);
  AudioModulationMode audioModulationMode() const;
  void setAudioProcessingMode(AudioProcessingMode mode);
  AudioProcessingMode audioProcessingMode() const;
  void setAudioDriveMode(AudioDriveMode mode);
  AudioDriveMode audioDriveMode() const;
  ModulationFrame nextFrame();
  ModulationFrameStatus skipFrames(uint32_t frameCount);
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
  AudioModulationMode audioModulationMode_ = AudioModulationMode::kDsbAm;
  AudioProcessingMode audioProcessingMode_ =
      AudioProcessingMode::kLoudnessEnhanced;
  AudioDriveMode audioDriveMode_ = AudioDriveMode::kBoost;
  bool initialized_ = false;
};

}  // namespace ultrasonic
