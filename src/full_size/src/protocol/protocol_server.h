#pragma once

#include <Arduino.h>
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#include "protocol_types.h"

namespace ultrasonic {

class ProtocolServer final {
 public:
  bool begin();
  bool feed(uint8_t value, ProtocolMessage* message);
  void resetReceiver();
  void startSession(uint32_t sessionId);
  bool sessionActive() const { return sessionActive_; }
  uint32_t sessionId() const { return sessionId_; }
  uint32_t receiveErrorCount() const { return receiveErrorCount_; }

  bool sendHelloAck(uint32_t requestSequence, uint16_t bufferSamples);
  bool sendAck(ProtocolMessageType acknowledgedType, uint32_t requestSequence,
               uint8_t result = 0, uint16_t detail = 0);
  bool resendCachedAckIfDuplicate(ProtocolMessageType acknowledgedType,
                                  uint32_t requestSequence);
  bool sendStatus(const ProtocolStatus& status);
  bool sendPong(uint32_t nonce);
  bool sendError(const char* text, uint16_t detail = 0);

 private:
  static constexpr size_t kHeaderLength = 20;
  static constexpr size_t kCrcLength = 2;
  static constexpr size_t kRawCapacity =
      kHeaderLength + kProtocolMaximumPayload + kCrcLength;
  static constexpr size_t kEncodedCapacity = 544;

  bool decodeCurrent(ProtocolMessage* message);
  bool sendFrame(ProtocolMessageType type, uint16_t flags,
                 const uint8_t* payload, uint16_t payloadLength,
                 uint32_t sampleIndex = 0);
  static uint16_t readU16(const uint8_t* data);
  static uint32_t readU32(const uint8_t* data);
  static void writeU16(uint8_t* data, uint16_t value);
  static void writeU32(uint8_t* data, uint32_t value);

  uint8_t encoded_[kEncodedCapacity] = {};
  size_t encodedLength_ = 0;
  SemaphoreHandle_t transmitMutex_ = nullptr;
  uint32_t sessionId_ = 0;
  uint32_t transmitSequence_ = 0;
  uint32_t receiveErrorCount_ = 0;
  portMUX_TYPE acknowledgementMux_ = portMUX_INITIALIZER_UNLOCKED;
  ProtocolMessageType lastAcknowledgedType_ = ProtocolMessageType::kError;
  uint32_t lastAcknowledgedSequence_ = UINT32_MAX;
  uint8_t lastAcknowledgedResult_ = 0;
  uint16_t lastAcknowledgedDetail_ = 0;
  bool sessionActive_ = false;
};

}  // namespace ultrasonic
