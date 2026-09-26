"""Read the NES APU register writes out of a VGM or VGZ file.

Only what the jukebox needs is kept: 2A03 register writes with their sample
timestamps, the loop point, the clock (to tell NTSC from PAL rips), and the
GD3 track title. Everything else is walked past and counted, so a rip that
leans on something the jukebox drops (FDS, a second APU, DPCM data blocks)
shows up in the converter's report instead of silently sounding wrong.

Reference: the VGM 1.71 specification. NES APU support arrived in 1.61.
"""

import gzip
import struct
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

SAMPLE_RATE = 44100
NTSC_CLOCK = 1789773
PAL_CLOCK = 1662607

VGM_MAGIC = b"Vgm "
GD3_MAGIC = b"Gd3 "
GZIP_MAGIC = b"\x1f\x8b"

NES_APU_CLOCK = 0x84
NES_FDS_FLAG = 0x80000000
NES_CLOCK_MASK = 0x3FFFFFFF
NES_SECOND_CHIP = 0x80
NES_APU_REGISTERS = 0x20  # $4000-$401F; 0x20 and up are FDS

CMD_NES_APU = 0xB4
CMD_WAIT = 0x61
CMD_WAIT_NTSC = 0x62
CMD_WAIT_PAL = 0x63
CMD_END = 0x66
CMD_DATA_BLOCK = 0x67
CMD_PCM_RAM_WRITE = 0x68


class VgmError(ValueError):
    """The file is not a VGM this converter can read."""


@dataclass(frozen=True)
class ApuWrite:
    sample: int
    register: int  # 0x00-0x1F for $4000-$401F
    value: int


@dataclass
class NesVgm:
    version: int
    clock: int
    fds: bool
    total_samples: int
    loop_start_sample: Optional[int]
    writes: list
    title: str = ""
    game: str = ""
    skipped: Counter = field(default_factory=Counter)

    @property
    def is_pal(self):
        return abs(self.clock - PAL_CLOCK) < abs(self.clock - NTSC_CLOCK)


def load(path):
    with open(path, "rb") as handle:
        return parse(handle.read())


def parse(data):
    if data[:2] == GZIP_MAGIC:
        data = gzip.decompress(data)
    if data[:4] != VGM_MAGIC:
        raise VgmError("not a VGM file")

    def u32(offset):
        if offset + 4 > len(data):
            return 0
        return struct.unpack_from("<I", data, offset)[0]

    version = u32(0x08)
    data_offset = 0x40
    if version >= 0x150 and u32(0x34):
        data_offset = 0x34 + u32(0x34)

    def header(offset):
        # Fields at or past the data offset belong to a newer header layout
        # and read as zero, which the specification requires.
        return u32(offset) if offset + 4 <= data_offset else 0

    clock_field = header(NES_APU_CLOCK) if version >= 0x161 else 0
    clock = clock_field & NES_CLOCK_MASK
    if not clock:
        raise VgmError("no NES APU in this VGM")

    end = len(data)
    if u32(0x04):
        end = min(end, 0x04 + u32(0x04))
    loop_offset = 0x1C + header(0x1C) if header(0x1C) else None

    vgm = NesVgm(
        version=version,
        clock=clock,
        fds=bool(clock_field & NES_FDS_FLAG),
        total_samples=header(0x18),
        loop_start_sample=None,
        writes=[],
    )
    _walk_commands(data, data_offset, end, loop_offset, version, vgm)
    if loop_offset is not None and vgm.loop_start_sample is None:
        raise VgmError("loop offset does not land on a command")
    if header(0x14):
        vgm.title, vgm.game = _read_gd3(data, 0x14 + header(0x14))
    return vgm


def _walk_commands(data, pos, end, loop_offset, version, vgm):
    sample = 0
    while pos < end:
        if pos == loop_offset:
            vgm.loop_start_sample = sample
        cmd = data[pos]
        if cmd == CMD_NES_APU:
            if pos + 3 > end:
                raise VgmError("truncated NES APU write")
            register, value = data[pos + 1], data[pos + 2]
            if register & NES_SECOND_CHIP:
                vgm.skipped["second_apu"] += 1
            elif register >= NES_APU_REGISTERS:
                vgm.skipped["fds"] += 1
            else:
                vgm.writes.append(ApuWrite(sample, register, value))
            pos += 3
        elif cmd == CMD_WAIT:
            sample += struct.unpack_from("<H", data, pos + 1)[0]
            pos += 3
        elif cmd == CMD_WAIT_NTSC:
            sample += 735
            pos += 1
        elif cmd == CMD_WAIT_PAL:
            sample += 882
            pos += 1
        elif 0x70 <= cmd <= 0x7F:
            sample += (cmd & 0x0F) + 1
            pos += 1
        elif 0x80 <= cmd <= 0x8F:
            # YM2612 DAC write from the data bank, then wait n samples.
            sample += cmd & 0x0F
            vgm.skipped["other_chip"] += 1
            pos += 1
        elif cmd == CMD_END:
            return
        elif cmd == CMD_DATA_BLOCK:
            if pos + 7 > end or data[pos + 1] != CMD_END:
                raise VgmError("malformed data block at 0x%X" % pos)
            block_type = data[pos + 2]
            size = struct.unpack_from("<I", data, pos + 3)[0] & 0x7FFFFFFF
            vgm.skipped["data_block_%02X" % block_type] += 1
            pos += 7 + size
        elif cmd == CMD_PCM_RAM_WRITE:
            vgm.skipped["other_chip"] += 1
            pos += 12
        else:
            length = _command_length(cmd, version)
            if length is None:
                raise VgmError("unknown VGM command 0x%02X at 0x%X" % (cmd, pos))
            vgm.skipped["other_chip"] += 1
            pos += length


def _command_length(cmd, version):
    """Total length in bytes of a command this converter only skips."""
    if 0x30 <= cmd <= 0x3F:
        return 2
    if 0x40 <= cmd <= 0x4E:
        return 3 if version >= 0x160 else 2
    if cmd in (0x4F, 0x50):
        return 2
    if 0x51 <= cmd <= 0x5F:
        return 3
    dac_stream = {0x90: 5, 0x91: 5, 0x92: 6, 0x93: 11, 0x94: 2, 0x95: 5}
    if cmd in dac_stream:
        return dac_stream[cmd]
    if 0xA0 <= cmd <= 0xBF:
        return 3
    if 0xC0 <= cmd <= 0xDF:
        return 4
    if 0xE0 <= cmd <= 0xFF:
        return 5
    return None


def _read_gd3(data, offset):
    """Return (track title, game name), English strings, or blanks."""
    if data[offset:offset + 4] != GD3_MAGIC:
        return "", ""
    length = struct.unpack_from("<I", data, offset + 8)[0]
    body = data[offset + 12:offset + 12 + length]
    strings = body.decode("utf-16-le", errors="replace").split("\x00")
    strings += [""] * 3
    return strings[0], strings[2]
