#pragma once

#include <stdint.h>

namespace ultrasonic {

constexpr uint8_t kProtocolVersion = 1;
constexpr uint32_t kProtocolMaximumPayload = 512;

enum class ProtocolMessageType : uint8_t {
  kHello = 0x01,
  kStreamStart = 0x02,
  kAudioData = 0x03,
  kStreamStop = 0x04,
  kSetMute = 0x05,
  kGimbalSetpoint = 0x06,
  kPing = 0x07,
  kSetVolume = 0x08,
  kHelloAck = 0x81,
  kCommandAck = 0x82,
  kStatus = 0x83,
  kLog = 0x84,
  kError = 0x85,
  kPong = 0x87,
};

enum ProtocolFrameFlags : uint16_t {
  kAckRequired = 1U << 0,
  kIsAck = 1U << 1,
  kErrorFlag = 1U << 2,
  kEndOfStream = 1U << 3,
};

enum class ProtocolStreamState : uint8_t {
  kIdle = 0,
  kPrefill = 1,
  kPlaying = 2,
  kDraining = 3,
  kMuted = 4,
  kFault = 5,
};

struct ProtocolMessage {
  ProtocolMessageType type = ProtocolMessageType::kError;
  uint16_t flags = 0;
  uint16_t payloadLength = 0;
  uint32_t sessionId = 0;
  uint32_t sequence = 0;
  uint32_t sampleIndex = 0;
  uint8_t payload[kProtocolMaximumPayload] = {};
};

struct ProtocolStatus {
  ProtocolStreamState state = ProtocolStreamState::kIdle;
  bool muted = true;
  uint16_t lastError = 0;
  uint16_t bufferFillSamples = 0;
  uint16_t bufferCapacitySamples = 0;
  uint32_t underrunCount = 0;
  uint32_t overrunCount = 0;
  uint32_t crcErrorCount = 0;
  uint32_t sequenceGapCount = 0;
  uint32_t timerSkippedSamples = 0;
  uint16_t lastAudioAgeMs = 0;
  uint16_t targetVolumePermille = 1000;
};

}  // namespace ultrasonic
