#include "gimbal_controller.h"

namespace ultrasonic {

uint32_t GimbalController::angleToDuty(int32_t logicalDegrees,
                                       int32_t direction) {
  const int32_t directedDegrees = logicalDegrees * direction;
  const int32_t pulseMicroseconds =
      static_cast<int32_t>(kCenterPulseMicroseconds) +
      directedDegrees *
          static_cast<int32_t>(kMaximumPulseMicroseconds -
                               kMinimumPulseMicroseconds) /
          (kMaximumAngle - kMinimumAngle);

  return static_cast<uint32_t>(
      (static_cast<uint64_t>(pulseMicroseconds) * kPeriodCounts +
       kPeriodMicroseconds / 2) /
      kPeriodMicroseconds);
}

esp_err_t GimbalController::begin() {
  if (initialized_) return ESP_OK;

  // Hold both signal pins low until the 50 Hz timer is configured.
  pinMode(kPanGpio, OUTPUT);
  pinMode(kTiltGpio, OUTPUT);
  digitalWrite(kPanGpio, LOW);
  digitalWrite(kTiltGpio, LOW);

  ledc_timer_config_t timerConfig = {};
  timerConfig.speed_mode = kSpeedMode;
  timerConfig.duty_resolution = kResolution;
  timerConfig.timer_num = kTimer;
  timerConfig.freq_hz = kServoFrequencyHz;
  timerConfig.clk_cfg = LEDC_USE_APB_CLK;

  esp_err_t error = ledc_timer_config(&timerConfig);
  if (error != ESP_OK) return error;

  ledc_channel_config_t channelConfig = {};
  channelConfig.speed_mode = kSpeedMode;
  channelConfig.intr_type = LEDC_INTR_DISABLE;
  channelConfig.timer_sel = kTimer;
  channelConfig.hpoint = 0;
  channelConfig.flags.output_invert = 0;
  channelConfig.duty = angleToDuty(0, 1);

  channelConfig.gpio_num = kPanGpio;
  channelConfig.channel = kPanChannel;
  error = ledc_channel_config(&channelConfig);
  if (error != ESP_OK) return error;

  channelConfig.gpio_num = kTiltGpio;
  channelConfig.channel = kTiltChannel;
  error = ledc_channel_config(&channelConfig);
  if (error != ESP_OK) return error;

  initialized_ = true;
  return setAngles(0, 0);
}

esp_err_t GimbalController::setAngles(int32_t panDegrees,
                                      int32_t tiltDegrees) {
  if (!initialized_) return ESP_ERR_INVALID_STATE;
  if (panDegrees < kMinimumAngle || panDegrees > kMaximumAngle ||
      tiltDegrees < kMinimumAngle || tiltDegrees > kMaximumAngle) {
    return ESP_ERR_INVALID_ARG;
  }

  esp_err_t error = writeChannel(
      kPanChannel, angleToDuty(panDegrees + kPanCompensationDegrees, kPanDirection));
  if (error != ESP_OK) return error;

  error = writeChannel(
      kTiltChannel, angleToDuty(tiltDegrees, kTiltDirection));
  if (error != ESP_OK) return error;

  panDegrees_ = panDegrees;
  tiltDegrees_ = tiltDegrees;
  return ESP_OK;
}

esp_err_t GimbalController::writeChannel(ledc_channel_t channel,
                                         uint32_t duty) {
  esp_err_t error = ledc_set_duty(kSpeedMode, channel, duty);
  if (error != ESP_OK) return error;
  return ledc_update_duty(kSpeedMode, channel);
}

}  // namespace ultrasonic
