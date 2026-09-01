#include "ultrasonic_app.h"

namespace ultrasonic {
namespace {

constexpr uint32_t kCommandQueueLength = 8;
constexpr uint32_t kControlTaskStackBytes = 4096;
constexpr uint32_t kPlaybackTaskStackBytes = 4096;
constexpr UBaseType_t kControlTaskPriority = 2;
constexpr UBaseType_t kPlaybackTaskPriority = 8;
constexpr int32_t kCarrierStepHz = 100;
constexpr uint32_t kDefaultToneHz = 1000;

}  // namespace

esp_err_t UltrasonicApp::begin() {
  const DutyConfig dutyConfig = {
      UltrasonicDriver::kPeriodCounts,
      UltrasonicDriver::kHalfDuty,
  };
  if (!modulationEngine_.begin(dutyConfig)) return ESP_ERR_INVALID_ARG;

  commandQueue_ = xQueueCreate(kCommandQueueLength, sizeof(Command));
  if (commandQueue_ == nullptr) return ESP_ERR_NO_MEM;

  gptimer_config_t timerConfig = {};
  timerConfig.clk_src = GPTIMER_CLK_SRC_DEFAULT;
  timerConfig.direction = GPTIMER_COUNT_UP;
  timerConfig.resolution_hz = kSampleTimerResolutionHz;

  esp_err_t error = gptimer_new_timer(&timerConfig, &sampleTimer_);
  if (error != ESP_OK) {
    vQueueDelete(commandQueue_);
    commandQueue_ = nullptr;
    return error;
  }

  gptimer_event_callbacks_t timerCallbacks = {};
  timerCallbacks.on_alarm = &UltrasonicApp::timerEntry;
  error = gptimer_register_event_callbacks(
      sampleTimer_, &timerCallbacks, this);
  if (error != ESP_OK) {
    gptimer_del_timer(sampleTimer_);
    sampleTimer_ = nullptr;
    vQueueDelete(commandQueue_);
    commandQueue_ = nullptr;
    return error;
  }

  error = gptimer_enable(sampleTimer_);
  if (error != ESP_OK) {
    gptimer_del_timer(sampleTimer_);
    sampleTimer_ = nullptr;
    vQueueDelete(commandQueue_);
    commandQueue_ = nullptr;
    return error;
  }

  // GPTimer 中断在当前核心注册；播放任务固定到同一核心，避免跨核通知抖动。
  const BaseType_t playbackCore = xPortGetCoreID();
  BaseType_t taskResult = xTaskCreatePinnedToCore(
      &UltrasonicApp::playbackTaskEntry, "ultra_playback",
      kPlaybackTaskStackBytes, this, kPlaybackTaskPriority,
      &playbackTaskHandle_, playbackCore);
  if (taskResult != pdPASS) {
    gptimer_disable(sampleTimer_);
    gptimer_del_timer(sampleTimer_);
    sampleTimer_ = nullptr;
    vQueueDelete(commandQueue_);
    commandQueue_ = nullptr;
    return ESP_ERR_NO_MEM;
  }

  taskResult = xTaskCreate(
      &UltrasonicApp::controlTaskEntry, "ultra_control",
      kControlTaskStackBytes, this, kControlTaskPriority,
      &controlTaskHandle_);
  if (taskResult != pdPASS) {
    vTaskDelete(playbackTaskHandle_);
    playbackTaskHandle_ = nullptr;
    gptimer_disable(sampleTimer_);
    gptimer_del_timer(sampleTimer_);
    sampleTimer_ = nullptr;
    vQueueDelete(commandQueue_);
    commandQueue_ = nullptr;
    return ESP_ERR_NO_MEM;
  }

  return ESP_OK;
}

void UltrasonicApp::controlTaskEntry(void* context) {
  static_cast<UltrasonicApp*>(context)->controlTask();
}

void UltrasonicApp::playbackTaskEntry(void* context) {
  static_cast<UltrasonicApp*>(context)->playbackTask();
}

bool IRAM_ATTR UltrasonicApp::timerEntry(
    gptimer_handle_t timer, const gptimer_alarm_event_data_t* eventData,
    void* context) {
  (void)timer;
  (void)eventData;
  auto* app = static_cast<UltrasonicApp*>(context);
  if (app->playbackTaskHandle_ == nullptr) return false;

  portENTER_CRITICAL_ISR(&app->timerMux_);
  if (app->pendingTimerTicks_ != UINT32_MAX) {
    ++app->pendingTimerTicks_;
  }
  portEXIT_CRITICAL_ISR(&app->timerMux_);

  BaseType_t higherPriorityTaskWoken = pdFALSE;
  xTaskNotifyFromISR(app->playbackTaskHandle_, kTimerEvent, eSetBits,
                     &higherPriorityTaskWoken);
  return higherPriorityTaskWoken == pdTRUE;
}

void UltrasonicApp::controlTask() {
  printHelp();
  for (;;) {
    handleSerial();
    vTaskDelay(pdMS_TO_TICKS(2));
  }
}

void UltrasonicApp::playbackTask() {
  for (;;) {
    uint32_t events = 0;
    xTaskNotifyWait(0, UINT32_MAX, &events, portMAX_DELAY);

    bool timingReconfigured = false;
    if ((events & kCommandEvent) != 0) {
      Command command = {};
      while (xQueueReceive(commandQueue_, &command, 0) == pdTRUE) {
        timingReconfigured =
            handleCommand(command) || timingReconfigured;
      }
    }

    // 返回 false 的模式/频率选择命令不重置当前调制节拍；
    // 启停输出的命令会重置定时器，必须丢弃同时到达的旧节拍。
    if ((events & kTimerEvent) != 0 && !timingReconfigured) {
      processTimerTicks();
    }
  }
}

void UltrasonicApp::handleSerial() {
  while (Serial.available() > 0) {
    char input = static_cast<char>(Serial.read());
    if (input >= 'a' && input <= 'z') input -= ('a' - 'A');

    if (input >= '0' && input <= '9') {
      numericInputActive_ = true;
      const uint32_t digit = static_cast<uint32_t>(input - '0');
      if (numericInputValue_ > (UINT32_MAX - digit) / 10) {
        numericInputOverflow_ = true;
      } else if (!numericInputOverflow_) {
        numericInputValue_ = numericInputValue_ * 10 + digit;
      }
      continue;
    }

    if (input == '\r' || input == '\n' || input == ' ') {
      if (numericInputActive_) handleNumericInput();
      continue;
    }

    if (numericInputActive_) {
      Serial.println("NUMBER ERROR: terminate the frequency with Enter");
      numericInputValue_ = 0;
      numericInputActive_ = false;
      numericInputOverflow_ = false;
    }

    switch (input) {
      case 'A':
        enqueue(CommandType::kCarrierOn);
        break;
      case 'T':
        enqueue(CommandType::kEnvelopeTone, kDefaultToneHz);
        break;
      case 'D':
        enqueue(CommandType::kUseDsbAm);
        break;
      case 'S':
        enqueue(CommandType::kUseSram);
        break;
      case 'R':
        enqueue(CommandType::kUseRawAudio);
        break;
      case 'E':
        enqueue(CommandType::kUseEnhancedAudio);
        break;
      case 'N':
        enqueue(CommandType::kUseStandardDrive);
        break;
      case 'B':
        enqueue(CommandType::kUseBoostDrive);
        break;
      case '-':
      case '[':
        enqueue(CommandType::kCarrierDown);
        break;
      case '+':
      case ']':
        enqueue(CommandType::kCarrierUp);
        break;
      case 'C':
        enqueue(CommandType::kCarrierReset);
        break;
      case 'F':
        enqueue(CommandType::kCarrierReport);
        break;
      case 'P':
        enqueue(CommandType::kAudioOnce);
        break;
      case 'L':
        enqueue(CommandType::kAudioLoop);
        break;
      case 'H':
      case '?':
        printHelp();
        break;
      default:
        Serial.printf("Unknown command: 0x%02X. Send H for help.\r\n",
                      static_cast<unsigned int>(
                          static_cast<unsigned char>(input)));
        break;
    }
  }
}

void UltrasonicApp::handleNumericInput() {
  const uint32_t value = numericInputValue_;
  const bool overflow = numericInputOverflow_;
  numericInputValue_ = 0;
  numericInputActive_ = false;
  numericInputOverflow_ = false;

  if (overflow) {
    Serial.println("NUMBER ERROR: value is too large");
    return;
  }
  if (value == 0) {
    enqueue(CommandType::kStop);
    return;
  }
  if (value < EnvelopeModulator::kMinimumToneHz ||
      value > EnvelopeModulator::kMaximumToneHz) {
    Serial.printf("TONE ERROR: enter %lu..%lu Hz, then press Enter\r\n",
                  static_cast<unsigned long>(
                      EnvelopeModulator::kMinimumToneHz),
                  static_cast<unsigned long>(
                      EnvelopeModulator::kMaximumToneHz));
    return;
  }

  enqueue(CommandType::kEnvelopeTone, value);
}

void UltrasonicApp::printHelp() const {
  Serial.println();
  Serial.println("=== ESP32-S3 120-element ultrasonic array ===");
  Serial.println("0 + Enter : stop GPIO4 switching");
  Serial.println("A : enable the complete array at 50% carrier duty");
  Serial.println("T : 1 kHz envelope test on the complete array");
  Serial.println("20..3000 + Enter : play that audible sine frequency in Hz");
  Serial.println("D : select DSB-AM for the next audio playback (default)");
  Serial.println("S : select square-root AM (SRAM) for the next playback");
  Serial.println("E : enhanced audio level for next playback (default)");
  Serial.println("R : raw PCM level for the next playback (A/B reference)");
  Serial.println("B : boosted envelope depth for the next tone/audio (default)");
  Serial.println("N : standard envelope depth for the next tone/audio");
  Serial.println("-/[ and +/] : tune carrier down/up by 100 Hz");
  Serial.println("C : reset carrier to 40 kHz; F : report actual carrier");
  Serial.println("P : play embedded audio once");
  Serial.println("L : loop embedded audio");
  Serial.println("H : print this help");
  Serial.println("Power-up default is OFF. Commands are case-insensitive.");
  Serial.println("GPIO4 is copied to 12 TC4428 branches by external buffers.");
  Serial.println("Software stop is not 12 V isolation; disconnect power before rewiring.");
  Serial.println();
}

bool UltrasonicApp::enqueue(CommandType type, uint32_t value) {
  const Command command = {type, value};
  if (xQueueSend(commandQueue_, &command, pdMS_TO_TICKS(20)) != pdTRUE) {
    Serial.println("COMMAND ERROR: queue is full");
    return false;
  }

  xTaskNotify(playbackTaskHandle_, kCommandEvent, eSetBits);
  return true;
}

bool UltrasonicApp::handleCommand(const Command& command) {
  switch (command.type) {
    case CommandType::kStop:
      stopOutput();
      return true;
    case CommandType::kCarrierOn:
      startCarrier();
      return true;
    case CommandType::kEnvelopeTone:
      startEnvelopeTone(command.value);
      return true;
    case CommandType::kUseDsbAm:
      selectAudioModulation(AudioModulationMode::kDsbAm);
      return false;
    case CommandType::kUseSram:
      selectAudioModulation(AudioModulationMode::kSram);
      return false;
    case CommandType::kUseRawAudio:
      selectAudioProcessing(AudioProcessingMode::kRaw);
      return false;
    case CommandType::kUseEnhancedAudio:
      selectAudioProcessing(AudioProcessingMode::kLoudnessEnhanced);
      return false;
    case CommandType::kUseStandardDrive:
      selectAudioDrive(AudioDriveMode::kStandard);
      return false;
    case CommandType::kUseBoostDrive:
      selectAudioDrive(AudioDriveMode::kBoost);
      return false;
    case CommandType::kCarrierDown:
      adjustCarrier(-kCarrierStepHz);
      return false;
    case CommandType::kCarrierUp:
      adjustCarrier(kCarrierStepHz);
      return false;
    case CommandType::kCarrierReset:
      resetCarrier();
      return false;
    case CommandType::kCarrierReport:
      reportCarrier();
      return false;
    case CommandType::kAudioOnce:
      startAudio(false);
      return true;
    case CommandType::kAudioLoop:
      startAudio(true);
      return true;
  }

  return false;
}

void UltrasonicApp::startCarrier() {
  stopSampleTimer();
  reportTimingStats();
  resetTimingStats();
  modulationEngine_.stop();
  if (!applyDriverResult(
          driver_.setDuty(UltrasonicDriver::kHalfDuty),
          "enable array carrier")) {
    return;
  }

  Serial.printf("ARRAY ON: GPIO4, 120 elements, %lu Hz, 50%%\r\n",
                static_cast<unsigned long>(driver_.carrierHz()));
}

void UltrasonicApp::startEnvelopeTone(uint32_t toneHz) {
  stopSampleTimer();
  reportTimingStats();
  resetTimingStats();
  if (!modulationEngine_.startEnvelopeTone(toneHz)) {
    Serial.println("MODULATION ERROR: envelope modulator is not ready");
    stopOutput(false);
    return;
  }

  Serial.printf(
      "TEST TONE: %lu Hz sine, %lu Hz carrier, %s drive, complete array\r\n",
      static_cast<unsigned long>(toneHz),
      static_cast<unsigned long>(driver_.carrierHz()),
      audioDriveModeName(modulationEngine_.audioDriveMode()));
  Serial.println("This is only a bench test; the audible tone may be weak.");
  renderTimedSample();
}

void UltrasonicApp::selectAudioModulation(AudioModulationMode mode) {
  modulationEngine_.setAudioModulationMode(mode);
  Serial.printf("AUDIO MODULATION: %s (applies on next P/L command)\r\n",
                audioModulationModeName(mode));
}

void UltrasonicApp::selectAudioProcessing(AudioProcessingMode mode) {
  modulationEngine_.setAudioProcessingMode(mode);
  Serial.printf("AUDIO LEVEL: %s (applies on next P/L command)\r\n",
                audioProcessingModeName(mode));
}

void UltrasonicApp::selectAudioDrive(AudioDriveMode mode) {
  modulationEngine_.setAudioDriveMode(mode);
  Serial.printf("DRIVE: %s (applies on next tone or P/L command)\r\n",
                audioDriveModeName(mode));
}

void UltrasonicApp::adjustCarrier(int32_t deltaHz) {
  int32_t target = static_cast<int32_t>(driver_.carrierHz()) + deltaHz;
  if (target < static_cast<int32_t>(UltrasonicDriver::kMinimumCarrierHz)) {
    target = UltrasonicDriver::kMinimumCarrierHz;
  }
  if (target > static_cast<int32_t>(UltrasonicDriver::kMaximumCarrierHz)) {
    target = UltrasonicDriver::kMaximumCarrierHz;
  }

  if (!applyDriverResult(
          driver_.setCarrierFrequency(static_cast<uint32_t>(target)),
          "tune carrier")) {
    return;
  }
  reportCarrier();
}

void UltrasonicApp::resetCarrier() {
  if (!applyDriverResult(
          driver_.setCarrierFrequency(UltrasonicDriver::kDefaultCarrierHz),
          "reset carrier")) {
    return;
  }
  reportCarrier();
}

void UltrasonicApp::reportCarrier() const {
  Serial.printf("CARRIER: %lu Hz (range 38000..42000, step 100)\r\n",
                static_cast<unsigned long>(driver_.carrierHz()));
}

void UltrasonicApp::startAudio(bool loop) {
  stopSampleTimer();
  reportTimingStats();
  resetTimingStats();
  if (!modulationEngine_.startAudio(loop)) {
    Serial.println("AUDIO ERROR: src/data/audio_data.h contains no valid samples");
    stopOutput(false);
    return;
  }

  const AudioInfo audio = modulationEngine_.audioInfo();
  const char* modulationName = audioModulationModeName(
      modulationEngine_.audioModulationMode());
  const char* processingName = audioProcessingModeName(
      modulationEngine_.audioProcessingMode());
  const char* driveName = audioDriveModeName(
      modulationEngine_.audioDriveMode());
  Serial.printf("AUDIO %s %s %s %s: %lu samples at %lu Hz (%.2f s), carrier %lu Hz\r\n",
                modulationName,
                processingName,
                driveName,
                loop ? "LOOP" : "PLAY ONCE",
                static_cast<unsigned long>(audio.sampleCount),
                static_cast<unsigned long>(audio.sampleRate),
                static_cast<double>(audio.sampleCount) /
                    static_cast<double>(audio.sampleRate),
                static_cast<unsigned long>(driver_.carrierHz()));
  renderTimedSample();
}

void UltrasonicApp::stopOutput(bool printStatus) {
  stopSampleTimer();
  modulationEngine_.stop();
  applyDriverResult(driver_.stop(), "stop output");
  if (printStatus) {
    Serial.println(
        "OUTPUT OFF (PWM stopped; switch off driver 12 V before rewiring)");
  }
  reportTimingStats();
  resetTimingStats();
}

void UltrasonicApp::renderTimedSample() {
  const ModulationFrame frame = modulationEngine_.nextFrame();
  if (frame.status == ModulationFrameStatus::kIdle) return;

  if (!applyDriverResult(driver_.setDuty(frame.duty),
                         "write modulation frame")) {
    return;
  }

  if (frame.status == ModulationFrameStatus::kCompleted) {
    completeAudioPlayback();
    return;
  }

  if (!sampleTimerRunning_) startSampleTimer(frame.sampleRateHz);
}

void UltrasonicApp::processTimerTicks() {
  const uint32_t elapsedTicks = takePendingTimerTicks();
  if (elapsedTicks == 0) return;

  if (elapsedTicks > maximumTimerBacklog_) {
    maximumTimerBacklog_ = elapsedTicks;
  }

  if (elapsedTicks > 1) {
    const uint32_t staleFrames = elapsedTicks - 1;
    skippedFrameCount_ += staleFrames;
    const ModulationFrameStatus status =
        modulationEngine_.skipFrames(staleFrames);
    if (status == ModulationFrameStatus::kCompleted) {
      completeAudioPlayback();
      return;
    }
  }

  renderTimedSample();
}

void UltrasonicApp::completeAudioPlayback() {
  stopSampleTimer();
  modulationEngine_.stop();
  if (!applyDriverResult(driver_.stop(), "finish audio")) return;

  Serial.println("AUDIO DONE; output stopped");
  reportTimingStats();
  resetTimingStats();
}

bool UltrasonicApp::startSampleTimer(uint32_t sampleRateHz) {
  if (sampleTimer_ == nullptr || sampleRateHz == 0 ||
      sampleRateHz > kSampleTimerResolutionHz) {
    applyDriverResult(ESP_ERR_INVALID_ARG, "configure sample timer");
    return false;
  }

  stopSampleTimer();
  clearPendingTimerTicks();

  const uint64_t alarmTicks =
      (static_cast<uint64_t>(kSampleTimerResolutionHz) + sampleRateHz / 2) /
      sampleRateHz;
  gptimer_alarm_config_t alarmConfig = {};
  alarmConfig.alarm_count = alarmTicks;
  alarmConfig.reload_count = 0;
  alarmConfig.flags.auto_reload_on_alarm = true;

  esp_err_t error = gptimer_set_raw_count(sampleTimer_, 0);
  if (error == ESP_OK) {
    error = gptimer_set_alarm_action(sampleTimer_, &alarmConfig);
  }
  if (error == ESP_OK) error = gptimer_start(sampleTimer_);
  if (error != ESP_OK) {
    applyDriverResult(error, "start sample timer");
    return false;
  }

  sampleTimerRunning_ = true;
  return true;
}

void UltrasonicApp::stopSampleTimer() {
  if (sampleTimer_ == nullptr) return;

  esp_err_t error = ESP_OK;
  if (sampleTimerRunning_) error = gptimer_stop(sampleTimer_);
  sampleTimerRunning_ = false;
  clearPendingTimerTicks();

  if (error != ESP_OK) {
    Serial.printf("TIMER ERROR (stop): %s\r\n", esp_err_to_name(error));
  }
}

uint32_t UltrasonicApp::takePendingTimerTicks() {
  portENTER_CRITICAL(&timerMux_);
  const uint32_t result = pendingTimerTicks_;
  pendingTimerTicks_ = 0;
  portEXIT_CRITICAL(&timerMux_);
  return result;
}

void UltrasonicApp::clearPendingTimerTicks() {
  portENTER_CRITICAL(&timerMux_);
  pendingTimerTicks_ = 0;
  portEXIT_CRITICAL(&timerMux_);
}

void UltrasonicApp::resetTimingStats() {
  skippedFrameCount_ = 0;
  maximumTimerBacklog_ = 0;
}

void UltrasonicApp::reportTimingStats() const {
  if (skippedFrameCount_ == 0) return;

  Serial.printf(
      "TIMING WARNING: skipped %llu stale samples; max backlog %lu ticks\r\n",
      static_cast<unsigned long long>(skippedFrameCount_),
      static_cast<unsigned long>(maximumTimerBacklog_));
}

bool UltrasonicApp::applyDriverResult(esp_err_t error,
                                      const char* operation) {
  if (error == ESP_OK) return true;

  stopSampleTimer();
  modulationEngine_.stop();
  driver_.stop();
  Serial.printf("RUNTIME ERROR (%s): %s\r\n", operation,
                esp_err_to_name(error));
  return false;
}

}  // namespace ultrasonic
