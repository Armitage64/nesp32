"""Sampled sound for the jukebox: the rates, the bytes on the wire, and the
.pcm file (docs/PROTOCOL.md, part 4).

The console plays sampled sound by writing each byte it receives to $4011,
the 7-bit DAC of its sample channel, as the byte arrives. A byte is a
sample, so the host's UART is the clock: 11 bits a byte (8N2), at a rate
that is a whole number of CPU cycles a bit so that the console's bit-banged
receiver hits every bit.

That receiver (nes/sound.inc, written by tools/gen_pcm.py) keeps the byte in
A and folds each read of the port into it: shift left, XOR $4017. It ends up
with the byte's bits reversed and inverted, and with the $40 that the port's
unused bits read left in from the last two reads (raw_byte). Nothing puts
that right on the console. A file holds each sample as the byte that the
scramble turns into its level, with bit 7 set, which $4011 ignores; the
stream ends at the first byte that arrives without it.

    "NPCM", version (1), cycles a bit, title length n, 0, title, samples

A nesp32 sends a file's samples as they are (its JUKE service, juke.c
there), and ends them with LAST_BYTE.
"""

from dataclasses import dataclass

CPU_HZ = 1789773                # NTSC: 21.477272 MHz / 12
PERIODS = (21, 16, 14, 12, 10, 8)   # cycles a bit: 7748 to 20338 samples a second
DEFAULT_PERIOD = 16
FRAME_BITS = 11                 # a start bit, 8 data bits, 2 stop bits
ROOMY_FROM = 13                 # cycles a bit from which the receiver's padding needs Y

# Port 2 as an instruction with $4017 as its operand reads it with the line
# at rest: bit 0 is D0 inverted, D1 to D4 read 0 with nothing on them, and
# bits 5 to 7 are what was last on the bus, the $40 of the address. The
# receiver counts on it, and the console checks before it agrees to play.
PORT_IDLE = 0x40

LEVELS = 128                    # $4011 takes 7 bits
MORE = 0x80                     # set in what the console holds for every byte but the last
FRAMES_PER_SECOND = 60          # the stream's frames, for a length on the screen

MAGIC = b"NPCM"
VERSION = 1
HEADER_SIZE = 8
TITLE_MAX = 255


def baud(period):
    return (CPU_HZ + period // 2) // period


def sample_rate(period):
    """Samples a second: a byte is a sample."""
    return baud(period) / FRAME_BITS


def raw_byte(byte):
    """What the console's receiver holds after a byte."""
    reverse = int("{:08b}".format(byte)[::-1], 2)
    return reverse ^ 0xFF ^ (PORT_IDLE | (PORT_IDLE << 1) & 0xFF)


def wire_byte(raw):
    """The byte to send for the receiver to end up holding raw."""
    return int("{:08b}".format(raw ^ raw_byte(0))[::-1], 2)


def sample_byte(level, last=False):
    """The byte on the wire for one sample, a level for $4011."""
    return wire_byte((level & (LEVELS - 1)) | (0 if last else MORE))


LAST_BYTE = bytes((sample_byte(0, last=True),))     # ends a stream, leaving the DAC at 0

# A console left in the middle of a stream waits for the rest with no
# timeout. A nesp32 sends this at the link's rate when it starts: long
# lows, which the stream routines take for last bytes at any rate, and
# which the link passes over as noise.
FILLER = bytes(4)
assert all(not raw_byte(byte) & MORE for byte in FILLER)


def encode(levels):
    """Samples for $4011, 0 to 127, as a file's bytes."""
    return bytes(sample_byte(level) for level in levels)


def decode(samples):
    """A file's samples as levels for $4011."""
    return [raw_byte(byte) & (LEVELS - 1) for byte in samples]


@dataclass
class Sound:
    """A sound track: its samples as the wire wants them, and its rate."""
    title: str
    period: int
    samples: bytes

    @property
    def rate(self):
        """The index of its rate in PERIODS, which is what the console is told."""
        return PERIODS.index(self.period)

    @property
    def frames(self):
        """How long it plays, in the stream's frames."""
        return len(self.samples) * FRAMES_PER_SECOND * FRAME_BITS // baud(self.period)

    def to_bytes(self):
        title = self.title.encode("ascii", "replace")[:TITLE_MAX]
        return (MAGIC + bytes((VERSION, self.period, len(title), 0)) + title + self.samples)

    @classmethod
    def from_bytes(cls, data):
        if len(data) < HEADER_SIZE or data[:4] != MAGIC or data[4] != VERSION:
            raise ValueError("not a .pcm file")
        if data[5] not in PERIODS:
            raise ValueError("no sound at %d cycles a bit" % data[5])
        start = HEADER_SIZE + data[6]
        if len(data) < start:
            raise ValueError("truncated .pcm file")
        return cls(data[HEADER_SIZE:start].decode("ascii"), data[5], bytes(data[start:]))
