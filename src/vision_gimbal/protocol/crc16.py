"""CRC-16/CCITT-FALSE used by the device protocol."""

import binascii


def crc16_ccitt_false(data: bytes) -> int:
    """Return CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF)."""

    return binascii.crc_hqx(data, 0xFFFF)
