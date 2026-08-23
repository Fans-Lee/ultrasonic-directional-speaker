#pragma once

#include <Arduino.h>
#include "driver/gptimer.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#include "../driver/ultrasonic_driver.h"
#include "../modulation/modulation_engine.h"

namespace ultrasonic {

// 软件管理层：串口任务负责接收命令，播放任务独占硬件 driver。
// GPTimer ISR 只累计节拍并唤醒播放任务，不在中断中访问硬件或打印串口。
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
    kUseDsbAm,
    kUseSram,
    kUseRawAudio,
    kUseEnhancedAudio,
    kUseStandardDrive,
    kUseBoostDrive,
    kCarrierDown,
    kCarrierUp,
    kCarrierReset,
    kCarrierReport,
    kAudioOnce,
    kAudioLoop,
  };

  struct Command {
    CommandType type;
    uint32_t value;
  };

  static constexpr uint32_t kTimerEvent = 1U << 0;
  static constexpr uint32_t kCommandEvent = 1U << 1;
  // GPTimer 的 APB 分频器最小值为 2：80 MHz / 2 = 40 MHz。
  static constexpr uint32_t kSampleTimerResolutionHz = 40000000;

  static void controlTaskEntry(void* context);
  static void playbackTaskEntry(void* context);
  static bool IRAM_ATTR timerEntry(
      gptimer_handle_t timer, const gptimer_alarm_event_data_t* eventData,
      void* context);

  void controlTask();
  void playbackTask();
  void handleSerial();
  void handleNumericInput();
  void printHelp() const;
  bool enqueue(CommandType type, uint32_t value = 0);

  bool handleCommand(const Command& command);
  void startSingle(uint8_t channel);
  void startAllCarrier();
  void startEnvelopeTone(uint32_t toneHz);
  void selectAudioModulation(AudioModulationMode mode);
  void selectAudioProcessing(AudioProcessingMode mode);
  void selectAudioDrive(AudioDriveMode mode);
  void adjustCarrier(int32_t deltaHz);
  void resetCarrier();
  void reportCarrier() const;
  void startAudio(bool loop);
  void stopOutput(bool printStatus = true);

  void renderTimedSample();
  void processTimerTicks();
  void completeAudioPlayback();
  bool startSampleTimer(uint32_t sampleRateHz);
  void stopSampleTimer();
  uint32_t takePendingTimerTicks();
  void clearPendingTimerTicks();
  void resetTimingStats();
  void reportTimingStats() const;
  bool applyDriverResult(esp_err_t error, const char* operation);

  UltrasonicDriver& driver_;
  ModulationEngine modulationEngine_;
  QueueHandle_t commandQueue_ = nullptr;
  TaskHandle_t controlTaskHandle_ = nullptr;
  TaskHandle_t playbackTaskHandle_ = nullptr;
  gptimer_handle_t sampleTimer_ = nullptr;
  portMUX_TYPE timerMux_ = portMUX_INITIALIZER_UNLOCKED;

  uint32_t pendingTimerTicks_ = 0;
  uint32_t numericInputValue_ = 0;
  bool numericInputActive_ = false;
  bool numericInputOverflow_ = false;
  bool sampleTimerRunning_ = false;
  uint64_t skippedFrameCount_ = 0;
  uint32_t maximumTimerBacklog_ = 0;
};

}  // namespace ultrasonic
