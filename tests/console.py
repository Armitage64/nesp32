"""A ROM on py65, with as much of an NES round it as the setup ROM uses.

py65 is a plain 6502. This adds:

- A frame clock. A vblank comes every 29780.5 CPU cycles, and with it an
  NMI if the ROM has them on. The handler runs to its rti in one go.
- The PPU's address register and its data port, a nametable with its
  attributes, the palette, OAM filled by the DMA at $4014, and controller 1
  as a shift register loaded from `pad`.
- Controller port 2 as the link's line (wire.py): what a read of $4017
  sees on the cycle it looks, and where the writes to OUT0 go.

It is nes-wiki's (tests/console.py), less the split screen that ROM has
and this one does not.

Time is in CPU cycles. Loops that only pass time are skipped rather than
stepped, with the cycles they would have used: main_wait until the next
vblank, and the serial receiver's hunt for a start bit while the line
rests.
"""

from py65.devices.mpu6502 import MPU
from py65.memory import ObservableMemory

FRAME_CYCLES = 29780.5
VBLANK_CYCLES = 20 * 341 / 3    # 2273: an NMI's PPU writes must be over by then
PRG_START = 0x8000
PRG_SIZE = 0x8000
INES_HEADER = 16
CHR_SIZE = 0x2000

PPUCTRL, PPUMASK, PPUSTATUS, OAMADDR = 0x2000, 0x2001, 0x2002, 0x2003
PPUSCROLL, PPUADDR, PPUDATA = 0x2005, 0x2006, 0x2007
OAMDMA, JOY1, JOY2 = 0x4014, 0x4016, 0x4017
PPUCTRL_NMI = 0x80
RENDERING = 0x18                # background and sprites both on
VBLANK_FLAG = 0x80
DMA_CYCLES = 513
RTI = 0x40
RETURN_TRAP = 0x00F0            # where call() has a subroutine return to
SPRITE_HIDDEN = 0xEF            # a sprite at this Y or below is off the picture

PAD_A, PAD_B, PAD_SELECT, PAD_START = 0x80, 0x40, 0x20, 0x10
PAD_UP, PAD_DOWN, PAD_LEFT, PAD_RIGHT = 0x08, 0x04, 0x02, 0x01

# The serial receivers' waits for a start bit (nes/lib/gen_link.py), as
# (code, cycles a look). The first has no count; the second counts its
# looks in X and gives up, so only whole looks short of X running out are
# skipped.
HUNT = (bytes((0xAD, 0x17, 0x40, 0x4A, 0x90, 0xFA)), 9)             # lda / lsr / bcc
HUNT_TIMEOUT = (bytes((0xAD, 0x17, 0x40, 0x4A, 0xB0)), 13)          # lda / lsr / bcs ..
READS_ABS = (0xAD,)             # lda: reads on its 4th cycle
STORES_ABS = (0x8D,)            # sta: writes on its 4th
STALL_FRAMES = 4


def load_labels(path):
    labels = {}
    with open(path) as handle:
        for line in handle:
            _, address, name = line.split()
            labels[name.lstrip(".")] = int(address, 16)
    return labels


class Frame:
    """What one frame did, from the vblank that began it to the next."""

    def __init__(self, start):
        self.start = start
        self.nmi_cycles = 0         # the handler's length; 0 if no NMI fired
        self.last_write = 0         # cycles after the vblank of its last PPU write
        self.pad = 0


