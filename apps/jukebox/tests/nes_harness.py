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
JOY1 = 0x4016
JOY2 = 0x4017
RETURN_TRAP = 0xFFF0  # call() returns here
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
        # $4016 is the controller strobe (OUT0), not an APU register.
        apu = [a for a in range(APU, APU_LAST + 1) if a != JOY1]
        self.memory.subscribe_to_write(apu, self._apu_write)
        self.reset_writes = []
        self.frames = []  # per NMI: (writes, underran, playing)
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
            skip_to = self._idle_until(next_nmi)
            if skip_to is not None and skip_to > mpu.processorCycles:
                mpu.processorCycles = skip_to
                continue
            mpu.step()
            if mpu.processorCycles > next_nmi + STALL_CYCLES:
                raise AssertionError("ROM stalled with NMI disabled at $%04X" % mpu.pc)

    def _idle_until(self, next_nmi):
        """A cycle to skip ahead to when the CPU is only spinning, or None.

        main_wait spins until an NMI moves frame_count past served_frame.
        """
        mpu = self.mpu
        if (mpu.pc == self.labels["main_wait"]
                and self.byte("frame_count") == self.byte("served_frame")):
            return next_nmi
        return None

    def call(self, name, a=0, x=0, y=0, limit=200_000):
        """Run one subroutine without booting, NMI off. Returns the MPU."""
        if self.mpu is None:
            self.mpu = MPU(memory=self.memory)
        mpu = self.mpu
        mpu.sp = 0xFD
        self.memory[0x01FE] = (RETURN_TRAP - 1) & 0xFF
        self.memory[0x01FF] = (RETURN_TRAP - 1) >> 8
        mpu.pc = self.labels[name]
        mpu.a, mpu.x, mpu.y = a, x, y
        start = mpu.processorCycles
        while mpu.pc != RETURN_TRAP:
            skip_to = self._idle_until(float("inf"))
            if skip_to is not None and skip_to > mpu.processorCycles:
                mpu.processorCycles = skip_to
            else:
                mpu.step()
            if mpu.processorCycles - start > limit:
                raise AssertionError("%s did not return" % name)
        return mpu

    def _nmi(self):
        mpu = self.mpu
        underruns = self.word("underruns")
        # An NMI that carries out a flush silences the APU and plays nothing.
        playing = bool(self.byte("playing")) and not self.byte("flush_pending")
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
        self.frames.append((writes, self.word("underruns") != underruns, playing))

    def run_until_played(self, count, limit=100_000, **kwargs):
        """Run until count frames have played, however many NMIs it takes."""
        while len(self.played_frames()) < count:
            if len(self.frames) >= limit:
                raise AssertionError("only %d frames played in %d NMIs"
                                     % (len(self.played_frames()), limit))
            self.run(min(100, count), **kwargs)

    def played_frames(self):
        """Writes per NMI, leaving out NMIs before playback started and NMIs
        that found the ring dry."""
        return [writes for writes, underran, playing in self.frames if playing and not underran]


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
        ended = frames and frames[-1][-1:] == [jbs.Control(jbs.CTRL_END)]
        if tail or not ended:
            yield expand(tail + [jbs.Control(jbs.CTRL_END)])
        while True:
            yield []
    loop, _ = jbs.decode(stream, loop_offset)
    while True:
        for frame in loop:
            yield expand(frame)
