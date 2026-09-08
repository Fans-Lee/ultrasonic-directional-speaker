#pragma once

#include <stddef.h>
#include <stdint.h>

namespace ultrasonic {

uint16_t crc16CcittFalse(const uint8_t* data, size_t length);

}  // namespace ultrasonic
