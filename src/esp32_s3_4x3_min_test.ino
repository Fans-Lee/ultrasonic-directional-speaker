#include <Arduino.h>
#include <math.h>
#include "driver/ledc.h"
#include "esp_err.h"
#include "audio_data.h"

// 4 列 × 每列 3 只换能器。GPIO 顺序从阵面左列到右列。
// 对应自制板 H4 排针上的 GPIO4、5、6、7。
static constexpr uint8_t kChannelCount = 4;
static constexpr int kGpio[kChannelCount] = {4, 5, 6, 7};

static constexpr uint32_t kCarrierHz = 40000;
static constexpr ledc_mode_t kSpeedMode = LEDC_LOW_SPEED_MODE;
static constexpr ledc_timer_t kTimer = LEDC_TIMER_0;
static constexpr ledc_timer_bit_t kResolution = LEDC_TIMER_10_BIT;
static constexpr uint32_t kPeriodCounts = 1U << 10;  // 1024
static constexpr uint32_t kHalfDuty = kPeriodCounts / 2;  // 50%

// 仅用于今天的链路测试：1 kHz 正弦包络，8 kHz 更新率。
// 这不是完整的语音调制器，也不能保证 12 只阵元产生明显可听声。
static constexpr uint32_t kEnvelopeSampleRate = 8000;
static constexpr uint32_t kToneHz = 1000;
static constexpr uint8_t kEnvelopeSamples =
    kEnvelopeSampleRate / kToneHz;  // 8 samples per 1 kHz cycle
static uint32_t gEnvelopeDuty[kEnvelopeSamples];

enum class RunMode : uint8_t {
  kOff,
  kSingle,
  kAllCarrier,
  kEnvelopeTone,
  kAudioOnce,
  kAudioLoop,
};

static RunMode gMode = RunMode::kOff;
static int gSingleChannel = -1;
static uint8_t gEnvelopeIndex = 0;
static uint32_t gNextEnvelopeUs = 0;
static uint32_t gAudioIndex = 0;
static uint32_t gNextAudioUs = 0;
static uint32_t gAudioDutyLut[256];
static uint8_t gDemoSineLut[256];

// 音频包络参数。基线不能为 0，避免过调制时包络穿过零点。
// 初次测试请保持下列参数。kAudioModulation 不应大于
// kAudioCarrierBase，否则会出现过调制和明显失真。
static constexpr float kAudioCarrierBase = 0.45f;
static constexpr float kAudioModulation = 0.40f;

static void stopOutput();

static void setChannelDuty(uint8_t index, uint32_t duty) {
  if (index >= kChannelCount) return;
  if (duty > kHalfDuty) duty = kHalfDuty;

  // 脉冲以计数周期中点为中心；改变占空比时尽量保持载波相位不动。
  const uint32_t hpoint = (duty == 0) ? 0 : (kPeriodCounts - duty) / 2;
  ESP_ERROR_CHECK(ledc_set_duty_with_hpoint(
      kSpeedMode, static_cast<ledc_channel_t>(index), duty, hpoint));
  ESP_ERROR_CHECK(
      ledc_update_duty(kSpeedMode, static_cast<ledc_channel_t>(index)));
}

static void setAllOff() {
  for (uint8_t i = 0; i < kChannelCount; ++i) {
    setChannelDuty(i, 0);
  }
}

static void setAllDuty(uint32_t duty) {
  for (uint8_t i = 0; i < kChannelCount; ++i) {
    setChannelDuty(i, duty);
  }
}

static void startSingle(uint8_t index) {
  setAllOff();
  setChannelDuty(index, kHalfDuty);
  gSingleChannel = index;
  gMode = RunMode::kSingle;
  Serial.printf("CH%d ON: GPIO%d, 40 kHz, 50%%\r\n",
                static_cast<int>(index + 1), kGpio[index]);
}

static void startAllCarrier() {
  setAllDuty(kHalfDuty);
  gMode = RunMode::kAllCarrier;
  Serial.println("ALL ON: four columns, same phase, 40 kHz, 50%");
}

static void startEnvelopeTone() {
  gEnvelopeIndex = 0;
  gNextEnvelopeUs = micros();
  gMode = RunMode::kEnvelopeTone;
  Serial.println("TEST TONE: 40 kHz carrier with 1 kHz sine envelope on four columns");
  Serial.println("This is only a bench test; the audible tone may be very weak.");
}

