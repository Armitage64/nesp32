"""Frames of the link (docs/PROTOCOL.md).

    request   $57, OP, LEN, PAYLOAD[LEN], CRC_HI, CRC_LO      console to Stick
    reply     $A5, STATE, LINE_LO, LINE_HI, TOTAL_LO, TOTAL_HI,
              TEXT[28], CRC_HI, CRC_LO                        always 36 bytes

The CRC is CRC-16/CCITT-FALSE over everything between the marker and the
CRC. The Stick only needs Decoder and fill_reply; the builders and parsers
of the other direction are here for the tests and the tools.
"""

from neswiki.linkrate import COLUMNS, HEADER_SIZE, QUERY_MAX, REPLY_SIZE

REQUEST_MARKER = 0x57
REPLY_MARKER = 0xA5

OP_SEARCH = 0x01                # payload: an id, then the words to search for
OP_LINE = 0x02                  # payload: a line's number, low byte first
PAYLOAD_MAX = 1 + QUERY_MAX
REQUEST_MAX = 3 + PAYLOAD_MAX + 2

# What the Stick says of itself.
IDLE, NO_WIFI, FETCHING, READY, NOT_FOUND, ERROR = range(6)
NO_SUCH_LINE = 0x80             # with the state, on a LINE reply: it has no such line
MORE = 0x40                     # with READY: the article is still arriving
NO_LINE = 0xFF00                # a reply's line when it is not a line's: | the search's id


def _table():
    entries = []
    for index in range(256):
        crc = index << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
        entries.append(crc)
    return entries


_CRC = _table()


def crc16(data, start=0, end=None):
    """The CRC of data[start:end], without slicing it."""
    table = _CRC
    crc = 0xFFFF
    for index in range(start, len(data) if end is None else end):
        crc = ((crc << 8) & 0xFF00) ^ table[(crc >> 8) ^ data[index]]
    return crc


def request(op, payload=b""):
    body = bytes((op, len(payload))) + bytes(payload)
    crc = crc16(body)
    return bytes((REQUEST_MARKER,)) + body + bytes((crc >> 8, crc & 0xFF))


def search_request(search_id, query):
    return request(OP_SEARCH, bytes((search_id,)) + query)


def line_request(number):
    return request(OP_LINE, bytes((number & 0xFF, number >> 8)))


def fill_reply(reply, state, line, total, text=None, start=0):
    """Make `reply`, a bytearray of REPLY_SIZE, a reply. Its text is COLUMNS
    bytes of `text` from `start`, or spaces if there is none; nothing is
    allocated when text is a memoryview."""
    reply[0] = REPLY_MARKER
    reply[1] = state
    reply[2] = line & 0xFF
    reply[3] = line >> 8
    reply[4] = total & 0xFF
    reply[5] = total >> 8
    if text is None:
        for index in range(HEADER_SIZE, HEADER_SIZE + COLUMNS):
            reply[index] = 0x20
    else:
        reply[HEADER_SIZE:HEADER_SIZE + COLUMNS] = text[start:start + COLUMNS]
    crc = crc16(reply, 1, REPLY_SIZE - 2)
    reply[REPLY_SIZE - 2] = crc >> 8
    reply[REPLY_SIZE - 1] = crc & 0xFF


def parse_reply(data):
    """(state, line, total, text) of a reply, or None if it is not one."""
    if len(data) != REPLY_SIZE or data[0] != REPLY_MARKER:
        return None
    crc = crc16(data, 1, REPLY_SIZE - 2)
    if data[REPLY_SIZE - 2] != crc >> 8 or data[REPLY_SIZE - 1] != crc & 0xFF:
        return None
    return (data[1], data[2] | data[3] << 8, data[4] | data[5] << 8,
            bytes(data[HEADER_SIZE:HEADER_SIZE + COLUMNS]))


def message(text):
    """Text for a reply: COLUMNS bytes, centered, capitals as the console's
    own messages are."""
    text = text.upper()[:COLUMNS]
    left = (COLUMNS - len(text)) // 2
    return (b" " * left + text.encode() + b" " * COLUMNS)[:COLUMNS]


class Decoder:
    """Finds requests in what the UART receives.

    The line is not clean: the console's controller read puts a junk byte
    on it every frame, and a request may arrive in pieces. feed() takes
    whatever has come and returns the whole requests in it, as (op,
    payload). Anything that is not a marker followed by a frame with a good
    CRC is passed over a byte at a time.
    """

    def __init__(self):
        self.held = b""
        self.discarded = 0

    def feed(self, data):
        held = self.held + data if self.held else bytes(data)
        found = []
        position = 0
        size = len(held)
        while True:
            start = held.find(b"\x57", position)
            if start < 0:
                self.discarded += size - position
                position = size
                break
            self.discarded += start - position
            position = start
            if size - position < 3:
                break                       # its length has not come yet
            length = held[position + 2]
            if length > PAYLOAD_MAX:
                position += 1               # not a frame: look further on
                self.discarded += 1
                continue
            end = position + 3 + length + 2
            if end > size:
                break                       # the rest has not come yet
            crc = crc16(held, position + 1, end - 2)
            if held[end - 2] == crc >> 8 and held[end - 1] == crc & 0xFF:
                found.append((held[position + 1], held[position + 3:end - 2]))
                position = end
            else:
                position += 1
                self.discarded += 1
        self.held = held[position:]
        return found
