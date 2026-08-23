#pragma once

#include <Arduino.h>
#include "driver/ledc.h"
#include "esp_err.h"

namespace ultrasonic {

// 只负责 GPIO 和 LEDC，不包含播放模式、串口或任务调度逻辑。
class UltrasonicDriver final {
 public:
  static constexpr uint8_t kChannelCount = 4;
  static constexpr uint32_t kDefaultCarrierHz = 40000;
  static constexpr uint32_t kMinimumCarrierHz = 38000;
  static constexpr uint32_t kMaximumCarrierHz = 42000;
  static constexpr uint32_t kPeriodCounts = 1U << 10;
  static constexpr uint32_t kHalfDuty = kPeriodCounts / 2;

  esp_err_t begin();
  esp_err_t setChannelDuty(uint8_t channel, uint32_t duty);
  esp_err_t setAllDuty(uint32_t duty);
  esp_err_t setCarrierFrequency(uint32_t frequencyHz);
  esp_err_t stop();

  int gpioForChannel(uint8_t channel) const;
  uint32_t carrierHz() const { return carrierHz_; }

 private:
  static constexpr int kGpios[kChannelCount] = {4, 5, 6, 7};
  static constexpr ledc_mode_t kSpeedMode = LEDC_LOW_SPEED_MODE;
  static constexpr ledc_timer_t kTimer = LEDC_TIMER_0;
  static constexpr ledc_timer_bit_t kResolution = LEDC_TIMER_10_BIT;

  bool initialized_ = false;
  uint32_t carrierHz_ = kDefaultCarrierHz;
};

}  // namespace ultrasonic