static void startAudio(bool loop) {
  if (kAudioSampleCount == 0) {
    Serial.println("AUDIO ERROR: audio_data.h contains no samples");
    stopOutput();
    return;
  }

  gAudioIndex = 0;
  gNextAudioUs = micros();
  gMode = loop ? RunMode::kAudioLoop : RunMode::kAudioOnce;
  Serial.printf("AUDIO %s: %lu samples at %lu Hz (%.2f s)\r\n",
                loop ? "LOOP" : "PLAY ONCE",
                static_cast<unsigned long>(kAudioSampleCount),
                static_cast<unsigned long>(kAudioSampleRate),
                static_cast<double>(kAudioSampleCount) /
                    static_cast<double>(kAudioSampleRate));
}

static void stopOutput() {
  setAllOff();
  gMode = RunMode::kOff;
  gSingleChannel = -1;
  Serial.println("OUTPUT OFF (PWM stopped; switch off driver 12 V before rewiring)");
}

static void printHelp() {
  Serial.println();
  Serial.println("=== ESP32-S3 4x3 ultrasonic array smoke test ===");
  Serial.println("0 : stop all PWM");
  Serial.println("1..4 : enable only one column (left to right)");
  Serial.println("A : enable all four columns, same phase, 40 kHz");
  Serial.println("T : 1 kHz envelope test on all four columns");
  Serial.println("P : play embedded audio once");
  Serial.println("L : loop embedded audio");
  Serial.println("H : print this help");
  Serial.println("Power-up default is OFF. Use uppercase or lowercase commands.");
  Serial.println();
}

static void buildEnvelopeTable() {
  // 0.15..0.95 的正包络，避免过调制。
  // 方波基波幅度约与 sin(pi*duty_ratio) 成正比，因此做反正弦映射。
  for (uint8_t i = 0; i < kEnvelopeSamples; ++i) {
    const float phase = 2.0f * PI * static_cast<float>(i) /
                        static_cast<float>(kEnvelopeSamples);
    const float envelope = 0.55f + 0.40f * sinf(phase);
    const float dutyRatio = asinf(envelope) / PI;
    uint32_t duty = static_cast<uint32_t>(
        lroundf(dutyRatio * static_cast<float>(kPeriodCounts)));
    if (duty < 1) duty = 1;
    if (duty > kHalfDuty) duty = kHalfDuty;
    gEnvelopeDuty[i] = duty;
  }
}

static void buildAudioTables() {
  for (uint16_t sample = 0; sample < 256; ++sample) {
    const float normalized =
        (static_cast<float>(sample) - 128.0f) / 128.0f;
    float envelope = kAudioCarrierBase + kAudioModulation * normalized;
    if (envelope < 0.05f) envelope = 0.05f;
    if (envelope > 0.90f) envelope = 0.90f;

    const float dutyRatio = asinf(envelope) / PI;
    uint32_t duty = static_cast<uint32_t>(
        lroundf(dutyRatio * static_cast<float>(kPeriodCounts)));
    if (duty < 1) duty = 1;
    if (duty > kHalfDuty) duty = kHalfDuty;
    gAudioDutyLut[sample] = duty;

    const float phase = 2.0f * PI * static_cast<float>(sample) / 256.0f;
    gDemoSineLut[sample] = static_cast<uint8_t>(
        lroundf(128.0f + 90.0f * sinf(phase)));
  }
}

static void setupLedc() {
  // 在 LEDC 接管 GPIO 前，先把输入保持为低电平。
  for (uint8_t i = 0; i < kChannelCount; ++i) {
    pinMode(kGpio[i], OUTPUT);
    digitalWrite(kGpio[i], LOW);
  }

  ledc_timer_config_t timerConfig = {};
  timerConfig.speed_mode = kSpeedMode;
  timerConfig.duty_resolution = kResolution;
  timerConfig.timer_num = kTimer;
  timerConfig.freq_hz = kCarrierHz;
  timerConfig.clk_cfg = LEDC_AUTO_CLK;
  ESP_ERROR_CHECK(ledc_timer_config(&timerConfig));

  for (uint8_t i = 0; i < kChannelCount; ++i) {
    ledc_channel_config_t channelConfig = {};
    channelConfig.gpio_num = kGpio[i];
    channelConfig.speed_mode = kSpeedMode;
    channelConfig.channel = static_cast<ledc_channel_t>(i);
    channelConfig.intr_type = LEDC_INTR_DISABLE;
    channelConfig.timer_sel = kTimer;
    channelConfig.duty = 0;
    channelConfig.hpoint = 0;
    channelConfig.flags.output_invert = 0;
    ESP_ERROR_CHECK(ledc_channel_config(&channelConfig));
  }
}

