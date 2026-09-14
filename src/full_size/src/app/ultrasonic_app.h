#pragma once

#include <Arduino.h>
#include "driver/gptimer.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#include "../driver/gimbal_controller.h"
#include "../driver/ultrasonic_driver.h"
#include "../modulation/modulation_engine.h"
#include "../protocol/protocol_server.h"

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
    kCarrierOn,
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
    kStreamStart,
    kStreamStop,
    kProtocolMute,
    kProtocolHello,
  };

  struct Command {
    CommandType type = CommandType::kStop;
    uint32_t value = 0;
    uint32_t requestSequence = 0;
    AudioStreamParameters streamParameters = {};
  };

  static constexpr uint32_t kTimerEvent = 1U << 0;
  static constexpr uint32_t kCommandEvent = 1U << 1;
  static constexpr uint32_t kStreamDataEvent = 1U << 2;
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
  void handleProtocolByte(uint8_t input);
  void handleProtocolMessage(const ProtocolMessage& message);
  void handleProtocolHello(const ProtocolMessage& message);
  void handleProtocolStreamStart(const ProtocolMessage& message);
  void handleProtocolAudio(const ProtocolMessage& message);
  void handleProtocolGimbal(const ProtocolMessage& message);
  void reportProtocolStatus();
  void checkProtocolAudioTimeout();
  void handleNumericInput();
  void beginPoseInput();
  void handlePoseCharacter(char input);
  void handlePoseInput();
  void printHelp() const;
  bool enqueue(CommandType type, uint32_t value = 0);
  bool enqueue(const Command& command);

  bool handleCommand(const Command& command);
  void startCarrier();
  void startEnvelopeTone(uint32_t toneHz);
  void selectAudioModulation(AudioModulationMode mode);
  void selectAudioProcessing(AudioProcessingMode mode);
  void selectAudioDrive(AudioDriveMode mode);
  void adjustCarrier(int32_t deltaHz);
  void resetCarrier();
  void reportCarrier() const;
  void startAudio(bool loop);
  void startStream(const AudioStreamParameters& parameters,
                   uint32_t requestSequence);
  void startProtocolSession(uint32_t requestSequence);
  void stopStream(uint32_t requestSequence);
  void setProtocolMute(bool enabled, uint32_t requestSequence);
  void maybeStartStreamPlayback();
  void handleStreamUnderrun();
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
  GimbalController gimbal_;
  ModulationEngine modulationEngine_;
  ProtocolServer protocol_;
  QueueHandle_t commandQueue_ = nullptr;
  TaskHandle_t controlTaskHandle_ = nullptr;
  TaskHandle_t playbackTaskHandle_ = nullptr;
  gptimer_handle_t sampleTimer_ = nullptr;
  portMUX_TYPE timerMux_ = portMUX_INITIALIZER_UNLOCKED;

  uint32_t pendingTimerTicks_ = 0;
  uint32_t numericInputValue_ = 0;
  static constexpr size_t kPoseInputCapacity = 32;
  char poseInput_[kPoseInputCapacity] = {};
  size_t poseInputLength_ = 0;
  bool numericInputActive_ = false;
  bool numericInputOverflow_ = false;
  bool poseInputActive_ = false;
  bool poseInputOverflow_ = false;
  bool protocolCaptureActive_ = false;
  bool protocolMuted_ = true;
  bool protocolTimeoutQueued_ = false;
  bool sampleTimerRunning_ = false;
  ProtocolStreamState protocolStreamState_ = ProtocolStreamState::kIdle;
  uint32_t lastProtocolStatusMs_ = 0;
  uint32_t lastAudioDataMs_ = 0;
  uint32_t expectedAudioSampleIndex_ = 0;
  uint32_t audioSequenceGapCount_ = 0;
  bool receivedFirstAudioPacket_ = false;
  static constexpr uint32_t kProtocolStatusIntervalMs = 100;
  uint32_t protocolAudioTimeoutMs_ = 500;
  uint64_t skippedFrameCount_ = 0;
  uint32_t maximumTimerBacklog_ = 0;
};

}  // namespace ultrasonic
