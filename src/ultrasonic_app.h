#pragma once

#include <Arduino.h>
#include "esp_err.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#include "modulation_engine.h"
#include "ultrasonic_driver.h"

namespace ultrasonic {

// 软件管理层：串口任务负责接收命令，播放任务独占硬件 driver。
// 微秒定时器只唤醒播放任务，不在回调中访问硬件或打印串口。
class UltrasonicApp final {
 public:
  explicit UltrasonicApp(UltrasonicDriver& driver) : driver_(driver) {}

  esp_err_t begin();

 private:
  enum class CommandType : uint8_t {
    kStop,
    kSingle,
    kAllCarrier,
    kEnvelopeTone,
    kAudioOnce,
    kAudioLoop,
  };

  struct Command {
    CommandType type;
    uint8_t channel;
  };

  static constexpr uint32_t kTimerEvent = 1U << 0;
  static constexpr uint32_t kCommandEvent = 1U << 1;

  static void controlTaskEntry(void* context);
  static void playbackTaskEntry(void* context);
  static void timerEntry(void* context);

  void controlTask();
  void playbackTask();
  void handleSerial();
  void printHelp() const;
  bool enqueue(CommandType type, uint8_t channel = 0);

  void handleCommand(const Command& command);
  void startSingle(uint8_t channel);
  void startAllCarrier();
  void startEnvelopeTone();
  void startAudio(bool loop);
  void stopOutput(bool printStatus = true);

  void renderTimedSample();
  void scheduleNextSample(uint32_t intervalUs);
  void stopSampleTimer();
  bool applyDriverResult(esp_err_t error, const char* operation);

  UltrasonicDriver& driver_;
  ModulationEngine modulationEngine_;
  QueueHandle_t commandQueue_ = nullptr;
  TaskHandle_t controlTaskHandle_ = nullptr;
  TaskHandle_t playbackTaskHandle_ = nullptr;
  esp_timer_handle_t sampleTimer_ = nullptr;

  int64_t nextSampleUs_ = 0;
};

}  // namespace ultrasonic
