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

enum class ModulationFrameStatus : uint8_t {
  kIdle,
  kRunning,
  kCompleted,
};

struct ModulationFrame {
  ModulationFrameStatus status = ModulationFrameStatus::kIdle;
  uint32_t duty = 0;
  uint32_t intervalUs = 0;
};

struct AudioInfo {
  uint32_t sampleCount = 0;
  uint32_t sampleRate = 0;
  bool isDemo = false;
};

}  // namespace ultrasonic
