#include "ultrasonic_driver.h"

namespace ultrasonic {

constexpr int UltrasonicDriver::kGpios[UltrasonicDriver::kChannelCount];

esp_err_t UltrasonicDriver::begin() {
  if (initialized_) return ESP_OK;

  // 在 LEDC 接管引脚前先保持低电平，避免启动过程产生意外脉冲。
  for (uint8_t channel = 0; channel < kChannelCount; ++channel) {
    pinMode(kGpios[channel], OUTPUT);
    digitalWrite(kGpios[channel], LOW);
  }

  ledc_timer_config_t timerConfig = {};
  timerConfig.speed_mode = kSpeedMode;
  timerConfig.duty_resolution = kResolution;
  timerConfig.timer_num = kTimer;
  timerConfig.freq_hz = kCarrierHz;
  // 80 MHz APB / (40 kHz * 1024) = 500/256，可由 LEDC 精确分频。
  timerConfig.clk_cfg = LEDC_USE_APB_CLK;

  esp_err_t error = ledc_timer_config(&timerConfig);
  if (error != ESP_OK) return error;

  for (uint8_t channel = 0; channel < kChannelCount; ++channel) {
    ledc_channel_config_t channelConfig = {};
    channelConfig.gpio_num = kGpios[channel];
    channelConfig.speed_mode = kSpeedMode;
    channelConfig.channel = static_cast<ledc_channel_t>(channel);
    channelConfig.intr_type = LEDC_INTR_DISABLE;
    channelConfig.timer_sel = kTimer;
    channelConfig.duty = 0;
    channelConfig.hpoint = 0;
    channelConfig.flags.output_invert = 0;

    error = ledc_channel_config(&channelConfig);
    if (error != ESP_OK) return error;
  }

  initialized_ = true;
  return stop();
}

// 设置指定通道的占空比并保持载波居中；包络到占空比的转换由调制层负责。
esp_err_t UltrasonicDriver::setChannelDuty(uint8_t channel, uint32_t duty) {
  if (!initialized_) return ESP_ERR_INVALID_STATE;
  if (channel >= kChannelCount) return ESP_ERR_INVALID_ARG;
  if (duty > kHalfDuty) duty = kHalfDuty;

  // 让脉冲以计数周期中点为中心，改变占空比时尽量保持载波相位不动。
  const uint32_t hpoint = duty == 0 ? 0 : (kPeriodCounts - duty) / 2;
  esp_err_t error = ledc_set_duty_with_hpoint(
      kSpeedMode, static_cast<ledc_channel_t>(channel), duty, hpoint);
  if (error != ESP_OK) return error;

  return ledc_update_duty(
      kSpeedMode, static_cast<ledc_channel_t>(channel));
}

esp_err_t UltrasonicDriver::setAllDuty(uint32_t duty) {
  if (!initialized_) return ESP_ERR_INVALID_STATE;
  if (duty > kHalfDuty) duty = kHalfDuty;

  const uint32_t hpoint = duty == 0 ? 0 : (kPeriodCounts - duty) / 2;
  esp_err_t firstError = ESP_OK;

  // 先写入四路 shadow 参数，再集中触发更新，缩短通道之间的更新时间差。
  for (uint8_t channel = 0; channel < kChannelCount; ++channel) {
    const esp_err_t error = ledc_set_duty_with_hpoint(
        kSpeedMode, static_cast<ledc_channel_t>(channel), duty, hpoint);
    if (firstError == ESP_OK && error != ESP_OK) firstError = error;
  }
  if (firstError != ESP_OK) return firstError;

  for (uint8_t channel = 0; channel < kChannelCount; ++channel) {
    const esp_err_t error = ledc_update_duty(
        kSpeedMode, static_cast<ledc_channel_t>(channel));
    if (firstError == ESP_OK && error != ESP_OK) firstError = error;
  }
  return firstError;
}

esp_err_t UltrasonicDriver::stop() {
  return setAllDuty(0);
}

int UltrasonicDriver::gpioForChannel(uint8_t channel) const {
  return channel < kChannelCount ? kGpios[channel] : -1;
}

}  // namespace ultrasonic
