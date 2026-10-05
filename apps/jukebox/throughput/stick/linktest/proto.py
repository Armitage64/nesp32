"""Frames of the throughput test (README.md, "Protocol").

The Stick is in charge here, the reverse of the jukebox's link: it sends a
command and the console answers. Both travel at the control rate.

    command   $C5, SEQ, OP, LEN, PAYLOAD[LEN], CRC_HI, CRC_LO
    reply     $9A, SEQ, OP, VALUE_LO, VALUE_HI, CRC_HI, CRC_LO

The CRC is CRC-16/CCITT-FALSE, the jukebox's, over SEQ up to the CRC.
"""

CMD_MARKER = 0xC5
REPLY_MARKER = 0x9A
REPLY_SIZE = 7

OP_PING = 1                     # value: rates to the Stick << 8 | rates to the console
OP_DRAW = 2                     # payload: PPU address high, low, then tiles
OP_RX = 3                       # payload: rate, seed low, seed high
OP_TX = 4                       # the same; answered with the block, no reply
OP_PORT = 5                     # value: what the console's $4017 reads
OP_PAD = 6                      # value: the buttons held on controller 1 (PAD_*)

PAD_START = 0x10                # A B Select Start Up Down Left Right, A in bit 7

DRAW_MAX = 32                   # tiles in one draw
ERROR_VALUE = 0xFFFF            # the console could not do what was asked


def crc16(data, crc=0xFFFF):
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
        crc &= 0xFFFF
    return crc


def command(seq, op, payload=b""):
    body = bytes((seq, op, len(payload))) + bytes(payload)
    crc = crc16(body)
    return bytes((CMD_MARKER,)) + body + bytes((crc >> 8, crc & 0xFF))


def reply(seq, op, value):
    """What the console sends; the tests and the simulation use it."""
    body = bytes((seq, op, value & 0xFF, value >> 8))
    crc = crc16(body)
    return bytes((REPLY_MARKER,)) + body + bytes((crc >> 8, crc & 0xFF))


def parse_reply(data, seq, op):
    """The value of the reply to (seq, op) found anywhere in data, or None.

    Noise ahead of the reply, and replies to older commands, are passed
    over."""
    for start in range(len(data) - REPLY_SIZE + 1):
        if data[start] != REPLY_MARKER or data[start + 1] != seq or data[start + 2] != op:
            continue
        crc = crc16(data[start + 1:start + 5])
        if data[start + 5] == crc >> 8 and data[start + 6] == crc & 0xFF:
            return data[start + 3] | data[start + 4] << 8
    return None


def pattern(seed, count):
    """The test block for a seed: count bytes of a 16-bit xorshift (7, 9, 8).

    Written as the console's 6502 code does it (prng_next in linktest.s), a
    byte at a time, so the two cannot drift apart. The seed must not be 0."""
    hi, lo = seed >> 8, seed & 0xFF
    out = bytearray(count)
    for index in range(count):
        a = (lo >> 1) | ((hi & 1) << 7)     # lsr hi (to carry), ror lo
        carry = lo & 1
        hi ^= a
        a = (hi >> 1) | (carry << 7)        # ror
        lo ^= a
        hi ^= lo
        out[index] = hi
    return bytes(out)
