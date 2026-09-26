"""Link protocol v1, host side (docs/PROTOCOL.md, part 3).

The NES paces the link: it sends a 4-byte request, and the host answers a
data request with one burst. This module is transport-free. Feed it the
bytes that arrive from the NES, and it returns the bytes to send back, so
the same code runs against a serial port, the StickS3's UART, or the
simulated line in the tests.
"""

from dataclasses import dataclass

import jbs

REQUEST_SEED = 0xA5
REQUEST_LENGTH = 4
OP_DATA = 0x4A      # 'J'
OP_HELLO = 0x48     # 'H'
OP_BUTTON = 0x42    # 'B'
OPS = frozenset({OP_DATA, OP_HELLO, OP_BUTTON})

BURST_MARKER = 0xA5
MAX_BURST_PAYLOAD = 255


def crc16(data, crc=0xFFFF):
    """CRC-16/CCITT-FALSE: polynomial $1021, initial $FFFF, no reflection."""
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return crc


def request_check(op, seq, arg):
    return REQUEST_SEED ^ op ^ seq ^ arg


def request_bytes(op, seq, arg):
    return bytes([op, seq, arg, request_check(op, seq, arg)])


def burst_bytes(seq, payload):
    if len(payload) > MAX_BURST_PAYLOAD:
        raise ValueError("burst payload too long")
    body = bytes([seq, len(payload)]) + bytes(payload)
    crc = crc16(body)
    return bytes([BURST_MARKER]) + body + bytes([crc >> 8, crc & 0xFF])


@dataclass(frozen=True)
class Request:
    op: int
    seq: int
    arg: int


class RequestDecoder:
    """Find requests in the byte stream from the NES.

    The line carries noise as well: break bytes around bursts and glitches
    from controller strobes. A candidate frame must have a known op and a
    valid check byte; on failure the scan moves forward one byte, because a
    good frame is often sitting one byte later.
    """

    def __init__(self):
        self.buffer = bytearray()
        self.discarded = 0

    def feed(self, data):
        self.buffer += data
        requests = []
        while len(self.buffer) >= REQUEST_LENGTH:
            op, seq, arg, check = self.buffer[:REQUEST_LENGTH]
            if op in OPS and check == request_check(op, seq, arg):
                requests.append(Request(op, seq, arg))
                del self.buffer[:REQUEST_LENGTH]
            else:
                del self.buffer[0]
                self.discarded += 1
        return requests


class StreamSource:
    """The bytes of a track as the NES should receive them, without end for a
    looping track. Positions are absolute, so a burst can be re-read."""

    def __init__(self, jbs_file):
        stream = jbs_file.stream
        if jbs_file.loop_frame is None:
            self.data = stream + bytes([jbs.OP_CONTROL, jbs.CTRL_END])
            self.loop_offset = None
        else:
            self.data = stream
            self.loop_offset = jbs_file.loop_offset
        self.position = 0

    def byte_at(self, position):
        if position < len(self.data):
            return self.data[position]
        if self.loop_offset is None:
            return None
        loop_length = len(self.data) - self.loop_offset
        return self.data[self.loop_offset + (position - len(self.data)) % loop_length]

    def take(self, count):
        out = bytearray()
        while len(out) < count:
            byte = self.byte_at(self.position)
            if byte is None:
                break
            out.append(byte)
            self.position += 1
        return bytes(out)


class Host:
    """Answer the NES's requests from one track.

    A data request names the burst the NES wants. The same sequence number
    as the last burst means it never arrived intact, so the host sends those
    stream bytes again (fewer if the credit is smaller). The next sequence
    number means the last burst was committed, so the host moves on.
    """

    def __init__(self, jbs_file):
        self.jbs_file = jbs_file
        self.stats = {"hello": 0, "bursts": 0, "resends": 0, "unexpected_seq": 0,
                      "buttons": 0}
        self.buttons = []
        self._reset()

    def _reset(self):
        self.source = StreamSource(self.jbs_file)
        self.last_seq = None
        self.burst_start = 0

    def handle(self, request):
        """Return the bytes to send for one request (empty for none)."""
        if request.op == OP_HELLO:
            self.stats["hello"] += 1
            self._reset()
            return b""
        if request.op == OP_BUTTON:
            self.stats["buttons"] += 1
            self.buttons.append(request.arg)
            return b""
        if request.seq == self.last_seq:
            self.stats["resends"] += 1
            self.source.position = self.burst_start
        else:
            if self.last_seq is not None and request.seq != (self.last_seq + 1) & 0xFF:
                self.stats["unexpected_seq"] += 1
            self.burst_start = self.source.position
            self.last_seq = request.seq
        self.stats["bursts"] += 1
        payload = self.source.take(min(request.arg, MAX_BURST_PAYLOAD))
        return burst_bytes(request.seq, payload)
