#pragma once

#include "audio_modulator.h"
#include "audio_volume.h"
#include "envelope_modulator.h"
#include "modulation_types.h"
#include "../audio/flash_audio_source.h"
#include "../audio/stream_audio_source.h"

namespace ultrasonic {

// 向调度层提供统一接口，隐藏具体调制算法和播放索引。
class ModulationEngine final {
 public:
  bool begin(const DutyConfig& dutyConfig);
  void stop();
  bool startEnvelopeTone(uint32_t toneHz);
  bool startAudio(bool loop);
  bool startStream(const AudioStreamParameters& parameters);
  bool pushStreamSamples(const uint8_t* samples, uint32_t sampleCount);
  bool streamReadyToPlay() const;
  StreamBufferStats streamStats() const;
  bool streaming() const;
  void setAudioModulationMode(AudioModulationMode mode);
  AudioModulationMode audioModulationMode() const;
  void setAudioProcessingMode(AudioProcessingMode mode);
  AudioProcessingMode audioProcessingMode() const;
  void setAudioDriveMode(AudioDriveMode mode);
  AudioDriveMode audioDriveMode() const;
  void setAudioVolume(uint16_t permille, bool immediate);
  uint16_t targetVolumePermille() const;
  bool audioOutputMuted() const;
  ModulationFrame nextFrame();
  ModulationFrameStatus skipFrames(uint32_t frameCount);
  AudioInfo audioInfo() const;

 private:
  enum class Mode : uint8_t {
    kOff,
    kEnvelopeTone,
    kEmbeddedAudio,
    kStreamAudio,
  };

  EnvelopeModulator envelopeModulator_;
  AudioModulator audioModulator_;
  AudioVolume audioVolume_;
  FlashAudioSource flashAudioSource_;
  StreamAudioSource streamAudioSource_;
  Mode mode_ = Mode::kOff;
  AudioModulationMode audioModulationMode_ = AudioModulationMode::kDsbAm;
  AudioProcessingMode audioProcessingMode_ =
      AudioProcessingMode::kLoudnessEnhanced;
  AudioDriveMode audioDriveMode_ = AudioDriveMode::kBoost;
  bool initialized_ = false;
};

}  // namespace ultrasonic
