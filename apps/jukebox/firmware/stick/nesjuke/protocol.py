"""Link protocol v1, host side, for MicroPython (docs/PROTOCOL.md, part 3).

A port of host/protocol.py that sends the same bytes; tests/test_stick.py
holds the two together. What differs is how the work is spread out, because
the reply to a request should start within about 5.5 ms:

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
OP_SOUND = 0x50     # 'P': a sound record has played; ARG is its rate

# A button request's ARG: what the NES's controller asked for.
BUTTON_NEXT = 0x01      # Right
BUTTON_PREVIOUS = 0x02  # Left
BUTTON_PLAY = 0x04      # Start or A: play, or pause

# The NES reads its controller once a frame by holding OUT0 low for about
# two bit times, which the UART receives as this byte. It is expected, not
# noise.
PAD_READ_BYTE = 0xFE

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
PAUSE_MARKER = 0x3C  # an empty burst: the NES holds the music where it is
SOUND_MARKER = 0xC3  # a go burst: sound follows, at the rate in its payload
MAX_BURST_PAYLOAD = 255
BURST_HEADER = 3    # marker, sequence, length
DEFAULT_CREDIT = 24  # CREDIT_MAX in nes/serial_link.inc

# After a go burst the Stick keeps listening this long. A console that
# missed the burst asks again, at the latest after its 4-frame timeout; one
# that took it is silent. Then the Stick changes its UART's rate and starts
# the samples this long after the go burst. The console listens from 150 ms
# after it (SOUND_SETTLE in nes/serial_link.inc).
SOUND_LISTEN_MS = 100
SOUND_START_MS = 175


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
    frame it lands in. `discarded` counts those bytes, leaving out the one
    each controller read puts on the line.
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
        if ((op == OP_DATA or op == OP_HELLO or op == OP_BUTTON or op == OP_STATS
             or op == OP_SOUND)
                and window[3] == REQUEST_SEED ^ op ^ window[1] ^ window[2]):
            self.op = op
            self.seq = window[1]
            self.arg = window[2]
            self.count = 0
            return True
        if op != PAD_READ_BYTE:
            self.discarded += 1
        window[0] = window[1]
        window[1] = window[2]
        window[2] = window[3]
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

    Sound tracks are as in host/protocol.py: a sound request is answered
    with a go burst, which sets `sound_due`, and device.py does the rest
    with sound_begin() and sound_end().
    """

    def __init__(self, source, credit=DEFAULT_CREDIT, stopped=False):
        self.source = source
        self.stats = {"hello": 0, "bursts": 0, "resends": 0, "unexpected_seq": 0,
                      "buttons": 0}
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
        self.sealed_marker = BURST_MARKER
        # Stopped, every answer is an empty flush burst: the NES drops what
        # it has buffered, falls silent and keeps asking.
        self.stopped = stopped
        # Paused, every answer is an empty pause burst: the NES falls silent
        # and keeps what it has buffered. What is staged here stays staged.
        self.paused = False
        self.flush_next = False
        self.sound_due = False  # a go burst went out, and its sound has not
        self.last_go = False    # the last burst was one
        self.last_seq = None
        self.last_length = 0    # whole bytes of the last burst, header to CRC
        # For a clock: the NES starts playing once it holds its prefill, or
        # when the stream runs out first. `fresh_starts` counts the times
        # its buffer was emptied, `sent` the bytes sent to it since, and
        # `drained` says an empty burst told it to play what it has.
        self.fresh_starts = 0
        self.sent = 0
        self.drained = False

    def stop(self):
        self.stopped = True
        self.paused = False
        self.sound_due = False
        self._discard()

    def sound_begin(self):
        """The sound to send now: a sound.Sound."""
        return self.source.sound

    def sound_end(self):
        """The samples have gone. The next burst is a flush burst, so the
        music after a sound starts from a full buffer as a track change
        does."""
        self.source.sound_done()
        self.flush()

    def play(self):
        """Start the current track again from its beginning."""
        self.source.restart()
        self.stopped = self.paused = False
        self.flush()

    def flush(self):
        """Make the next burst a flush burst, for a source that has just
        jumped to another track. What was read ahead belongs to the old one."""
        self.flush_next = True
        self.sound_due = False
        self._discard()

    def press(self, buttons):
        """Do what the NES's controller asked for (BUTTON_* bits). Left and
        Right change the track and start it playing, also from stopped or
        paused. Start pauses and resumes; from stopped, or after the
        playlist's end, it plays the current track from its beginning."""
        source = self.source
        self.sound_due = False
        if buttons & (BUTTON_NEXT | BUTTON_PREVIOUS):
            if hasattr(source, "jump"):
                source.jump(1 if buttons & BUTTON_NEXT else -1)
                self.stopped = self.paused = False
                self.flush()
            else:
                self.play()     # a single track: start it again
        elif buttons & BUTTON_PLAY:
            if self.stopped or getattr(source, "finished", False):
                self.play()
            else:
                self.paused = not self.paused
                self.sealed_seq = None  # the burst made ready is the wrong kind

    def _discard(self):
        self.staged = 0
        self.sealed_seq = None

    def _fresh_start(self):
        self.fresh_starts += 1
        self.sent = 0
        self.drained = False

    def _reset(self):
        self.source.restart()
        self._fresh_start()
        self.staged = 0
        self.sealed_seq = None
        self.last_seq = None
        self.last_length = 0
        self.sound_due = False

    def _stage(self, want):
        if self.staged < want:
            data = self.source.take(want - self.staged)
            if data:
                start = BURST_HEADER + self.staged
                self.buffers[self.current][start:start + len(data)] = data
                self.staged += len(data)

    def _seal(self, seq, length, marker):
        buffer = self.buffers[self.current]
        buffer[0] = marker
        buffer[1] = seq
        buffer[2] = length
        table = CRC_TABLE
        crc = 0xFFFF
        if marker != BURST_MARKER:  # its CRC covers the marker as well
            crc = ((crc << 8) & 0xFF00) ^ table[(crc >> 8) ^ marker]
        end = BURST_HEADER + length
        for index in range(1, end):
            crc = ((crc << 8) & 0xFF00) ^ table[(crc >> 8) ^ buffer[index]]
        buffer[end] = crc >> 8
        buffer[end + 1] = crc & 0xFF
        self.sealed_seq = seq
        self.sealed_length = length
        self.sealed_marker = marker

    def prepare(self):
        """Build the burst the next request will most likely ask for. Call it
        while the line is idle: right after a reply, or while waiting."""
        if self.sealed_seq is not None:
            return
        seq = 0 if self.last_seq is None else (self.last_seq + 1) & 0xFF
        if self.stopped:
            self._seal(seq, 0, FLUSH_MARKER)
            return
        if self.paused:
            # Sealing writes the CRC where staged bytes sit, and those are
            # still wanted; handle() moves them out of the way first.
            if not self.staged:
                self._seal(seq, 0, PAUSE_MARKER)
            return
        self._stage(self.credit)
        if self.staged <= self.credit:
            self._seal(seq, self.staged, FLUSH_MARKER if self.flush_next else BURST_MARKER)

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
            self.press(arg)
            return None
        if op == OP_STATS:
            self.counters.report(seq, arg)
            return None
        credit = arg
        if seq == self.last_seq:
            # A go burst is only sent again while its sound is still due. If
            # that was called off (a button), the NES gets a new answer
            # under the same number, which is safe: it committed nothing.
            if self.sound_due or not self.last_go:
                self.stats["resends"] += 1
                return self.views[1 - self.current][:self.last_length]
        elif self.last_seq is not None and seq != (self.last_seq + 1) & 0xFF:
            self.stats["unexpected_seq"] += 1
        self.stats["bursts"] += 1
        go = False
        if op == OP_SOUND:
            credit = self.credit    # a sound request carries its rate, not a credit
        if self.stopped:
            length = 0
            marker = FLUSH_MARKER
        elif self.paused:
            length = 0
            marker = PAUSE_MARKER
        elif op == OP_SOUND:
            sound = getattr(self.source, "sound", None)
            if sound is not None and arg == sound.rate:
                # Nothing is staged: the source gives no more until the
                # sound is over. The payload is the rate.
                go = True
                self.buffers[self.current][BURST_HEADER] = arg
                self.staged = length = 1
                marker = SOUND_MARKER
            else:
                # The console cannot play it, or no sound is waiting here.
                # A flush burst ends its wait and carries on.
                if sound is not None:
                    self.source.sound_done()
                self._stage(DEFAULT_CREDIT)
                length = min(self.staged, DEFAULT_CREDIT)
                marker = FLUSH_MARKER
                self.flush_next = False
        else:
            self._stage(arg)
            length = min(self.staged, arg)
            marker = FLUSH_MARKER if self.flush_next else BURST_MARKER
            self.flush_next = False
        self.sound_due = self.last_go = go
        if marker == FLUSH_MARKER:
            self._fresh_start()
        if not go:
            self.sent += length
        if not length and marker == BURST_MARKER:
            self.drained = True
        sending = self.current
        if (self.sealed_seq != seq or self.sealed_length != length
                or self.sealed_marker != marker):
            # Not the request prepare() expected. Bytes staged beyond this
            # credit move to the other buffer first, because the CRC is
            # about to be written where they sit.
            extra = self.staged - length
            if extra:
                start = BURST_HEADER + length
                self.buffers[1 - sending][BURST_HEADER:BURST_HEADER + extra] = (
                    self.buffers[sending][start:start + extra])
            self._seal(seq, length, marker)
            self.staged = extra
        else:
            self.staged = 0
        self.current = 1 - sending
        self.sealed_seq = None
        self.credit = credit
        self.last_seq = seq
        self.last_length = BURST_HEADER + length + 2
        return self.views[sending][:self.last_length]