static void handleSerial() {
  while (Serial.available() > 0) {
    char command = static_cast<char>(Serial.read());
    if (command >= 'a' && command <= 'z') command -= ('a' - 'A');

    if (command >= '1' && command <= '4') {
      startSingle(static_cast<uint8_t>(command - '1'));
    } else {
      switch (command) {
        case '0':
          stopOutput();
          break;
        case 'A':
          startAllCarrier();
          break;
        case 'T':
          startEnvelopeTone();
          break;
        case 'P':
          startAudio(false);
          break;
        case 'L':
          startAudio(true);
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
          Serial.printf(
              "Unknown command: 0x%02X. Send H for help.\r\n",
              static_cast<unsigned int>(static_cast<unsigned char>(command)));
          break;
      }
    }
  }
}

static void updateEnvelopeTone() {
  if (gMode != RunMode::kEnvelopeTone) return;

  const uint32_t now = micros();
  if (static_cast<int32_t>(now - gNextEnvelopeUs) < 0) return;

  constexpr uint32_t kIntervalUs = 1000000UL / kEnvelopeSampleRate;
  // 如果串口输出等原因让程序落后，不追赶很多旧样本，避免长时间阻塞。
  gNextEnvelopeUs = now + kIntervalUs;
  setAllDuty(gEnvelopeDuty[gEnvelopeIndex]);
  gEnvelopeIndex = (gEnvelopeIndex + 1) % kEnvelopeSamples;
}

static uint8_t readAudioSample(uint32_t index) {
  if (!kAudioIsDemo) {
    return pgm_read_byte(&kAudioSamples[index]);
  }

  // audio_data.h 尚未被真实 WAV 覆盖时，播放 2 秒八音测试旋律。
  static constexpr uint16_t kDemoNotesHz[] = {
      500, 600, 700, 800, 700, 600, 500, 0,
  };
  static constexpr uint32_t kSamplesPerNote = kAudioSampleRate / 4;
  const uint32_t noteIndex = index / kSamplesPerNote;
  const uint16_t frequency = kDemoNotesHz[noteIndex];
  if (frequency == 0) return 128;

  const uint32_t sampleInNote = index % kSamplesPerNote;
  const uint8_t phase = static_cast<uint8_t>(
      (sampleInNote * static_cast<uint32_t>(frequency) * 256UL) /
      kAudioSampleRate);
  return gDemoSineLut[phase];
}

static void updateAudio() {
  if (gMode != RunMode::kAudioOnce && gMode != RunMode::kAudioLoop) return;

  const uint32_t now = micros();
  if (static_cast<int32_t>(now - gNextAudioUs) < 0) return;

  const uint32_t intervalUs = 1000000UL / kAudioSampleRate;
  gNextAudioUs += intervalUs;
  // 若主循环曾阻塞，丢弃过时样本，避免播放速度永久变慢。
  if (static_cast<int32_t>(now - gNextAudioUs) >=
      static_cast<int32_t>(intervalUs)) {
    gNextAudioUs = now + intervalUs;
  }

  setAllDuty(gAudioDutyLut[readAudioSample(gAudioIndex)]);
  ++gAudioIndex;

  if (gAudioIndex >= kAudioSampleCount) {
    if (gMode == RunMode::kAudioLoop) {
      gAudioIndex = 0;
    } else {
      setAllOff();
      gMode = RunMode::kOff;
      Serial.println("AUDIO DONE; output stopped");
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);

  buildEnvelopeTable();
  buildAudioTables();
  setupLedc();
  setAllOff();
  printHelp();
}

void loop() {
  handleSerial();
  updateEnvelopeTone();
  updateAudio();

  if (gMode != RunMode::kEnvelopeTone && gMode != RunMode::kAudioOnce &&
      gMode != RunMode::kAudioLoop) {
    delay(1);
  }
}
