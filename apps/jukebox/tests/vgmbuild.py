"""Build small synthetic VGM files so tests never need copyrighted rips."""

import gzip
import struct

NTSC = 1789773
PAL = 1662607
HEADER_SIZE = 0x100


class VgmBuilder:
    def __init__(self, clock=NTSC, version=0x171, fds=False):
        self.clock = clock | (0x80000000 if fds else 0)
        self.version = version
        self.commands = bytearray()
        self.samples = 0
        self.loop_position = None
        self.loop_sample = None

    def write(self, register, value):
        self.commands += bytes([0xB4, register, value])
        return self

    def frame(self, count=1):
        for _ in range(count):
            self.commands.append(0x62)
            self.samples += 735
        return self

    def wait(self, samples):
        while samples:
            step = min(samples, 0xFFFF)
            self.commands += b"\x61" + struct.pack("<H", step)
            self.samples += step
            samples -= step
        return self

    def raw(self, data, samples=0):
        self.commands += data
        self.samples += samples
        return self

    def loop_here(self):
        self.loop_position = len(self.commands)
        self.loop_sample = self.samples
        return self

    def build(self, title="", game="", compress=False):
        header = bytearray(HEADER_SIZE)
        body = bytes(self.commands) + b"\x66"
        gd3 = _gd3(title, game)
        total = HEADER_SIZE + len(body) + len(gd3)
        header[0:4] = b"Vgm "
        struct.pack_into("<I", header, 0x04, total - 0x04)
        struct.pack_into("<I", header, 0x08, self.version)
        struct.pack_into("<I", header, 0x14, HEADER_SIZE + len(body) - 0x14)
        struct.pack_into("<I", header, 0x18, self.samples)
        if self.loop_position is not None:
            struct.pack_into("<I", header, 0x1C, HEADER_SIZE + self.loop_position - 0x1C)
            struct.pack_into("<I", header, 0x20, self.samples - self.loop_sample)
        struct.pack_into("<I", header, 0x24, 60)
        struct.pack_into("<I", header, 0x34, HEADER_SIZE - 0x34)
        struct.pack_into("<I", header, 0x84, self.clock)
        data = bytes(header) + body + gd3
        return gzip.compress(data) if compress else data


def _gd3(title, game):
    strings = [title, "", game, "", "NES", "", "", "", "", "", ""]
    text = "".join(s + "\x00" for s in strings).encode("utf-16-le")
    return b"Gd3 " + struct.pack("<II", 0x100, len(text)) + text
