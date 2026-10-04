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
OP_SOUND = 0x50     # 'P': a sound record has played; ARG is its rate
OPS = frozenset({OP_DATA, OP_HELLO, OP_BUTTON, OP_STATS, OP_SOUND})

# A button request's ARG: what the NES's controller asked for.
BUTTON_NEXT = 0x01      # Right
BUTTON_PREVIOUS = 0x02  # Left
BUTTON_PLAY = 0x04      # Start or A: play, or pause

# The NES reads its controller once a frame by holding OUT0 low for about
# two bit times, which a UART receives as this byte. It is expected, not
# noise.
PAD_READ_BYTE = 0xFE

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
PAUSE_MARKER = 0x3C  # an empty burst: the NES holds the music where it is
SOUND_MARKER = 0xC3  # a go burst: sound follows, at the rate in its payload
SOUND_REFUSED = 0xFF  # a sound request's ARG from a console that cannot play it
MAX_BURST_PAYLOAD = 255
DEFAULT_CREDIT = 24  # CREDIT_MAX in nes/serial_link.inc

# After a go burst the host keeps listening this long. A console that
# missed the burst asks again, at the latest after its 4-frame timeout; one
# that took it is silent. Then the host changes its UART's rate and starts
# the samples this long after the go burst. The console listens from 150 ms
# after it (SOUND_SETTLE in nes/serial_link.inc).
SOUND_LISTEN_MS = 100
SOUND_START_MS = 175


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


def burst_bytes(seq, payload, flush=False, pause=False, go=False):
    """A burst, or a flush, pause or go burst, whose CRC covers its marker
    as well."""
    if len(payload) > MAX_BURST_PAYLOAD:
        raise ValueError("burst payload too long")
    body = bytes([seq, len(payload)]) + bytes(payload)
    if flush or pause or go:
        marker = bytes([FLUSH_MARKER if flush else PAUSE_MARKER if pause else SOUND_MARKER])
        crc = crc16(marker + body)
        return marker + body + bytes([crc >> 8, crc & 0xFF])
    crc = crc16(body)
    return bytes([BURST_MARKER]) + body + bytes([crc >> 8, crc & 0xFF])


@dataclass(frozen=True)
class Request:
    op: int
    seq: int
    arg: int


class RequestDecoder:
    """Find requests in the byte stream from the NES.

    The line carries other bytes as well: one from each controller read
    (PAD_READ_BYTE, once a frame), and noise. A candidate frame must have a
    known op and a valid check byte; on failure the scan moves forward one
    byte, because a good frame is often sitting one byte later. `discarded`
    counts the bytes passed over, leaving out the controller reads.
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
                if op != PAD_READ_BYTE:
                    self.discarded += 1
                del self.buffer[0]
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

    Paused, it answers with empty pause bursts: the NES falls silent but
    keeps what it has buffered, and carries on from there with the first
    ordinary burst after `paused` is cleared.

    A source may hold sound tracks (playlist.PlaylistSource). When the NES
    reaches one it sends a sound request, and the answer is a go burst,
    which sets `sound_due`. Whoever owns the serial port then does the
    rest: if no request arrives for SOUND_LISTEN_MS, the NES took the burst
    and is waiting for samples, so it sends sound_begin()'s samples at
    their own baud rate and calls sound_end(). A request in that time
    means the NES is not waiting: a sound request is answered with the same
    go burst and the wait starts over, and anything else clears
    `sound_due`. The host's own buttons must wait while it is set, because
    a console that took the go burst hears nothing but samples.
    """

    def __init__(self, source, stopped=False):
        """source is a JbsFile (one track) or anything with take(count) and
        restart(), such as a playlist.PlaylistSource."""
        self.source = StreamSource(source) if isinstance(source, jbs.JbsFile) else source
        self.stats = {"hello": 0, "bursts": 0, "resends": 0, "unexpected_seq": 0,
                      "buttons": 0}
        self.counters = NesCounters()
        self.nes = self.counters.totals  # counter name -> total this session
        self.last_seq = None
        self.last_burst = b""
        self.stopped = stopped
        self.paused = False
        self.flush_next = False
        self.sound_due = False  # a go burst went out; see the class comment
        self.last_go = False    # the last burst was one

    def stop(self):
        self.stopped = True
        self.paused = False
        self.sound_due = False

    def play(self):
        self.source.restart()
        self.stopped = self.paused = False
        self.flush_next = True
        self.sound_due = False

    def flush(self):
        self.flush_next = True
        self.sound_due = False

    def sound_begin(self):
        """The sound to send now: a pcm.Sound."""
        return self.source.sound

    def sound_end(self):
        """The samples have gone. The next burst is a flush burst, so the
        music after a sound starts from a full buffer as a track change
        does."""
        self.source.sound_done()
        self.sound_due = False
        self.flush_next = True

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

    def _reset(self):
        self.source.restart()
        self.last_seq = None
        self.last_burst = b""
        self.sound_due = False

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
            self.press(request.arg)
            return b""
        if request.op == OP_STATS:
            self.counters.report(request.seq, request.arg)
            return b""
        wants_sound = request.op == OP_SOUND
        if request.seq == self.last_seq:
            # A go burst is only sent again while its sound is still due. If
            # that was called off (a button), the NES gets a new answer
            # under the same number, which is safe: it committed nothing.
            if self.sound_due or not self.last_go:
                self.stats["resends"] += 1
                return self.last_burst
        elif self.last_seq is not None and request.seq != (self.last_seq + 1) & 0xFF:
            self.stats["unexpected_seq"] += 1
        self.stats["bursts"] += 1
        pause = go = False
        if self.stopped:
            payload, flush = b"", True
        elif self.paused:
            payload, flush, pause = b"", False, True
        elif wants_sound:
            sound = getattr(self.source, "sound", None)
            if sound is not None and request.arg == sound.rate:
                payload, flush, go = bytes([sound.rate]), False, True
            else:
                # The console cannot play it (SOUND_REFUSED), or this host
                # has no sound waiting. A flush burst ends its wait, and
                # carries on with whatever is next.
                if sound is not None:
                    self.source.sound_done()
                payload, flush = self.source.take(DEFAULT_CREDIT), True
                self.flush_next = False
        else:
            payload = self.source.take(min(request.arg, MAX_BURST_PAYLOAD))
            flush, self.flush_next = self.flush_next, False
        self.sound_due = self.last_go = go
        self.last_seq = request.seq
        self.last_burst = burst_bytes(request.seq, payload, flush, pause, go)
        return self.last_burst
