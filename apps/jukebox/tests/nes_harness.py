"""Run the player ROM on py65 and record what it writes to the APU.

py65 is a plain 6502, which is all the player needs: there is no PPU beyond
PPUSTATUS always reporting vblank, and the APU is a set of write-only
registers whose writes get recorded per NMI.

The emulated clock fires an NMI every NTSC frame (29781 cycles) while the ROM
has NMI enabled, or at random intervals to stress the ring buffer handoff.
Whenever the CPU sits at main_wait with nothing to do, the clock skips ahead
to the next NMI, which is what keeps whole songs fast enough to test.
"""

from py65.devices.mpu6502 import MPU
from py65.memory import ObservableMemory

import jbs

NTSC_FRAME_CYCLES = 29781
PRG_START = 0x8000
PRG_SIZE = 0x8000
INES_HEADER = 16
PPUCTRL = 0x2000
PPUSTATUS = 0x2002
PPUCTRL_NMI = 0x80
APU = 0x4000
APU_LAST = 0x4017
RTI = 0x40
VBLANK = 0x80
STALL_CYCLES = 10 * NTSC_FRAME_CYCLES


def load_labels(path):
    labels = {}
    with open(path) as handle:
        for line in handle:
            _, address, name = line.split()
            labels[name.lstrip(".")] = int(address, 16)
    return labels


class Console:
    def __init__(self, rom_path, labels_path):
        with open(rom_path, "rb") as handle:
            rom = handle.read()
        self.labels = load_labels(labels_path)
        self.memory = ObservableMemory()
        for offset, byte in enumerate(rom[INES_HEADER:INES_HEADER + PRG_SIZE]):
            self.memory[PRG_START + offset] = byte
        self.memory.subscribe_to_read([PPUSTATUS], lambda address: VBLANK)
        self.memory.subscribe_to_write(range(APU, APU_LAST + 1), self._apu_write)
        self.reset_writes = []
        self.frames = []  # per NMI: (writes, underran)
        self._writes = self.reset_writes
        self.nmi_cycles = []
        self.mpu = None

    def _apu_write(self, address, value):
        self._writes.append((address - APU, value))

    def load_song(self, stream, loop_offset=None):
        """Point the song descriptor at another stream, as embed_song would."""
        data = bytes(stream)
        if loop_offset is None:
            data += bytes([jbs.OP_CONTROL, jbs.CTRL_END])
        start = self.labels["song_data"]
        for offset, byte in enumerate(data):
            self.memory[start + offset] = byte
        desc = self.labels["song_desc"]
        loop = start + (loop_offset or 0)
        for offset, word in enumerate((start, start + len(data), loop)):
            self.memory[desc + 2 * offset] = word & 0xFF
            self.memory[desc + 2 * offset + 1] = word >> 8
        self.memory[desc + 6] = int(loop_offset is not None)

    def byte(self, name, offset=0):
        return self.memory[self.labels[name] + offset]

    def word(self, name):
        return self.byte(name) | self.byte(name, 1) << 8

    def run(self, nmis, period=lambda: NTSC_FRAME_CYCLES, interrupt_at=()):
        """Boot (first call only) and run until nmis more NMIs have fired.

        interrupt_at names labels where an NMI fires as well, every time the
        CPU reaches one, to hit windows a clock would almost never land in.
        """
        targets = {self.labels[name] for name in interrupt_at}
        returned_to = None
        if self.mpu is None:
            self.mpu = MPU(memory=self.memory)
            self.mpu.pc = self.memory[0xFFFC] | self.memory[0xFFFD] << 8
        mpu = self.mpu
        main_wait = self.labels["main_wait"]
        frame_count = self.labels["frame_count"]
        next_nmi = mpu.processorCycles + period()
        fired = 0
        while fired < nmis:
            enabled = self.memory[PPUCTRL] & PPUCTRL_NMI
            if enabled and mpu.pc in targets and mpu.pc != returned_to:
                self._nmi()
                fired += 1
                returned_to = mpu.pc  # don't fire again before moving on
                continue
            if mpu.processorCycles >= next_nmi and enabled:
                self._nmi()
                fired += 1
                next_nmi = mpu.processorCycles + period()
                returned_to = mpu.pc
                continue
            returned_to = None
            # main_wait spins on "cmp frame_count" until an NMI changes it.
            idle = mpu.pc == main_wait and mpu.a == self.memory[frame_count]
            if idle and mpu.processorCycles < next_nmi:
                mpu.processorCycles = next_nmi
                continue
            mpu.step()
            if mpu.processorCycles > next_nmi + STALL_CYCLES:
                raise AssertionError("ROM stalled with NMI disabled at $%04X" % mpu.pc)

    def _nmi(self):
        mpu = self.mpu
        underruns = self.word("underruns")
        writes = []
        self._writes = writes
        start = mpu.processorCycles
        mpu.nmi()
        while True:
            returning = self.memory[mpu.pc] == RTI
            mpu.step()
            if returning:
                break
        self.nmi_cycles.append(mpu.processorCycles - start)
        self._writes = []
        self.frames.append((writes, self.word("underruns") != underruns))

    def played_frames(self):
        """Writes per NMI, leaving out the NMIs that found the ring dry."""
        return [writes for writes, underran in self.frames if not underran]


def expected_frames(stream, loop_offset=None):
    """What the player should write, frame by frame, according to the Python
    decoder. Yields forever: the loop repeats, or silence after the end."""
    init = [(0x15, 0x00), (0x17, 0x40)]
    end = [(0x15, 0x00)]

    def expand(frame):
        writes = []
        for item in frame:
            if item == jbs.Control(jbs.CTRL_INIT):
                writes += init
            elif item == jbs.Control(jbs.CTRL_END):
                writes += end
            else:
                writes.append(item)
        return writes

    frames, tail = jbs.decode(stream)
    for frame in frames:
        yield expand(frame)
    if loop_offset is None:
        yield expand(tail + [jbs.Control(jbs.CTRL_END)])
        while True:
            yield []
    loop, _ = jbs.decode(stream, loop_offset)
    while True:
        for frame in loop:
            yield expand(frame)
