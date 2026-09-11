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
#if !ARDUINO_USB_CDC_ON_BOOT
  // HardwareSerial defaults to 256 bytes, barely more than one 185-byte
  // AUDIO_DATA frame. Leave room for queued host packets and control-task jitter.
  // This UART ring is separate from the 2048-sample decoded audio buffer.
  Serial.setRxBufferSize(4096);
#endif
  Serial.begin(460800);
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
