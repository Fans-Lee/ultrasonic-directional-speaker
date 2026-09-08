#pragma once

#include <stdint.h>

namespace ultrasonic {

// 调制计算只关心 PWM 计数范围，不依赖具体的 LEDC driver。
struct DutyConfig {
  uint32_t periodCounts;
  uint32_t maximumDuty;
};

enum class AudioModulationMode : uint8_t {
  kDsbAm,
  kSram,
};

inline const char* audioModulationModeName(AudioModulationMode mode) {
  switch (mode) {
    case AudioModulationMode::kSram:
      return "SRAM";
    case AudioModulationMode::kDsbAm:
    default:
      return "DSB-AM";
  }
}

enum class AudioProcessingMode : uint8_t {
  kRaw,
  kLoudnessEnhanced,
};

inline const char* audioProcessingModeName(AudioProcessingMode mode) {
  switch (mode) {
    case AudioProcessingMode::kRaw:
      return "RAW";
    case AudioProcessingMode::kLoudnessEnhanced:
    default:
      return "LOUD";
  }
}

enum class AudioDriveMode : uint8_t {
  kStandard,
  kBoost,
};

inline const char* audioDriveModeName(AudioDriveMode mode) {
  switch (mode) {
    case AudioDriveMode::kStandard:
      return "STANDARD";
    case AudioDriveMode::kBoost:
    default:
      return "BOOST";
  }
}

enum class ModulationFrameStatus : uint8_t {
  kIdle,
  kRunning,
  kCompleted,
  kUnderrun,
};

struct ModulationFrame {
  ModulationFrameStatus status = ModulationFrameStatus::kIdle;
  uint32_t duty = 0;
  uint32_t sampleRateHz = 0;
};

struct AudioInfo {
  uint32_t sampleCount = 0;
  uint32_t sampleRate = 0;
};

struct AudioStreamParameters {
  uint32_t sampleRate = 8000;
  uint32_t prebufferSamples = 480;
  uint32_t dataTimeoutMs = 100;
  AudioModulationMode modulationMode = AudioModulationMode::kDsbAm;
  AudioProcessingMode processingMode = AudioProcessingMode::kRaw;
  AudioDriveMode driveMode = AudioDriveMode::kStandard;
};

}  // namespace ultrasonic