class Console:
    def __init__(self, rom_path, labels_path, nmi_delay=0):
        with open(rom_path, "rb") as handle:
            rom = handle.read()
        self.labels = load_labels(labels_path)
        self.prg = bytes(rom[INES_HEADER:INES_HEADER + PRG_SIZE])
        self.chr = bytes(rom[INES_HEADER + PRG_SIZE:INES_HEADER + PRG_SIZE + CHR_SIZE])
        self.memory = ObservableMemory()
        for offset, byte in enumerate(self.prg):
            self.memory[PRG_START + offset] = byte
        self.nmi_delay = nmi_delay  # holds every NMI back, to try other phases
        self.vram = bytearray(0x4000)
        self.oam = bytearray(256)
        self.ctrl = self.mask = 0
        self.v = self.w = self._high = 0
        self.vblank_unread = False
        self.pad = 0
        self._pad_shift = 0
        self._strobe = 0
        self.frames = []
        self.frame = Frame(0.0)     # the time before the first vblank
        self.next_vblank = FRAME_CYCLES
        self.in_nmi = False
        # The serial line (wire.py): the level of D0 at a cycle, when it
        # next leaves mark, and where OUT0's writes go.
        self.joy2_level = None
        self.joy2_quiet_until = None
        self.on_joy1 = None
        self.joy2_reads = None      # set to a list to record (cycle, pc, level)
        self.joy1_writes = None     # set to a list to record (cycle, bit 0)
        self.host = None            # called every host_every cycles
        self.host_every = 0
        self._host_at = 0
        memory = self.memory
        memory.subscribe_to_write([PPUCTRL], self._write_ctrl)
        memory.subscribe_to_write([PPUMASK], self._write_mask)
        memory.subscribe_to_read([PPUSTATUS], self._read_status)
        memory.subscribe_to_write([PPUADDR], self._write_addr)
        memory.subscribe_to_write([PPUDATA], self._write_data)
        memory.subscribe_to_write([OAMDMA], self._write_dma)
        memory.subscribe_to_read([JOY1], self._read_joy1)
        memory.subscribe_to_write([JOY1], self._write_joy1)
        memory.subscribe_to_read([JOY2], self._read_joy2)
        self.mpu = MPU(memory=memory)
        self.mpu.pc = memory[0xFFFC] | memory[0xFFFD] << 8

    @property
    def now(self):
        return self.mpu.processorCycles

    # --- PPU registers ---------------------------------------------------------

    def _write_ctrl(self, address, value):
        self.ctrl = value

    def _write_mask(self, address, value):
        self.mask = value

    def _read_status(self, address):
        value = 0
        if self.vblank_unread and self.now + 3 < self.frame.start + VBLANK_CYCLES:
            value |= VBLANK_FLAG
        self.vblank_unread = False
        self.w = 0
        return value

    def _write_addr(self, address, value):
        if self.w == 0:
            self._high = value & 0x3F
        else:
            self.v = self._high << 8 | value
        self.w ^= 1

    @staticmethod
    def _mirror(address):
        address &= 0x3FFF
        if 0x2800 <= address < 0x3000:      # vertical mirroring
            address -= 0x800
        if 0x3F00 <= address:               # the palette, every 32 bytes
            address = 0x3F00 | (address & 0x1F)
        return address

    def _write_data(self, address, value):
        if self.in_nmi:
            self.frame.last_write = self.now + 3 - self.frame.start
        elif self.mask & RENDERING:
            raise AssertionError("PPUDATA written outside the NMI with rendering on")
        self.vram[self._mirror(self.v)] = value
        self.v = (self.v + (32 if self.ctrl & 0x04 else 1)) & 0x7FFF

    def _write_dma(self, address, value):
        for offset in range(256):
            self.oam[offset] = self.memory[value << 8 | offset]
        self.mpu.processorCycles += DMA_CYCLES

    # --- the picture -----------------------------------------------------------

    def tiles(self, row, column, length):
        start = 0x2000 + 32 * row + column
        return bytes(self.vram[start:start + length])

    def text(self, row, column=0, length=32):
        """A row's tiles as text, with the second colour's bit taken off.
        A tile that is not a character shows as '^'."""
        out = []
        for tile in self.tiles(row, column, length):
            code = tile & 0x7F
            out.append(chr(code) if 0x20 <= code < 0x7F else " " if tile == 0 else "^")
        return "".join(out)

    def line(self, row):
        """A row's text, without the blank at either end."""
        return self.text(row).strip()

    def screen(self):
        """The whole picture as text, a line a row."""
        return "\n".join(self.text(row).rstrip() for row in range(30))

    def sprite(self, index=0):
        """(x, y, tile) of a sprite as the picture shows it, or None if it
        is off the picture."""
        y, tile, _, x = self.oam[4 * index:4 * index + 4]
        if y >= SPRITE_HIDDEN:
            return None
        return x, y + 1, tile

    # --- the controller --------------------------------------------------------

    def _read_joy2(self, address):
        # Port 2 with nothing but the link on it: bit 0 is D0 inverted, and
        # the rest is what the bus last held, the $40 of the address.
        mpu = self.mpu
        if self.memory[mpu.pc - 1] not in READS_ABS:
            raise AssertionError("$4017 read by opcode $%02X" % self.memory[mpu.pc - 1])
        cycle = mpu.processorCycles + 3
        level = self.joy2_level(cycle) if self.joy2_level is not None else 1
        if self.joy2_reads is not None:
            self.joy2_reads.append((cycle, mpu.pc - 1, level))
        return 0x40 | (level ^ 1)

    def _write_joy1(self, address, value):
        mpu = self.mpu
        if self.memory[mpu.pc - 1] not in STORES_ABS:
            raise AssertionError("$4016 written by opcode $%02X" % self.memory[mpu.pc - 1])
        if self.joy1_writes is not None:
            self.joy1_writes.append((self.now + 3, value & 1))
        if self.on_joy1 is not None:
            self.on_joy1(self.now + 3, value & 1)
        # While OUT0 is high the controller keeps loading its buttons, so
        # what it shifts out is what was held when OUT0 fell.
        if self._strobe or value & 1:
            self._pad_shift = self.pad
        self._strobe = value & 1

    def _read_joy1(self, address):
        if self._strobe:
            return 0x40 | (self.pad >> 7)
        bit = self._pad_shift >> 7
        self._pad_shift = (self._pad_shift << 1 | 1) & 0xFF
        return 0x40 | bit

    # --- memory ----------------------------------------------------------------

    def byte(self, name, offset=0):
        return self.memory[self.labels[name] + offset]

    def word(self, name):
        return self.byte(name) | self.byte(name, 1) << 8

    def data(self, name, length):
        start = self.labels[name]
        return bytes(self.memory[start:start + length])

    # --- running ---------------------------------------------------------------

    def run(self, frames=1, pad=None):
        """Run until this many more vblanks have passed. `pad` sets the
        buttons held from now on."""
        if pad is not None:
            self.pad = pad
        target = len(self.frames) + frames
        mpu = self.mpu
        nmi_off_since = None
        while len(self.frames) < target:
            if mpu.processorCycles >= self.next_vblank:
                self._vblank()
                if self.ctrl & PPUCTRL_NMI:
                    nmi_off_since = None
                elif nmi_off_since is None:
                    nmi_off_since = len(self.frames)
                elif len(self.frames) - nmi_off_since > STALL_FRAMES:
                    raise AssertionError("the ROM ran %d frames with the NMI off"
                                         % STALL_FRAMES)
                continue
            if self.host is not None and mpu.processorCycles >= self._host_at:
                self._host_at = mpu.processorCycles + self.host_every
                self.host()
            if not self._skip():
                mpu.step()

    def press(self, buttons, frames=2, release=2):
        """Hold buttons for some frames, then let go for some."""
        self.run(frames, pad=buttons)
        self.run(release, pad=0)

    def run_until(self, condition, frames=600):
        """Run a frame at a time until condition() is true. Returns how many
        frames that took; raises if it never is."""
        for count in range(frames):
            if condition():
                return count
            self.run(1)
        raise AssertionError("still waiting after %d frames:\n%s" % (frames, self.screen()))

    def call(self, name, a=0, x=0, y=0, limit=2_000_000):
        """Run one subroutine from a fresh stack, with no vblanks. Returns
        the MPU."""
        mpu = self.mpu
        mpu.sp = 0xFD
        self.memory[0x01FE] = (RETURN_TRAP - 1) & 0xFF
        self.memory[0x01FF] = (RETURN_TRAP - 1) >> 8
        mpu.pc = self.labels[name]
        mpu.a, mpu.x, mpu.y = a, x, y
        start = mpu.processorCycles
        self.next_vblank = float("inf")
        while mpu.pc != RETURN_TRAP:
            if not self._skip():
                mpu.step()
            if mpu.processorCycles - start > limit:
                raise AssertionError("%s did not return" % name)
        return mpu

    def _vblank(self):
        mpu = self.mpu
        self.frame.pad = self.pad
        self.frames.append(self.frame)
        self.frame = Frame(self.next_vblank)
        self.next_vblank += FRAME_CYCLES
        self.vblank_unread = True
        if not self.ctrl & PPUCTRL_NMI:
            return
        mpu.processorCycles += self.nmi_delay
        started = mpu.processorCycles
        self.in_nmi = True
        mpu.nmi()
        while True:
            returning = self.memory[mpu.pc] == RTI
            mpu.step()
            if returning:
                break
        self.in_nmi = False
        self.frame.nmi_cycles = mpu.processorCycles - started

    def _skip(self):
        """Jump over a loop that only passes time. True if it did."""
        mpu = self.mpu
        pc = mpu.pc
        if (pc == self.labels.get("main_wait")
                and self.byte("frame_count") == self.byte("served_frame")
                and self.ctrl & PPUCTRL_NMI):
            mpu.processorCycles = max(mpu.processorCycles, int(self.next_vblank) + 1)
            return True
        if pc < PRG_START or self.joy2_quiet_until is None:
            return False
        offset = pc - PRG_START
        for code, cycles in (HUNT, HUNT_TIMEOUT):
            if self.prg[offset:offset + len(code)] != code:
                continue
            # Whole passes of the hunt while the line rests at mark, so its
            # phase against the next start bit is kept.
            quiet = self.joy2_quiet_until(mpu.processorCycles)
            if quiet is None:
                return False
            limit = min(quiet, self.next_vblank, self._host_at)
            passes = int((limit - mpu.processorCycles - 2 * cycles) // cycles)
            if code is HUNT_TIMEOUT[0]:
                # Its count of looks must not run out in the skip: X counts
                # down, and a 0 is the last look of a pass of 256.
                passes = min(passes, (mpu.x - 1) & 0xFF)
            if passes <= 0:
                return False
            mpu.processorCycles += passes * cycles
            if code is HUNT_TIMEOUT[0]:
                mpu.x = (mpu.x - passes) & 0xFF
            return True
        return False
