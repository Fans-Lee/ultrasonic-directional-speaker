#include "ultrasonic_driver.h"

namespace ultrasonic {

esp_err_t UltrasonicDriver::begin() {
  if (initialized_) return ESP_OK;

  // The 120-element board has one logical input. Keep it low until LEDC is
  // configured so the twelve TC4428 branches cannot receive a startup burst.
  pinMode(kOutputGpio, OUTPUT);
  digitalWrite(kOutputGpio, LOW);

  ledc_timer_config_t timerConfig = {};
  timerConfig.speed_mode = kSpeedMode;
  timerConfig.duty_resolution = kResolution;
  timerConfig.timer_num = kTimer;
  timerConfig.freq_hz = carrierHz_;
  // 80 MHz APB / (40 kHz * 1024) = 500/256，可由 LEDC 精确分频。
  timerConfig.clk_cfg = LEDC_USE_APB_CLK;

  esp_err_t error = ledc_timer_config(&timerConfig);
  if (error != ESP_OK) return error;

  ledc_channel_config_t channelConfig = {};
  channelConfig.gpio_num = kOutputGpio;
  channelConfig.speed_mode = kSpeedMode;
  channelConfig.channel = kChannel;
  channelConfig.intr_type = LEDC_INTR_DISABLE;
  channelConfig.timer_sel = kTimer;
  channelConfig.duty = 0;
  channelConfig.hpoint = 0;
  channelConfig.flags.output_invert = 0;

  error = ledc_channel_config(&channelConfig);
  if (error != ESP_OK) return error;

  initialized_ = true;
  return stop();
}

// Set the only array input while keeping the pulse centered in the carrier
// period. Envelope-to-duty conversion belongs to the modulation layer.
esp_err_t UltrasonicDriver::setDuty(uint32_t duty) {
  if (!initialized_) return ESP_ERR_INVALID_STATE;
  if (duty > kHalfDuty) duty = kHalfDuty;

  // Center both moving edges to reduce unintended phase modulation.
  const uint32_t hpoint = duty == 0 ? 0 : (kPeriodCounts - duty) / 2;
  esp_err_t error = ledc_set_duty_with_hpoint(
      kSpeedMode, kChannel, duty, hpoint);
  if (error != ESP_OK) return error;

  return ledc_update_duty(kSpeedMode, kChannel);
}

esp_err_t UltrasonicDriver::setCarrierFrequency(uint32_t frequencyHz) {
  if (!initialized_) return ESP_ERR_INVALID_STATE;
  if (frequencyHz < kMinimumCarrierHz ||
      frequencyHz > kMaximumCarrierHz) {
    return ESP_ERR_INVALID_ARG;
  }

  const esp_err_t error = ledc_set_freq(kSpeedMode, kTimer, frequencyHz);
  if (error != ESP_OK) return error;

  const uint32_t actualFrequency = ledc_get_freq(kSpeedMode, kTimer);
  if (actualFrequency == 0) return ESP_FAIL;
  carrierHz_ = actualFrequency;
  return ESP_OK;
}

esp_err_t UltrasonicDriver::stop() {
  return setDuty(0);
}

}  // namespace ultrasonic
