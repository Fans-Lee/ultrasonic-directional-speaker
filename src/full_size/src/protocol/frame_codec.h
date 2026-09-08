#pragma once

#include <stddef.h>
#include <stdint.h>

namespace ultrasonic {

bool cobsDecode(const uint8_t* encoded, size_t encodedLength, uint8_t* decoded,
                size_t decodedCapacity, size_t* decodedLength);
bool cobsEncode(const uint8_t* raw, size_t rawLength, uint8_t* encoded,
                size_t encodedCapacity, size_t* encodedLength);

}  // namespace ultrasonic
