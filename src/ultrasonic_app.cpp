#include "ultrasonic_app.h"

#include <math.h>

#include "audio_data.h"

namespace ultrasonic {
namespace {

constexpr uint32_t kCommandQueueLength = 8;
constexpr uint32_t kControlTaskStackBytes = 4096;
constexpr uint32_t kPlaybackTaskStackBytes = 4096;
constexpr UBaseType_t kControlTaskPriority = 2;
constexpr UBaseType_t kPlaybackTaskPriority = 4;

}  // namespace

esp_err_t UltrasonicApp::begin() {
  buildEnvelopeTable();
  buildAudioTables();

  commandQueue_ = xQueueCreate(kCommandQueueLength, sizeof(Command));
  if (commandQueue_ == nullptr) return ESP_ERR_NO_MEM;

  esp_timer_create_args_t timerArgs = {};
  timerArgs.callback = &UltrasonicApp::timerEntry;
  timerArgs.arg = this;
  timerArgs.dispatch_method = ESP_TIMER_TASK;
  timerArgs.name = "ultra_tick";

  esp_err_t error = esp_timer_create(&timerArgs, &sampleTimer_);
  if (error != ESP_OK) {
    vQueueDelete(commandQueue_);
    commandQueue_ = nullptr;
    return error;
  }

  BaseType_t taskResult = xTaskCreate(
      &UltrasonicApp::playbackTaskEntry, "ultra_playback",
      kPlaybackTaskStackBytes, this, kPlaybackTaskPriority,
      &playbackTaskHandle_);
  if (taskResult != pdPASS) {
    esp_timer_delete(sampleTimer_);
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
    esp_timer_delete(sampleTimer_);
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

void UltrasonicApp::timerEntry(void* context) {
  auto* app = static_cast<UltrasonicApp*>(context);
  if (app->playbackTaskHandle_ != nullptr) {
    xTaskNotify(app->playbackTaskHandle_, kTimerEvent, eSetBits);
  }
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

    if ((events & kCommandEvent) != 0) {
      Command command = {};
      while (xQueueReceive(commandQueue_, &command, 0) == pdTRUE) {
        handleCommand(command);
      }

      // 模式切换会自行重新布置定时器；忽略与命令同时到达的旧定时事件。
      continue;
    }

    if ((events & kTimerEvent) != 0) renderTimedSample();
  }
}

void UltrasonicApp::handleSerial() {
  while (Serial.available() > 0) {
    char input = static_cast<char>(Serial.read());
    if (input >= 'a' && input <= 'z') input -= ('a' - 'A');

    if (input >= '1' && input <= '4') {
      enqueue(CommandType::kSingle, static_cast<uint8_t>(input - '1'));
      continue;
    }

    switch (input) {
      case '0':
        enqueue(CommandType::kStop);
        break;
      case 'A':
        enqueue(CommandType::kAllCarrier);
        break;
      case 'T':
        enqueue(CommandType::kEnvelopeTone);
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
      case '\r':
      case '\n':
      case ' ':
        break;
      default:
        Serial.printf("Unknown command: 0x%02X. Send H for help.\r\n",
                      static_cast<unsigned int>(
                          static_cast<unsigned char>(input)));
        break;
    }
  }
}

void UltrasonicApp::printHelp() const {
  Serial.println();
  Serial.println("=== ESP32-S3 4x3 ultrasonic array smoke test ===");
  Serial.println("0 : stop all PWM");
  Serial.println("1..4 : enable only one column (left to right)");
  Serial.println("A : enable all four columns, same phase, 40 kHz");
  Serial.println("T : 1 kHz envelope test on all four columns");
  Serial.println("P : play embedded audio once");
  Serial.println("L : loop embedded audio");
  Serial.println("H : print this help");
  Serial.println("Power-up default is OFF. Commands are case-insensitive.");
  Serial.println();
}

bool UltrasonicApp::enqueue(CommandType type, uint8_t channel) {
  const Command command = {type, channel};
  if (xQueueSend(commandQueue_, &command, pdMS_TO_TICKS(20)) != pdTRUE) {
    Serial.println("COMMAND ERROR: queue is full");
    return false;
  }

  xTaskNotify(playbackTaskHandle_, kCommandEvent, eSetBits);
  return true;
}

void UltrasonicApp::handleCommand(const Command& command) {
  switch (command.type) {
    case CommandType::kStop:
      stopOutput();
      break;
    case CommandType::kSingle:
      startSingle(command.channel);
      break;
    case CommandType::kAllCarrier:
      startAllCarrier();
      break;
    case CommandType::kEnvelopeTone:
      startEnvelopeTone();
      break;
    case CommandType::kAudioOnce:
      startAudio(false);
      break;
    case CommandType::kAudioLoop:
      startAudio(true);
      break;
  }
}

void UltrasonicApp::startSingle(uint8_t channel) {
  stopSampleTimer();
  mode_ = RunMode::kOff;
  if (!applyDriverResult(driver_.stop(), "clear channels")) return;
  if (!applyDriverResult(
          driver_.setChannelDuty(channel, UltrasonicDriver::kHalfDuty),
          "enable channel")) {
    return;
  }

  mode_ = RunMode::kSingle;
  Serial.printf("CH%d ON: GPIO%d, 40 kHz, 50%%\r\n",
                static_cast<int>(channel + 1), driver_.gpioForChannel(channel));
}

void UltrasonicApp::startAllCarrier() {
  stopSampleTimer();
  mode_ = RunMode::kOff;
  if (!applyDriverResult(
          driver_.setAllDuty(UltrasonicDriver::kHalfDuty),
          "enable all channels")) {
    return;
  }

  mode_ = RunMode::kAllCarrier;
  Serial.println("ALL ON: four columns, same phase, 40 kHz, 50%");
}

void UltrasonicApp::startEnvelopeTone() {
  stopSampleTimer();
  envelopeIndex_ = 0;
  mode_ = RunMode::kEnvelopeTone;
  nextSampleUs_ = esp_timer_get_time();
  Serial.println(
      "TEST TONE: 40 kHz carrier with 1 kHz sine envelope on four columns");
  Serial.println("This is only a bench test; the audible tone may be weak.");
  renderTimedSample();
}

void UltrasonicApp::startAudio(bool loop) {
  stopSampleTimer();
  if (kAudioSampleCount == 0 || kAudioSampleRate == 0) {
    Serial.println("AUDIO ERROR: audio_data.h contains no valid samples");
    stopOutput(false);
    return;
  }

  audioIndex_ = 0;
  mode_ = loop ? RunMode::kAudioLoop : RunMode::kAudioOnce;
  nextSampleUs_ = esp_timer_get_time();
  Serial.printf("AUDIO %s: %lu samples at %lu Hz (%.2f s)\r\n",
                loop ? "LOOP" : "PLAY ONCE",
                static_cast<unsigned long>(kAudioSampleCount),
                static_cast<unsigned long>(kAudioSampleRate),
                static_cast<double>(kAudioSampleCount) /
                    static_cast<double>(kAudioSampleRate));
  renderTimedSample();
}

void UltrasonicApp::stopOutput(bool printStatus) {
  stopSampleTimer();
  mode_ = RunMode::kOff;
  applyDriverResult(driver_.stop(), "stop output");
  if (printStatus) {
    Serial.println(
        "OUTPUT OFF (PWM stopped; switch off driver 12 V before rewiring)");
  }
}

void UltrasonicApp::renderTimedSample() {
  uint32_t intervalUs = 0;

  if (mode_ == RunMode::kEnvelopeTone) {
    if (!applyDriverResult(
            driver_.setAllDuty(envelopeDuty_[envelopeIndex_]),
            "write envelope sample")) {
      return;
    }
    envelopeIndex_ = (envelopeIndex_ + 1) % kEnvelopeSampleCount;
    intervalUs = 1000000UL / kEnvelopeSampleRate;
  } else if (mode_ == RunMode::kAudioOnce || mode_ == RunMode::kAudioLoop) {
    if (!applyDriverResult(
            driver_.setAllDuty(audioDutyLut_[readAudioSample(audioIndex_)]),
            "write audio sample")) {
      return;
    }

    ++audioIndex_;
    if (audioIndex_ >= kAudioSampleCount) {
      if (mode_ == RunMode::kAudioLoop) {
        audioIndex_ = 0;
      } else {
        mode_ = RunMode::kOff;
        applyDriverResult(driver_.stop(), "finish audio");
        Serial.println("AUDIO DONE; output stopped");
        return;
      }
    }
    intervalUs = 1000000UL / kAudioSampleRate;
  } else {
    return;
  }

  scheduleNextSample(intervalUs);
}

void UltrasonicApp::scheduleNextSample(uint32_t intervalUs) {
  if (intervalUs == 0) {
    applyDriverResult(ESP_ERR_INVALID_ARG, "schedule sample");
    return;
  }

  nextSampleUs_ += intervalUs;
  const int64_t nowUs = esp_timer_get_time();

  // 丢弃严重过时的节拍，避免任务恢复后连续补播旧样本。
  if (nowUs - nextSampleUs_ >= static_cast<int64_t>(intervalUs)) {
    nextSampleUs_ = nowUs + intervalUs;
  }

  const uint64_t delayUs = nextSampleUs_ > nowUs
                               ? static_cast<uint64_t>(nextSampleUs_ - nowUs)
                               : 1;
  const esp_err_t error = esp_timer_start_once(sampleTimer_, delayUs);
  if (error != ESP_OK) applyDriverResult(error, "arm sample timer");
}

void UltrasonicApp::stopSampleTimer() {
  if (sampleTimer_ == nullptr) return;
  const esp_err_t error = esp_timer_stop(sampleTimer_);
  if (error != ESP_OK && error != ESP_ERR_INVALID_STATE) {
    Serial.printf("TIMER ERROR (stop): %s\r\n", esp_err_to_name(error));
  }
}

uint8_t UltrasonicApp::readAudioSample(uint32_t index) const {
  if (!kAudioIsDemo) return pgm_read_byte(&kAudioSamples[index]);

  // audio_data.h 尚未由真实 WAV 覆盖时，生成 2 秒八音测试旋律。
  static constexpr uint16_t kDemoNotesHz[] = {
      500, 600, 700, 800, 700, 600, 500, 0,
  };
  static constexpr uint32_t kSamplesPerNote = kAudioSampleRate / 4;
  static_assert(kSamplesPerNote > 0, "demo sample rate is too low");

  const uint32_t noteIndex =
      (index / kSamplesPerNote) %
      (sizeof(kDemoNotesHz) / sizeof(kDemoNotesHz[0]));
  const uint16_t frequency = kDemoNotesHz[noteIndex];
  if (frequency == 0) return 128;

  const uint32_t sampleInNote = index % kSamplesPerNote;
  const uint8_t phase = static_cast<uint8_t>(
      (sampleInNote * static_cast<uint32_t>(frequency) * 256UL) /
      kAudioSampleRate);
  return demoSineLut_[phase];
}

bool UltrasonicApp::applyDriverResult(esp_err_t error,
                                      const char* operation) {
  if (error == ESP_OK) return true;

  stopSampleTimer();
  mode_ = RunMode::kOff;
  driver_.stop();
  Serial.printf("HARDWARE ERROR (%s): %s\r\n", operation,
                esp_err_to_name(error));
  return false;
}

void UltrasonicApp::buildEnvelopeTable() {
  // 0.15..0.95 的正弦包络；反正弦映射补偿方波基波幅度。
  for (uint8_t sample = 0; sample < kEnvelopeSampleCount; ++sample) {
    const float phase = 2.0f * PI * static_cast<float>(sample) /
                        static_cast<float>(kEnvelopeSampleCount);
    const float envelope = 0.55f + 0.40f * sinf(phase);
    const float dutyRatio = asinf(envelope) / PI;
    uint32_t duty = static_cast<uint32_t>(lroundf(
        dutyRatio * static_cast<float>(UltrasonicDriver::kPeriodCounts)));
    if (duty < 1) duty = 1;
    if (duty > UltrasonicDriver::kHalfDuty) {
      duty = UltrasonicDriver::kHalfDuty;
    }
    envelopeDuty_[sample] = duty;
  }
}

void UltrasonicApp::buildAudioTables() {
  for (uint16_t sample = 0; sample < 256; ++sample) {
    const float normalized =
        (static_cast<float>(sample) - 128.0f) / 128.0f;
    float envelope = kAudioCarrierBase + kAudioModulation * normalized;
    if (envelope < 0.05f) envelope = 0.05f;
    if (envelope > 0.90f) envelope = 0.90f;

    const float dutyRatio = asinf(envelope) / PI;
    uint32_t duty = static_cast<uint32_t>(lroundf(
        dutyRatio * static_cast<float>(UltrasonicDriver::kPeriodCounts)));
    if (duty < 1) duty = 1;
    if (duty > UltrasonicDriver::kHalfDuty) {
      duty = UltrasonicDriver::kHalfDuty;
    }
    audioDutyLut_[sample] = duty;

    const float phase = 2.0f * PI * static_cast<float>(sample) / 256.0f;
    demoSineLut_[sample] = static_cast<uint8_t>(
        lroundf(128.0f + 90.0f * sinf(phase)));
  }
}

}  // namespace ultrasonic
