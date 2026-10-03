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
OP_STATS = 0x53     # 'S'
OPS = frozenset({OP_DATA, OP_HELLO, OP_BUTTON, OP_STATS})

# The counters the NES reports with OP_STATS, in the order of its index
# (STATS_TABLE in nes/serial_link.inc). Each report carries a low byte.
NES_COUNTERS = ("aborts", "timeouts", "rejects", "crc_errors", "request_delay",
                "underruns", "bursts")
NES_LEVELS = frozenset({"request_delay"})  # a setting, not a count


class NesCounters:
    """The NES's counters as totals for this session.

    A report is only the low byte of a count that started when the console
    was switched on. Here each count starts from the first report heard, or
    from zero if the NES said hello (it has just booted), and the steps
    between reports are added up, so it neither wraps at 256 nor includes
    what happened before this host was listening.
    """

    def __init__(self):
        self.totals = {}
        self.raw = {}
        self.booted = False

    def hello(self):
        self.totals = {}
        self.raw = {}
        self.booted = True

    def report(self, index, value):
        if index >= len(NES_COUNTERS):
            return
        name = NES_COUNTERS[index]
        if name in NES_LEVELS:
            self.totals[name] = value
            return
        if name in self.raw:
            self.totals[name] += (value - self.raw[name]) & 0xFF
        else:
            self.totals[name] = value if self.booted else 0
        self.raw[name] = value

BURST_MARKER = 0xA5
FLUSH_MARKER = 0x5A  # a burst that first drops what the NES has buffered
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


def burst_bytes(seq, payload, flush=False):
    """A burst, or a flush burst, whose CRC covers its marker as well."""
    if len(payload) > MAX_BURST_PAYLOAD:
        raise ValueError("burst payload too long")
    body = bytes([seq, len(payload)]) + bytes(payload)
    if flush:
        crc = crc16(bytes([FLUSH_MARKER]) + body)
        return bytes([FLUSH_MARKER]) + body + bytes([crc >> 8, crc & 0xFF])
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

    def restart(self):
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
    as the last burst means it never arrived intact, so the host sends
    exactly the same burst again. The next sequence number means the last
    burst was committed, so the host moves on.

    Resends must be identical. A slow host can have several copies of one
    burst on the wire, and the NES commits whichever arrives intact; if the
    copies differed, the host could not know how much was committed. An
    identical copy always fits, because the NES's credit for a repeated
    sequence number never shrinks: nothing was committed, and playback only
    frees space.

    The host can also be stopped. It then answers every request with an
    empty flush burst: the NES drops what it has buffered, falls silent and
    keeps asking, so the link stays alive. play() starts the current track
    again from its beginning, and flush() makes the next burst a flush burst,
    for a source that has just jumped to another track.
    """

    def __init__(self, source, stopped=False):
        """source is a JbsFile (one track) or anything with take(count) and
        restart(), such as a playlist.PlaylistSource."""
        self.source = StreamSource(source) if isinstance(source, jbs.JbsFile) else source
        self.stats = {"hello": 0, "bursts": 0, "resends": 0, "unexpected_seq": 0,
                      "buttons": 0}
        self.buttons = []
        self.counters = NesCounters()
        self.nes = self.counters.totals  # counter name -> total this session
        self.last_seq = None
        self.last_burst = b""
        self.stopped = stopped
        self.flush_next = False

    def stop(self):
        self.stopped = True

    def play(self):
        self.source.restart()
        self.stopped = False
        self.flush_next = True

    def flush(self):
        self.flush_next = True

    def _reset(self):
        self.source.restart()
        self.last_seq = None
        self.last_burst = b""

    def handle(self, request):
        """Return the bytes to send for one request (empty for none)."""
        if request.op == OP_HELLO:
            self.stats["hello"] += 1
            self._reset()
            self.counters.hello()
            self.nes = self.counters.totals
            return b""
        if request.op == OP_BUTTON:
            self.stats["buttons"] += 1
            self.buttons.append(request.arg)
            return b""
        if request.op == OP_STATS:
            self.counters.report(request.seq, request.arg)
            return b""
        if request.seq == self.last_seq:
            self.stats["resends"] += 1
            return self.last_burst
        if self.last_seq is not None and request.seq != (self.last_seq + 1) & 0xFF:
            self.stats["unexpected_seq"] += 1
        self.stats["bursts"] += 1
        if self.stopped:
            payload, flush = b"", True
        else:
            payload = self.source.take(min(request.arg, MAX_BURST_PAYLOAD))
            flush, self.flush_next = self.flush_next, False
        self.last_seq = request.seq
        self.last_burst = burst_bytes(request.seq, payload, flush)
        return self.last_burst
