"""Sampled sound on the Stick (docs/PROTOCOL.md, part 4).

What the Stick needs of tools/pcm.py, which makes the .pcm files:
tests/test_stick.py holds the two together. A file is already what goes on
the wire, a byte a sample, so the Stick only copies it to the UART at the
file's baud rate and ends it with LAST_BYTE.

    "NPCM", version (1), cycles a bit, title length n, 0, title, samples
"""

import os

CPU_HZ = 1789773
PERIODS = (21, 16, 14, 12, 10, 8)   # cycles a bit; the console is told the index
FRAME_BITS = 11                 # a start bit, 8 data bits, 2 stop bits
FRAMES_PER_SECOND = 60

MAGIC = b"NPCM"
VERSION = 1
HEADER_SIZE = 8

LAST_BYTE = b"\xfc"             # ends a stream, leaving the console's DAC at 0
FILLER = bytes(4)               # at 38400 baud: ends a stream a console was left in
CHUNK = 512                     # bytes read from flash and handed to the UART at a time


def baud(period):
    return (CPU_HZ + period // 2) // period


class Sound:
    """A sound track on flash: where its samples are, and their rate."""

    def __init__(self, path, period, start, count):
        self.path = path
        self.period = period
        self.rate = PERIODS.index(period)
        self.start = start      # of the samples, in the file
        self.count = count      # samples


def load(path):
    """Return (title, Sound) for a .pcm file, reading only its header."""
    with open(path, "rb") as handle:
        header = handle.read(HEADER_SIZE)
        if len(header) < HEADER_SIZE or header[:4] != MAGIC or header[4] != VERSION:
            raise ValueError("not a .pcm file: " + path)
        if header[5] not in PERIODS:
            raise ValueError("no sound at %d cycles a bit: %s" % (header[5], path))
        title = str(handle.read(header[6]), "ascii")
    start = HEADER_SIZE + header[6]
    return title, Sound(path, header[5], start, os.stat(path)[6] - start)


def frames(sound):
    """How long a sound plays, in the stream's frames."""
    return sound.count * FRAMES_PER_SECOND * FRAME_BITS // baud(sound.period)


def send(uart, handle, stop=None):
    """Copy samples from a file, already at its first, to the UART, and end
    the stream. uart.write waits while the UART's buffer is full, so the
    UART sets the pace. stop, if given, is asked after each chunk and ends
    the sound early by returning true. Returns the samples sent."""
    buffer = bytearray(CHUNK)
    view = memoryview(buffer)
    sent = 0
    while True:
        count = handle.readinto(buffer)
        if not count:
            break
        uart.write(view[:count])
        sent += count
        if stop is not None and stop():
            break
    uart.write(LAST_BYTE)
    return sent
