"""Run the player ROM on py65 and record what it writes to the APU.

py65 is a plain 6502, which is all the player needs. The APU is a set of
write-only registers whose writes get recorded per NMI. The PPU is its
address register and its memory, enough to see what the ROM put on the
screen and when, with PPUSTATUS always reporting vblank. Controller 1 is a
shift register loaded from `pad`.

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
PPUADDR = 0x2006
PPUDATA = 0x2007
PPUCTRL_NMI = 0x80
PPUCTRL_DOWN = 0x04
VBLANK_CYCLES = 2273    # 20 scanlines: PPU writes must be over by then
PAD_A, PAD_B, PAD_SELECT, PAD_START = 0x80, 0x40, 0x20, 0x10
PAD_UP, PAD_DOWN, PAD_LEFT, PAD_RIGHT = 0x08, 0x04, 0x02, 0x01
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
        self.memory.subscribe_to_read([PPUSTATUS], self._read_ppustatus)
        self.memory.subscribe_to_write([PPUADDR], self._write_ppuaddr)
        self.memory.subscribe_to_write([PPUDATA], self._write_ppudata)
        self.vram = bytearray(0x4000)
        self.ppu_address = 0
        self.ppu_latch = None       # the high byte, between the two writes
        self.ppu_write_offsets = []  # per NMI: cycles in to its last PPU write
        self._nmi_start = None
        self._last_ppu_write = 0
        self.pad = 0                # buttons held on controller 1 (PAD_*)
        self._pad_shift = 0
        self._strobe = 0
        self.memory.subscribe_to_read([JOY1], self._read_joy1)
        self.memory.subscribe_to_write([JOY1], self._strobe_joy1)
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

    def _read_ppustatus(self, address):
        self.ppu_latch = None
        return VBLANK

    def _write_ppuaddr(self, address, value):
        if self.ppu_latch is None:
            self.ppu_latch = value
        else:
            self.ppu_address = (self.ppu_latch << 8 | value) & 0x3FFF
            self.ppu_latch = None

    def _write_ppudata(self, address, value):
        self.vram[self.ppu_address] = value
        down = self.memory[PPUCTRL] & PPUCTRL_DOWN
        self.ppu_address = (self.ppu_address + (32 if down else 1)) & 0x3FFF
        if self._nmi_start is not None:
            self._last_ppu_write = self.mpu.processorCycles + 3 - self._nmi_start

    def _strobe_joy1(self, address, value):
        self._strobe = value & 1
        if self._strobe:
            self._pad_shift = self.pad

    def _read_joy1(self, address):
        # While the strobe is high the controller keeps loading its buttons
        # and shows the first (A). Low, each read shifts the next one out.
        if self._strobe:
            return 0x40 | (self.pad >> 7)
        bit = self._pad_shift >> 7
        self._pad_shift = (self._pad_shift << 1 | 1) & 0xFF
        return 0x40 | bit

    def screen_text(self, column, row, length):
        """What the nametable shows at a tile position, as text."""
        start = 0x2000 + 32 * row + column
        return bytes(self.vram[start:start + length]).decode("latin-1")

    def nametable(self):
        return bytes(self.vram[0x2000:0x2400])

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
                started = mpu.processorCycles
                self._nmi()
                fired += 1
                # Vblanks come a period apart however long the handler ran,
                # so its time comes out of the frame. The stress tests use
                # periods shorter than the handler; those count from its end,
                # or the main loop would never run.
                step = period()
                next_nmi = started + step
                if next_nmi <= mpu.processorCycles:
                    next_nmi = mpu.processorCycles + step
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
        # An NMI that carries out a flush silences the APU and plays nothing,
        # and neither does one that finds the music paused.
        playing = (bool(self.byte("playing")) and not self.byte("flush_pending")
                   and not self.byte("paused"))
        writes = []
        self._writes = writes
        start = mpu.processorCycles
        self._nmi_start = start
        self._last_ppu_write = 0
        mpu.nmi()
        while True:
            returning = self.memory[mpu.pc] == RTI
            mpu.step()
            if returning:
                break
        self._nmi_start = None
        self.ppu_write_offsets.append(self._last_ppu_write)
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
            if isinstance(item, (jbs.Title, jbs.Game, jbs.Length)):
                continue
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
