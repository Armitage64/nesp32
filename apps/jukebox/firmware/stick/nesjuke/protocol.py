"""Link protocol v1, host side, for MicroPython (docs/PROTOCOL.md, part 3).

A port of host/protocol.py that sends the same bytes; tests/test_stick.py
holds the two together. What differs is how the work is spread out, because
the reply to a request should start within about 6 ms:

- the CRC is table-driven;
- nothing here deletes from or grows a buffer on the reply path. The decoder
  is a 4-byte sliding window, and bursts are built in two fixed buffers;
- prepare() builds the next burst while the line is idle, so answering the
  usual request is a comparison and one uart.write().
"""

import array

REQUEST_SEED = 0xA5
OP_DATA = 0x4A      # 'J'
OP_HELLO = 0x48     # 'H'
OP_BUTTON = 0x42    # 'B'
OP_STATS = 0x53     # 'S'

# The counters the NES reports with OP_STATS, in the order of its index
# (STATS_TABLE in nes/serial_link.inc). Each report carries a low byte.
NES_COUNTERS = ("aborts", "timeouts", "rejects", "crc_errors", "request_delay",
                "underruns", "bursts")
NES_LEVELS = ("request_delay",)  # a setting, not a count


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
BURST_HEADER = 3    # marker, sequence, length
DEFAULT_CREDIT = 24  # CREDIT_MAX in nes/serial_link.inc


def _crc_table():
    table = array.array("H", [0] * 256)
    for index in range(256):
        crc = index << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
        table[index] = crc & 0xFFFF
    return table


CRC_TABLE = _crc_table()


def crc16(data, crc=0xFFFF):
    """CRC-16/CCITT-FALSE: polynomial $1021, initial $FFFF, no reflection."""
    table = CRC_TABLE
    for byte in data:
        crc = ((crc << 8) & 0xFF00) ^ table[(crc >> 8) ^ byte]
    return crc


class RequestDecoder:
    """Find requests in the byte stream from the NES, one byte at a time.

    push() returns True when a request completes and leaves it in op, seq
    and arg. A window with an unknown op or a bad check byte drops its oldest
    byte, as host/protocol.py's decoder does, so noise costs at most the
    frame it lands in.
    """

    def __init__(self):
        self.window = bytearray(4)
        self.count = 0
        self.discarded = 0
        self.op = self.seq = self.arg = 0

    def push(self, byte):
        window = self.window
        window[self.count] = byte
        if self.count < 3:
            self.count += 1
            return False
        op = window[0]
        if ((op == OP_DATA or op == OP_HELLO or op == OP_BUTTON or op == OP_STATS)
                and window[3] == REQUEST_SEED ^ op ^ window[1] ^ window[2]):
            self.op = op
            self.seq = window[1]
            self.arg = window[2]
            self.count = 0
            return True
        window[0] = window[1]
        window[1] = window[2]
        window[2] = window[3]
        self.discarded += 1
        return False


