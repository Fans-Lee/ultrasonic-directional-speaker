#include "protocol_server.h"

#include <string.h>

#include "crc16.h"
#include "frame_codec.h"

namespace ultrasonic {

bool ProtocolServer::begin() {
  if (transmitMutex_ == nullptr) transmitMutex_ = xSemaphoreCreateMutex();
  resetReceiver();
  return transmitMutex_ != nullptr;
}

bool ProtocolServer::feed(uint8_t value, ProtocolMessage* message) {
  if (value != 0) {
    if (encodedLength_ >= kEncodedCapacity) {
      ++receiveErrorCount_;
      encodedLength_ = 0;
      return false;
    }
    encoded_[encodedLength_++] = value;
    return false;
  }
  if (encodedLength_ == 0) return false;
  const bool valid = decodeCurrent(message);
  encodedLength_ = 0;
  if (!valid) ++receiveErrorCount_;
  return valid;
}

void ProtocolServer::resetReceiver() { encodedLength_ = 0; }

void ProtocolServer::startSession(uint32_t sessionId) {
  sessionId_ = sessionId;
  transmitSequence_ = 0;
  sessionActive_ = sessionId != 0;
  portENTER_CRITICAL(&acknowledgementMux_);
  lastAcknowledgedSequence_ = UINT32_MAX;
  portEXIT_CRITICAL(&acknowledgementMux_);
}

bool ProtocolServer::decodeCurrent(ProtocolMessage* message) {
  if (message == nullptr) return false;
  uint8_t raw[kRawCapacity] = {};
  size_t rawLength = 0;
  if (!cobsDecode(encoded_, encodedLength_, raw, sizeof(raw), &rawLength) ||
      rawLength < kHeaderLength + kCrcLength) {
    return false;
  }
  const uint16_t suppliedCrc = readU16(&raw[rawLength - kCrcLength]);
  if (crc16CcittFalse(raw, rawLength - kCrcLength) != suppliedCrc) {
    return false;
  }
  if (raw[0] != 'U' || raw[1] != 'A' || raw[2] != kProtocolVersion) {
    return false;
  }
  const uint16_t payloadLength = readU16(&raw[6]);
  if (payloadLength > kProtocolMaximumPayload ||
      rawLength != kHeaderLength + payloadLength + kCrcLength) {
    return false;
  }
  message->type = static_cast<ProtocolMessageType>(raw[3]);
  message->flags = readU16(&raw[4]);
  message->payloadLength = payloadLength;
  message->sessionId = readU32(&raw[8]);
  message->sequence = readU32(&raw[12]);
  message->sampleIndex = readU32(&raw[16]);
  if (payloadLength > 0) {
    memcpy(message->payload, &raw[kHeaderLength], payloadLength);
  }
  return true;
}

bool ProtocolServer::sendHelloAck(uint32_t requestSequence,
                                  uint16_t bufferSamples) {
  (void)requestSequence;
  uint8_t payload[8] = {};
  writeU16(&payload[0], kProtocolMaximumPayload);
  writeU16(&payload[2], bufferSamples);
  writeU32(&payload[4], 0x00000003U);
  return sendFrame(ProtocolMessageType::kHelloAck, kIsAck, payload,
                   sizeof(payload));
}

bool ProtocolServer::sendAck(ProtocolMessageType acknowledgedType,
                             uint32_t requestSequence, uint8_t result,
                             uint16_t detail) {
  portENTER_CRITICAL(&acknowledgementMux_);
  lastAcknowledgedType_ = acknowledgedType;
  lastAcknowledgedSequence_ = requestSequence;
  lastAcknowledgedResult_ = result;
  lastAcknowledgedDetail_ = detail;
  portEXIT_CRITICAL(&acknowledgementMux_);
  uint8_t payload[8] = {};
  payload[0] = static_cast<uint8_t>(acknowledgedType);
  payload[1] = result;
  writeU16(&payload[2], detail);
  writeU32(&payload[4], requestSequence);
  const uint16_t flags = static_cast<uint16_t>(
      kIsAck | (result == 0 ? 0 : kErrorFlag));
  return sendFrame(ProtocolMessageType::kCommandAck, flags, payload,
                   sizeof(payload));
}

bool ProtocolServer::resendCachedAckIfDuplicate(
    ProtocolMessageType acknowledgedType, uint32_t requestSequence) {
  portENTER_CRITICAL(&acknowledgementMux_);
  const bool duplicate = requestSequence == lastAcknowledgedSequence_ &&
                         acknowledgedType == lastAcknowledgedType_;
  const uint8_t result = lastAcknowledgedResult_;
  const uint16_t detail = lastAcknowledgedDetail_;
  portEXIT_CRITICAL(&acknowledgementMux_);
  if (!duplicate) {
    return false;
  }
  sendAck(acknowledgedType, requestSequence, result, detail);
  return true;
}

bool ProtocolServer::sendStatus(const ProtocolStatus& status) {
  uint8_t payload[32] = {};
  payload[0] = static_cast<uint8_t>(status.state);
  payload[1] = status.muted ? 1 : 0;
  writeU16(&payload[2], status.lastError);
  writeU16(&payload[4], status.bufferFillSamples);
  writeU16(&payload[6], status.bufferCapacitySamples);
  writeU32(&payload[8], status.underrunCount);
  writeU32(&payload[12], status.overrunCount);
  writeU32(&payload[16], status.crcErrorCount);
  writeU32(&payload[20], status.sequenceGapCount);
  writeU32(&payload[24], status.timerSkippedSamples);
  writeU16(&payload[28], status.lastAudioAgeMs);
  writeU16(&payload[30], 0);
  return sendFrame(ProtocolMessageType::kStatus, 0, payload, sizeof(payload));
}

bool ProtocolServer::sendPong(uint32_t nonce) {
  uint8_t payload[4] = {};
  writeU32(payload, nonce);
  return sendFrame(ProtocolMessageType::kPong, 0, payload, sizeof(payload));
}

bool ProtocolServer::sendError(const char* text, uint16_t detail) {
  (void)detail;
  if (text == nullptr) text = "unknown error";
  const size_t length = strnlen(text, kProtocolMaximumPayload);
  return sendFrame(ProtocolMessageType::kError, kErrorFlag,
                   reinterpret_cast<const uint8_t*>(text),
                   static_cast<uint16_t>(length));
}

bool ProtocolServer::sendFrame(ProtocolMessageType type, uint16_t flags,
                               const uint8_t* payload,
                               uint16_t payloadLength,
                               uint32_t sampleIndex) {
  if (transmitMutex_ == nullptr || payloadLength > kProtocolMaximumPayload ||
      (payloadLength > 0 && payload == nullptr)) {
    return false;
  }
  uint8_t raw[kRawCapacity] = {};
  raw[0] = 'U';
  raw[1] = 'A';
  raw[2] = kProtocolVersion;
  raw[3] = static_cast<uint8_t>(type);
  writeU16(&raw[4], flags);
  writeU16(&raw[6], payloadLength);
  writeU32(&raw[8], sessionId_);
  writeU32(&raw[12], transmitSequence_++);
  writeU32(&raw[16], sampleIndex);
  if (payloadLength > 0) memcpy(&raw[kHeaderLength], payload, payloadLength);
  const size_t bodyLength = kHeaderLength + payloadLength;
  writeU16(&raw[bodyLength], crc16CcittFalse(raw, bodyLength));

  uint8_t encoded[kEncodedCapacity] = {};
  size_t encodedLength = 0;
  if (!cobsEncode(raw, bodyLength + kCrcLength, encoded, sizeof(encoded),
                  &encodedLength)) {
    return false;
  }
  if (xSemaphoreTake(transmitMutex_, pdMS_TO_TICKS(20)) != pdTRUE) return false;
  Serial.write(static_cast<uint8_t>(0));
  const size_t written = Serial.write(encoded, encodedLength);
  Serial.write(static_cast<uint8_t>(0));
  xSemaphoreGive(transmitMutex_);
  return written == encodedLength;
}

uint16_t ProtocolServer::readU16(const uint8_t* data) {
  return static_cast<uint16_t>(data[0]) |
         (static_cast<uint16_t>(data[1]) << 8);
}

uint32_t ProtocolServer::readU32(const uint8_t* data) {
  return static_cast<uint32_t>(data[0]) |
         (static_cast<uint32_t>(data[1]) << 8) |
         (static_cast<uint32_t>(data[2]) << 16) |
         (static_cast<uint32_t>(data[3]) << 24);
}

void ProtocolServer::writeU16(uint8_t* data, uint16_t value) {
  data[0] = static_cast<uint8_t>(value & 0xFFU);
  data[1] = static_cast<uint8_t>((value >> 8) & 0xFFU);
}

void ProtocolServer::writeU32(uint8_t* data, uint32_t value) {
  data[0] = static_cast<uint8_t>(value & 0xFFU);
  data[1] = static_cast<uint8_t>((value >> 8) & 0xFFU);
  data[2] = static_cast<uint8_t>((value >> 16) & 0xFFU);
  data[3] = static_cast<uint8_t>((value >> 24) & 0xFFU);
}

}  // namespace ultrasonic
