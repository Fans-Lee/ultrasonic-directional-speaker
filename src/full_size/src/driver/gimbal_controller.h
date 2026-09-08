#pragma once

#include <Arduino.h>
#include "driver/ledc.h"
#include "esp_err.h"

namespace ultrasonic {

// MG996R two-axis gimbal driver. Logical 0 degrees is the 1.5 ms servo
// midpoint; commands use signed angles in the range -90..90 degrees.
class GimbalController final {
 public:
  static constexpr int kTiltGpio = 5;
  static constexpr int kPanGpio = 6;
  static constexpr int32_t kMinimumAngle = -90;
  static constexpr int32_t kMaximumAngle = 90;
  static constexpr int32_t kPanCompensationDegrees = 112;
  static constexpr int32_t kTiltCompensationDegrees = 12;
  esp_err_t begin();
  esp_err_t setAngles(int32_t panDegrees, int32_t tiltDegrees);

  int32_t panDegrees() const { return panDegrees_; }
  int32_t tiltDegrees() const { return tiltDegrees_; }

 private:
  static constexpr ledc_mode_t kSpeedMode = LEDC_LOW_SPEED_MODE;
  static constexpr ledc_timer_t kTimer = LEDC_TIMER_1;
  static constexpr ledc_timer_bit_t kResolution = LEDC_TIMER_14_BIT;
  static constexpr ledc_channel_t kPanChannel = LEDC_CHANNEL_1;
  static constexpr ledc_channel_t kTiltChannel = LEDC_CHANNEL_2;
  static constexpr uint32_t kServoFrequencyHz = 50;
  static constexpr uint32_t kPeriodCounts = 1U << 14;
  static constexpr uint32_t kPeriodMicroseconds = 20000;
  static constexpr uint32_t kMinimumPulseMicroseconds = 1000;
  static constexpr uint32_t kCenterPulseMicroseconds = 1500;
  static constexpr uint32_t kMaximumPulseMicroseconds = 2000;

  // Change either value to -1 if that axis moves opposite to the desired
  // logical direction after the servos are mounted.
  static constexpr int32_t kPanDirection = 1;
  static constexpr int32_t kTiltDirection = 1;

  static uint32_t angleToDuty(int32_t logicalDegrees,
                              int32_t direction);
  esp_err_t writeChannel(ledc_channel_t channel, uint32_t duty);

  bool initialized_ = false;
  int32_t panDegrees_ = 0;
  int32_t tiltDegrees_ = 0;
};

}  // namespace ultrasonic
