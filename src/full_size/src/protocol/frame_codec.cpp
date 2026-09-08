#include "frame_codec.h"

namespace ultrasonic {

bool cobsDecode(const uint8_t* encoded, size_t encodedLength, uint8_t* decoded,
                size_t decodedCapacity, size_t* decodedLength) {
  if (encoded == nullptr || decoded == nullptr || decodedLength == nullptr ||
      encodedLength == 0) {
    return false;
  }
  size_t inputIndex = 0;
  size_t outputIndex = 0;
  while (inputIndex < encodedLength) {
    const uint8_t code = encoded[inputIndex++];
    if (code == 0) return false;
    const size_t copyLength = static_cast<size_t>(code - 1);
    if (inputIndex + copyLength > encodedLength ||
        outputIndex + copyLength > decodedCapacity) {
      return false;
    }
    for (size_t index = 0; index < copyLength; ++index) {
      decoded[outputIndex++] = encoded[inputIndex++];
    }
    if (code != 0xFF && inputIndex < encodedLength) {
      if (outputIndex >= decodedCapacity) return false;
      decoded[outputIndex++] = 0;
    }
  }
  *decodedLength = outputIndex;
  return true;
}

bool cobsEncode(const uint8_t* raw, size_t rawLength, uint8_t* encoded,
                size_t encodedCapacity, size_t* encodedLength) {
  if (raw == nullptr || encoded == nullptr || encodedLength == nullptr ||
      encodedCapacity == 0) {
    return false;
  }
  size_t readIndex = 0;
  size_t writeIndex = 1;
  size_t codeIndex = 0;
  uint8_t code = 1;
  while (readIndex < rawLength) {
    if (raw[readIndex] == 0) {
      if (codeIndex >= encodedCapacity) return false;
      encoded[codeIndex] = code;
      codeIndex = writeIndex;
      if (writeIndex >= encodedCapacity) return false;
      ++writeIndex;
      code = 1;
      ++readIndex;
      continue;
    }
    if (writeIndex >= encodedCapacity) return false;
    encoded[writeIndex++] = raw[readIndex++];
    ++code;
    if (code == 0xFF) {
      encoded[codeIndex] = code;
      codeIndex = writeIndex;
      if (writeIndex >= encodedCapacity) return false;
      ++writeIndex;
      code = 1;
    }
  }
  if (codeIndex >= encodedCapacity) return false;
  encoded[codeIndex] = code;
  *encodedLength = writeIndex;
  return true;
}

}  // namespace ultrasonic
