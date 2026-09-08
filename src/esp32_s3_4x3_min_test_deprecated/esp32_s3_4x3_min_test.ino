#include <Arduino.h>

#include "src/app/ultrasonic_app.h"
#include "src/driver/ultrasonic_driver.h"

namespace {

ultrasonic::UltrasonicDriver gDriver;
ultrasonic::UltrasonicApp gApp(gDriver);

void reportStartupError(const char* stage, esp_err_t error) {
  Serial.printf("STARTUP ERROR (%s): %s\r\n", stage, esp_err_to_name(error));
  Serial.println("Output remains OFF.");
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(300);

  const esp_err_t driverError = gDriver.begin();
  if (driverError != ESP_OK) {
    reportStartupError("hardware driver", driverError);
    return;
  }

  const esp_err_t appError = gApp.begin();
  if (appError != ESP_OK) {
    gDriver.stop();
    reportStartupError("FreeRTOS manager", appError);
  }
}

void loop() {
  // 串口解析和调制播放均由 FreeRTOS 任务管理，Arduino loop 仅保持空闲。
  vTaskDelay(pdMS_TO_TICKS(1000));
}
