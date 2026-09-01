#include <Arduino.h>

#include "src/app/ultrasonic_app.h"
#include "src/driver/ultrasonic_driver.h"

namespace {

ultrasonic::UltrasonicDriver gDriver;
ultrasonic::UltrasonicApp gApp(gDriver);

void reportStartupError(const char* stage, esp_err_t error) {
  Serial.printf("STARTUP ERROR (%s): %s\r\n", stage,
                esp_err_to_name(error));
  Serial.println("GPIO4 switching remains OFF.");
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(300);

  const esp_err_t driverError = gDriver.begin();
  if (driverError != ESP_OK) {
    reportStartupError("single-GPIO carrier driver", driverError);
    return;
  }

  const esp_err_t appError = gApp.begin();
  if (appError != ESP_OK) {
    gDriver.stop();
    reportStartupError("FreeRTOS playback manager", appError);
  }
}

void loop() {
  // Serial control and modulation playback run in FreeRTOS tasks.
  vTaskDelay(pdMS_TO_TICKS(1000));
}
