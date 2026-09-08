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
  esp_err_t error = gimbal_.begin();
  if (error != ESP_OK) return error;

  const DutyConfig dutyConfig = {
      UltrasonicDriver::kPeriodCounts,
      UltrasonicDriver::kHalfDuty,
  };
  if (!modulationEngine_.begin(dutyConfig)) return ESP_ERR_INVALID_ARG;
  if (!protocol_.begin()) return ESP_ERR_NO_MEM;

  commandQueue_ = xQueueCreate(kCommandQueueLength, sizeof(Command));
  if (commandQueue_ == nullptr) return ESP_ERR_NO_MEM;

  gptimer_config_t timerConfig = {};
  timerConfig.clk_src = GPTIMER_CLK_SRC_DEFAULT;
  timerConfig.direction = GPTIMER_COUNT_UP;
  timerConfig.resolution_hz = kSampleTimerResolutionHz;

  error = gptimer_new_timer(&timerConfig, &sampleTimer_);
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

  // The competition demo starts centered and continuously plays the embedded
  // audio. Servo commands are handled by the lower-priority control task while
  // the playback task keeps rendering 8 kHz modulation frames.
  //if (!enqueue(CommandType::kAudioLoop)) return ESP_FAIL;
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
    checkProtocolAudioTimeout();
    reportProtocolStatus();
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
    if ((events & kStreamDataEvent) != 0 && !timingReconfigured) {
      maybeStartStreamPlayback();
    }
  }
}