class Host:
    """Answer the NES's requests from a source with take(count) and restart().

    The rules are host/protocol.py's: the same sequence number as the last
    burst gets exactly the same burst again, and any other gets new data.

    Two buffers take turns. One holds the last burst sent, for resends. The
    other collects the payload of the next one: `staged` bytes taken from the
    source, starting at BURST_HEADER. prepare() also seals it (header and
    CRC) for the request the NES will most likely send, the next sequence
    number with the same credit as last time.
    """

    def __init__(self, source, credit=DEFAULT_CREDIT, stopped=False):
        self.source = source
        self.stats = {"hello": 0, "bursts": 0, "resends": 0, "unexpected_seq": 0,
                      "buttons": 0}
        self.buttons = []
        self.counters = NesCounters()
        self.nes = self.counters.totals  # counter name -> total this session
        size = BURST_HEADER + MAX_BURST_PAYLOAD + 2
        self.buffers = (bytearray(size), bytearray(size))
        self.views = (memoryview(self.buffers[0]), memoryview(self.buffers[1]))
        self.credit = credit
        self.current = 0        # which buffer collects the next burst
        self.staged = 0
        self.sealed_seq = None  # the staged burst is complete for this request
        self.sealed_length = 0
        self.sealed_flush = False
        # Stopped, every answer is an empty flush burst: the NES drops what
        # it has buffered, falls silent and keeps asking.
        self.stopped = stopped
        self.flush_next = False
        self.last_seq = None
        self.last_length = 0    # whole bytes of the last burst, header to CRC

    def stop(self):
        self.stopped = True
        self._discard()

    def play(self):
        """Start the current track again from its beginning."""
        self.source.restart()
        self.stopped = False
        self.flush()

    def flush(self):
        """Make the next burst a flush burst, for a source that has just
        jumped to another track. What was read ahead belongs to the old one."""
        self.flush_next = True
        self._discard()

    def _discard(self):
        self.staged = 0
        self.sealed_seq = None

    def _reset(self):
        self.source.restart()
        self.staged = 0
        self.sealed_seq = None
        self.last_seq = None
        self.last_length = 0

    def _stage(self, want):
        if self.staged < want:
            data = self.source.take(want - self.staged)
            if data:
                start = BURST_HEADER + self.staged
                self.buffers[self.current][start:start + len(data)] = data
                self.staged += len(data)

    def _seal(self, seq, length, flush):
        buffer = self.buffers[self.current]
        buffer[1] = seq
        buffer[2] = length
        table = CRC_TABLE
        crc = 0xFFFF
        if flush:   # its CRC covers the marker as well
            buffer[0] = FLUSH_MARKER
            crc = ((crc << 8) & 0xFF00) ^ table[(crc >> 8) ^ FLUSH_MARKER]
        else:
            buffer[0] = BURST_MARKER
        end = BURST_HEADER + length
        for index in range(1, end):
            crc = ((crc << 8) & 0xFF00) ^ table[(crc >> 8) ^ buffer[index]]
        buffer[end] = crc >> 8
        buffer[end + 1] = crc & 0xFF
        self.sealed_seq = seq
        self.sealed_length = length
        self.sealed_flush = flush

    def prepare(self):
        """Build the burst the next request will most likely ask for. Call it
        while the line is idle: right after a reply, or while waiting."""
        if self.sealed_seq is not None:
            return
        seq = 0 if self.last_seq is None else (self.last_seq + 1) & 0xFF
        if self.stopped:
            self._seal(seq, 0, True)
            return
        self._stage(self.credit)
        if self.staged <= self.credit:
            self._seal(seq, self.staged, self.flush_next)

    def handle(self, op, seq, arg):
        """Return the bytes to send for one request, or None for none. The
        result is a view of a buffer that stays valid until the next call."""
        if op == OP_HELLO:
            self.stats["hello"] += 1
            self._reset()
            self.counters.hello()
            self.nes = self.counters.totals
            return None
        if op == OP_BUTTON:
            self.stats["buttons"] += 1
            self.buttons.append(arg)
            return None
        if op == OP_STATS:
            self.counters.report(seq, arg)
            return None
        if seq == self.last_seq:
            self.stats["resends"] += 1
            return self.views[1 - self.current][:self.last_length]
        if self.last_seq is not None and seq != (self.last_seq + 1) & 0xFF:
            self.stats["unexpected_seq"] += 1
        self.stats["bursts"] += 1
        if self.stopped:
            length = 0
            flush = True
        else:
            self._stage(arg)
            length = min(self.staged, arg)
            flush = self.flush_next
            self.flush_next = False
        sending = self.current
        if (self.sealed_seq != seq or self.sealed_length != length
                or self.sealed_flush != flush):
            # Not the request prepare() expected. Bytes staged beyond this
            # credit move to the other buffer first, because the CRC is
            # about to be written where they sit.
            extra = self.staged - length
            if extra:
                start = BURST_HEADER + length
                self.buffers[1 - sending][BURST_HEADER:BURST_HEADER + extra] = (
                    self.buffers[sending][start:start + extra])
            self._seal(seq, length, flush)
            self.staged = extra
        else:
            self.staged = 0
        self.current = 1 - sending
        self.sealed_seq = None
        self.credit = arg
        self.last_seq = seq
        self.last_length = BURST_HEADER + length + 2
        return self.views[sending][:self.last_length]