void UltrasonicApp::handleSerial() {
  while (Serial.available() > 0) {
    const uint8_t rawInput = static_cast<uint8_t>(Serial.read());
    if (protocol_.sessionActive() || protocolCaptureActive_ || rawInput == 0) {
      handleProtocolByte(rawInput);
      continue;
    }
    char input = static_cast<char>(rawInput);

    if (poseInputActive_) {
      handlePoseCharacter(input);
      continue;
    }
    if (input == '(') {
      beginPoseInput();
      continue;
    }

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

void UltrasonicApp::handleProtocolByte(uint8_t input) {
  if (!protocol_.sessionActive() && !protocolCaptureActive_) {
    protocol_.resetReceiver();
    protocolCaptureActive_ = true;
    return;
  }
  ProtocolMessage message = {};
  const bool complete = protocol_.feed(input, &message);
  if (!protocol_.sessionActive() && input == 0) protocolCaptureActive_ = false;
  if (complete) handleProtocolMessage(message);
}

void UltrasonicApp::handleProtocolMessage(const ProtocolMessage& message) {
  if (message.type == ProtocolMessageType::kHello) {
    handleProtocolHello(message);
    return;
  }
  if (!protocol_.sessionActive() || message.sessionId != protocol_.sessionId()) {
    return;
  }
  if ((message.flags & kAckRequired) != 0 &&
      protocol_.resendCachedAckIfDuplicate(message.type, message.sequence)) {
    return;
  }
  switch (message.type) {
    case ProtocolMessageType::kStreamStart:
      handleProtocolStreamStart(message);
      break;
    case ProtocolMessageType::kAudioData:
      handleProtocolAudio(message);
      break;
    case ProtocolMessageType::kStreamStop: {
      Command command = {};
      command.type = CommandType::kStreamStop;
      command.requestSequence = message.sequence;
      if (!enqueue(command)) {
        protocol_.sendAck(message.type, message.sequence, 1, 1);
      }
      break;
    }
    case ProtocolMessageType::kSetMute: {
      if (message.payloadLength != 1 || message.payload[0] > 1) {
        protocol_.sendAck(message.type, message.sequence, 1, 2);
        break;
      }
      Command command = {};
      command.type = CommandType::kProtocolMute;
      command.value = message.payload[0];
      command.requestSequence = message.sequence;
      if (!enqueue(command)) {
        protocol_.sendAck(message.type, message.sequence, 1, 1);
      }
      break;
    }
    case ProtocolMessageType::kGimbalSetpoint:
      handleProtocolGimbal(message);
      break;
    case ProtocolMessageType::kPing:
      if (message.payloadLength == 4) {
        const uint32_t nonce = static_cast<uint32_t>(message.payload[0]) |
                               (static_cast<uint32_t>(message.payload[1]) << 8) |
                               (static_cast<uint32_t>(message.payload[2]) << 16) |
                               (static_cast<uint32_t>(message.payload[3]) << 24);
        protocol_.sendPong(nonce);
      }
      break;
    default:
      if ((message.flags & kAckRequired) != 0) {
        protocol_.sendAck(message.type, message.sequence, 1, 3);
      }
      break;
  }
}

void UltrasonicApp::handleProtocolHello(const ProtocolMessage& message) {
  if (message.payloadLength != 8 || message.sessionId == 0) return;
  protocol_.startSession(message.sessionId);
  protocolCaptureActive_ = false;
  Command command = {};
  command.type = CommandType::kProtocolHello;
  command.requestSequence = message.sequence;
  enqueue(command);
}

void UltrasonicApp::handleProtocolStreamStart(
    const ProtocolMessage& message) {
  if (message.payloadLength != 16) {
    protocol_.sendAck(message.type, message.sequence, 1, 2);
    return;
  }
  const auto readU16 = [](const uint8_t* data) {
    return static_cast<uint16_t>(data[0]) |
           (static_cast<uint16_t>(data[1]) << 8);
  };
  const auto readU32 = [](const uint8_t* data) {
    return static_cast<uint32_t>(data[0]) |
           (static_cast<uint32_t>(data[1]) << 8) |
           (static_cast<uint32_t>(data[2]) << 16) |
           (static_cast<uint32_t>(data[3]) << 24);
  };
  const uint32_t sampleRate = readU32(&message.payload[0]);
  const uint16_t packetSamples = readU16(&message.payload[4]);
  const uint16_t prebufferSamples = readU16(&message.payload[6]);
  const uint8_t sampleFormat = message.payload[8];
  const uint8_t channels = message.payload[9];
  const uint8_t modulation = message.payload[10];
  const uint8_t processing = message.payload[11];
  const uint8_t drive = message.payload[12];
  const uint16_t dataTimeoutMs = readU16(&message.payload[14]);
  if (sampleRate != 8000 || packetSamples == 0 || packetSamples > 512 ||
      prebufferSamples == 0 ||
      prebufferSamples > StreamAudioSource::kCapacitySamples ||
      sampleFormat != 1 || channels != 1 || modulation > 1 || processing > 1 ||
      drive > 1 || dataTimeoutMs < 20 || dataTimeoutMs > 2000) {
    protocol_.sendAck(message.type, message.sequence, 1, 4);
    return;
  }
  Command command = {};
  command.type = CommandType::kStreamStart;
  command.requestSequence = message.sequence;
  command.streamParameters.sampleRate = sampleRate;
  command.streamParameters.prebufferSamples = prebufferSamples;
  command.streamParameters.dataTimeoutMs = dataTimeoutMs;
  command.streamParameters.modulationMode =
      modulation == 0 ? AudioModulationMode::kDsbAm
                      : AudioModulationMode::kSram;
  command.streamParameters.processingMode =
      processing == 0 ? AudioProcessingMode::kRaw
                      : AudioProcessingMode::kLoudnessEnhanced;
  command.streamParameters.driveMode =
      drive == 0 ? AudioDriveMode::kStandard : AudioDriveMode::kBoost;
  if (!enqueue(command)) {
    protocol_.sendAck(message.type, message.sequence, 1, 1);
  }
}

void UltrasonicApp::handleProtocolAudio(const ProtocolMessage& message) {
  if (!modulationEngine_.streaming() || message.payloadLength == 0) return;
  if (receivedFirstAudioPacket_ &&
      message.sampleIndex != expectedAudioSampleIndex_) {
    ++audioSequenceGapCount_;
  }
  receivedFirstAudioPacket_ = true;
  expectedAudioSampleIndex_ = message.sampleIndex + message.payloadLength;
  modulationEngine_.pushStreamSamples(message.payload, message.payloadLength);
  lastAudioDataMs_ = millis();
  protocolTimeoutQueued_ = false;
  if (playbackTaskHandle_ != nullptr) {
    xTaskNotify(playbackTaskHandle_, kStreamDataEvent, eSetBits);
  }
}

void UltrasonicApp::handleProtocolGimbal(const ProtocolMessage& message) {
  if (message.payloadLength != 4) {
    if ((message.flags & kAckRequired) != 0) {
      protocol_.sendAck(message.type, message.sequence, 1, 2);
    }
    return;
  }
  const int16_t panCentidegrees = static_cast<int16_t>(
      static_cast<uint16_t>(message.payload[0]) |
      (static_cast<uint16_t>(message.payload[1]) << 8));
  const int16_t tiltCentidegrees = static_cast<int16_t>(
      static_cast<uint16_t>(message.payload[2]) |
      (static_cast<uint16_t>(message.payload[3]) << 8));
  if (panCentidegrees < -9000 || panCentidegrees > 9000 ||
      tiltCentidegrees < -9000 || tiltCentidegrees > 9000) {
    if ((message.flags & kAckRequired) != 0) {
      protocol_.sendAck(message.type, message.sequence, 1, 5);
    }
    return;
  }
  const int32_t panDegrees = panCentidegrees >= 0
                                 ? (panCentidegrees + 50) / 100
                                 : (panCentidegrees - 50) / 100;
  const int32_t tiltDegrees = tiltCentidegrees >= 0
                                  ? (tiltCentidegrees + 50) / 100
                                  : (tiltCentidegrees - 50) / 100;
  const esp_err_t error = gimbal_.setAngles(panDegrees, tiltDegrees);
  if ((message.flags & kAckRequired) != 0) {
    protocol_.sendAck(message.type, message.sequence,
                      error == ESP_OK ? 0 : 1,
                      error == ESP_OK ? 0 : 6);
  }
}

void UltrasonicApp::reportProtocolStatus() {
  if (!protocol_.sessionActive()) return;
  const uint32_t now = millis();
  if (now - lastProtocolStatusMs_ < kProtocolStatusIntervalMs) return;
  lastProtocolStatusMs_ = now;
  const StreamBufferStats stream = modulationEngine_.streamStats();
  const uint32_t age = lastAudioDataMs_ == 0 ? UINT16_MAX
                                             : now - lastAudioDataMs_;
  ProtocolStatus status = {};
  status.state = protocolStreamState_;
  status.muted = protocolMuted_ || !sampleTimerRunning_;
  status.bufferFillSamples = static_cast<uint16_t>(stream.bufferedSamples);
  status.bufferCapacitySamples = static_cast<uint16_t>(stream.capacitySamples);
  status.underrunCount = stream.underrunCount;
  status.overrunCount = stream.overrunCount;
  status.crcErrorCount = protocol_.receiveErrorCount();
  status.sequenceGapCount = audioSequenceGapCount_;
  status.timerSkippedSamples =
      skippedFrameCount_ > UINT32_MAX ? UINT32_MAX
                                      : static_cast<uint32_t>(skippedFrameCount_);
  status.lastAudioAgeMs =
      static_cast<uint16_t>(age > UINT16_MAX ? UINT16_MAX : age);
  protocol_.sendStatus(status);
}

void UltrasonicApp::checkProtocolAudioTimeout() {
  if (!protocol_.sessionActive() || !modulationEngine_.streaming() ||
      protocolMuted_ || protocolTimeoutQueued_ || lastAudioDataMs_ == 0) {
    return;
  }
  if (millis() - lastAudioDataMs_ <= protocolAudioTimeoutMs_) return;
  Command command = {};
  command.type = CommandType::kProtocolMute;
  command.value = 1;
  command.requestSequence = UINT32_MAX;
  if (enqueue(command)) protocolTimeoutQueued_ = true;
}

void UltrasonicApp::beginPoseInput() {
  if (numericInputActive_) {
    Serial.println("NUMBER ERROR: terminate the frequency with Enter");
    numericInputValue_ = 0;
    numericInputActive_ = false;
    numericInputOverflow_ = false;
  }

  poseInputLength_ = 0;
  poseInput_[0] = '\0';
  poseInputActive_ = true;
  poseInputOverflow_ = false;
}

void UltrasonicApp::handlePoseCharacter(char input) {
  if (input == ')') {
    handlePoseInput();
    return;
  }

  if (input == '\r' || input == '\n') {
    Serial.println("GIMBAL ERROR: close the pair with ')'");
    poseInputActive_ = false;
    poseInputLength_ = 0;
    poseInputOverflow_ = false;
    return;
  }

  if (poseInputLength_ + 1 >= kPoseInputCapacity) {
    poseInputOverflow_ = true;
    return;
  }

  poseInput_[poseInputLength_++] = input;
  poseInput_[poseInputLength_] = '\0';
}

void UltrasonicApp::handlePoseInput() {
  poseInputActive_ = false;

  if (poseInputOverflow_) {
    Serial.println("GIMBAL ERROR: command is too long");
    poseInputLength_ = 0;
    poseInputOverflow_ = false;
    return;
  }

  long panDegrees = 0;
  long tiltDegrees = 0;
  char trailing = '\0';
  const int parsed = sscanf(poseInput_, " %ld , %ld %c",
                            &panDegrees, &tiltDegrees, &trailing);
  poseInputLength_ = 0;

  if (parsed != 2) {
    Serial.println("GIMBAL ERROR: use (left-right,up-down), e.g. (-10,30)");
    return;
  }
  if (panDegrees < GimbalController::kMinimumAngle ||
      panDegrees > GimbalController::kMaximumAngle ||
      tiltDegrees < GimbalController::kMinimumAngle ||
      tiltDegrees > GimbalController::kMaximumAngle) {
    Serial.println("GIMBAL ERROR: both angles must be -90..90 degrees");
    return;
  }

  const esp_err_t error = gimbal_.setAngles(
      static_cast<int32_t>(panDegrees),
      static_cast<int32_t>(tiltDegrees));
  if (error != ESP_OK) {
    Serial.printf("GIMBAL ERROR: %s\r\n", esp_err_to_name(error));
    return;
  }

  Serial.printf("GIMBAL: pan=%ld deg, tilt=%ld deg\r\n",
                panDegrees, tiltDegrees);
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
  Serial.println("(pan,tilt) : set GPIO6/GPIO5 signed angles, e.g. (-10,30)");
  Serial.println("H : print this help");
  Serial.println("Power-up default: gimbal (0,0), ultrasonic output muted.");
  Serial.println("Binary protocol v1 accepts live 8 kHz PCM at 460800 baud.");
  Serial.println("GPIO4 is copied to 12 TC4428 branches by external buffers.");
  Serial.println("Software stop is not 12 V isolation; disconnect power before rewiring.");
  Serial.println();
}

bool UltrasonicApp::enqueue(CommandType type, uint32_t value) {
  Command command = {};
  command.type = type;
  command.value = value;
  return enqueue(command);
}

bool UltrasonicApp::enqueue(const Command& command) {
  if (xQueueSend(commandQueue_, &command, pdMS_TO_TICKS(20)) != pdTRUE) {
    if (protocol_.sessionActive()) {
      protocol_.sendError("command queue is full", 1);
    } else {
      Serial.println("COMMAND ERROR: queue is full");
    }
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
    case CommandType::kStreamStart:
      startStream(command.streamParameters, command.requestSequence);
      return true;
    case CommandType::kStreamStop:
      stopStream(command.requestSequence);
      return true;
    case CommandType::kProtocolMute:
      setProtocolMute(command.value != 0, command.requestSequence);
      return true;
    case CommandType::kProtocolHello:
      startProtocolSession(command.requestSequence);
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

void UltrasonicApp::startStream(const AudioStreamParameters& parameters,
                                uint32_t requestSequence) {
  stopSampleTimer();
  reportTimingStats();
  resetTimingStats();
  driver_.stop();
  if (!modulationEngine_.startStream(parameters)) {
    protocolStreamState_ = ProtocolStreamState::kFault;
    protocolMuted_ = true;
    protocol_.sendAck(ProtocolMessageType::kStreamStart, requestSequence, 1, 7);
    return;
  }
  protocolMuted_ = false;
  protocolTimeoutQueued_ = false;
  protocolStreamState_ = ProtocolStreamState::kPrefill;
  protocolAudioTimeoutMs_ = parameters.dataTimeoutMs;
  lastAudioDataMs_ = 0;
  expectedAudioSampleIndex_ = 0;
  audioSequenceGapCount_ = 0;
  receivedFirstAudioPacket_ = false;
  protocol_.sendAck(ProtocolMessageType::kStreamStart, requestSequence);
}

void UltrasonicApp::startProtocolSession(uint32_t requestSequence) {
  stopOutput(false);
  protocolMuted_ = true;
  protocolTimeoutQueued_ = false;
  protocolStreamState_ = ProtocolStreamState::kIdle;
  lastAudioDataMs_ = 0;
  expectedAudioSampleIndex_ = 0;
  audioSequenceGapCount_ = 0;
  receivedFirstAudioPacket_ = false;
  protocol_.sendHelloAck(
      requestSequence,
      static_cast<uint16_t>(StreamAudioSource::kCapacitySamples));
}

void UltrasonicApp::stopStream(uint32_t requestSequence) {
  stopSampleTimer();
  modulationEngine_.stop();
  driver_.stop();
  protocolMuted_ = true;
  protocolTimeoutQueued_ = false;
  protocolStreamState_ = ProtocolStreamState::kIdle;
  if (requestSequence != UINT32_MAX) {
    protocol_.sendAck(ProtocolMessageType::kStreamStop, requestSequence);
  }
}

void UltrasonicApp::setProtocolMute(bool enabled,
                                    uint32_t requestSequence) {
  protocolMuted_ = enabled;
  if (enabled) {
    stopSampleTimer();
    driver_.stop();
    protocolStreamState_ = modulationEngine_.streaming()
                               ? ProtocolStreamState::kMuted
                               : ProtocolStreamState::kIdle;
    if (requestSequence == UINT32_MAX) {
      modulationEngine_.stop();
      protocolStreamState_ = ProtocolStreamState::kMuted;
    }
  } else if (modulationEngine_.streaming()) {
    protocolStreamState_ = ProtocolStreamState::kPrefill;
    maybeStartStreamPlayback();
  }
  if (requestSequence != UINT32_MAX) {
    protocol_.sendAck(ProtocolMessageType::kSetMute, requestSequence);
  }
}

void UltrasonicApp::maybeStartStreamPlayback() {
  if (!modulationEngine_.streaming() || protocolMuted_ ||
      sampleTimerRunning_ || !modulationEngine_.streamReadyToPlay()) {
    return;
  }
  protocolStreamState_ = ProtocolStreamState::kPlaying;
  renderTimedSample();
}

void UltrasonicApp::handleStreamUnderrun() {
  stopSampleTimer();
  driver_.stop();
  protocolStreamState_ = protocolMuted_ ? ProtocolStreamState::kMuted
                                        : ProtocolStreamState::kPrefill;
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
  if (protocol_.sessionActive()) {
    protocolMuted_ = true;
    protocolStreamState_ = ProtocolStreamState::kIdle;
  }
}

void UltrasonicApp::renderTimedSample() {
  const ModulationFrame frame = modulationEngine_.nextFrame();
  if (frame.status == ModulationFrameStatus::kIdle) return;
  if (frame.status == ModulationFrameStatus::kUnderrun) {
    handleStreamUnderrun();
    return;
  }

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
    if (status == ModulationFrameStatus::kUnderrun) {
      handleStreamUnderrun();
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

  if (protocol_.sessionActive()) return;

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
  if (protocol_.sessionActive()) {
    protocolStreamState_ = ProtocolStreamState::kFault;
    protocolMuted_ = true;
    protocol_.sendError(operation, static_cast<uint16_t>(error));
  } else {
    Serial.printf("RUNTIME ERROR (%s): %s\r\n", operation,
                  esp_err_to_name(error));
  }
  return false;
}

}  // namespace ultrasonic
