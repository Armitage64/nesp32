"""NESpedia's ROM on py65, with as much of an NES round it as the ROM uses.

py65 is a plain 6502. This adds:

- A frame clock. A vblank comes every 29780.5 CPU cycles, and with it an
  NMI if the ROM has them on. The handler runs to its rti in one go.
- PPUSTATUS as the ROM polls it: the vblank flag, and the sprite 0 hit,
  which rises at the dot where sprite 0's pixel is drawn (if rendering is
  on and there is a lit background pixel under it) and stands until the
  pre-render line.
- The PPU's address and scroll registers with their shared latch (t, v, w),
  so what a frame shows can be worked out from the writes the ROM made:
  the scroll at the top of the frame, and the one the split's last write
  put in mid-frame, with the dot it landed on.
- Nametables with vertical mirroring, OAM filled by the DMA at $4014, and
  controller 1 as a shift register loaded from `pad`.

Time is in CPU cycles; a dot is a third of one. Dots are counted from the
vblank, which is taken to start at dot 0 of scanline 241, so scanline n of
the picture starts (21 + n) * 341 dots later.

Loops that only pass time are skipped rather than stepped, with the cycles
and the counts they would have used: main_wait until the next vblank, the
split's two waits on PPUSTATUS, and its delay loop. skip_waits = False
steps the split's loops instead, to check that skipping changes nothing.

On a console the phase between the ROM's polling and the picture is
whatever it happens to be. Here it would be the same every frame, so
nmi_delay holds every NMI back by that many cycles to try the others.
"""

from py65.devices.mpu6502 import MPU
from py65.memory import ObservableMemory

FRAME_CYCLES = 29780.5
DOTS_PER_LINE = 341
VBLANK_LINES = 20
FIRST_LINE = VBLANK_LINES + 1   # scanlines from the vblank to the picture's first
VBLANK_CYCLES = VBLANK_LINES * DOTS_PER_LINE / 3    # 2273: PPU writes must be over
PRG_START = 0x8000
PRG_SIZE = 0x8000
INES_HEADER = 16
CHR_SIZE = 0x2000

PPUCTRL, PPUMASK, PPUSTATUS, OAMADDR = 0x2000, 0x2001, 0x2002, 0x2003
PPUSCROLL, PPUADDR, PPUDATA = 0x2005, 0x2006, 0x2007
OAMDMA, JOY1, JOY2 = 0x4014, 0x4016, 0x4017
PPUCTRL_NMI, PPUCTRL_DOWN = 0x80, 0x04
RENDERING = 0x18                # background and sprites both on
VBLANK_FLAG, HIT_FLAG = 0x80, 0x40
DMA_CYCLES = 513
RTI = 0x40
RETURN_TRAP = 0xFFF0

PAD_A, PAD_B, PAD_SELECT, PAD_START = 0x80, 0x40, 0x20, 0x10
PAD_UP, PAD_DOWN, PAD_LEFT, PAD_RIGHT = 0x08, 0x04, 0x02, 0x01

# bit $2002, then the branch that leaves each of the split's waits.
WAIT_CLEAR = bytes((0x2C, 0x02, 0x20, 0x50))    # bvc: until the hit flag is clear
WAIT_HIT = bytes((0x2C, 0x02, 0x20, 0x70))      # bvs: until it is set
WAIT_LOOK = 11                  # cycles from one look to the next
WAIT_WRAP = 4                   # more, every 256th look
DELAY_LOOP = bytes((0xCA, 0xD0, 0xFD))          # dex / bne
DELAY_CYCLES = 5
# The serial receiver's wait for a start bit: lda $4017 / lsr / bcc.
HUNT = bytes((0xAD, 0x17, 0x40, 0x4A, 0x90, 0xFA))
HUNT_CYCLES = 9
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
    """What one frame showed, from the vblank that began it to the next."""

    def __init__(self, start):
        self.start = start
        self.nmi_cycles = 0         # the handler's length; 0 if no NMI fired
        self.vblank_writes = []     # nametable addresses written in the NMI
        self.last_write = 0         # cycles after the vblank of the last of them
        self.header = None          # t when the picture began: the top's scroll
        self.hit_at = None          # cycle the sprite 0 flag rose
        self.split = None           # v the split's last write set
        self.split_line = None      # the scanline and dot it landed on
        self.split_dot = None
        self.top = None             # the ROM's `top` and `fine` at the split
        self.fine = None
        self.lines = None           # the article's lines in view: Console.window
        self.pad = 0

    @property
    def header_nametable(self):
        return (self.header >> 10) & 3

    @property
    def split_y(self):
        """The article's scroll the split set: 0-239 down its nametable."""
        return ((self.split >> 5) & 0x1F) * 8 + ((self.split >> 12) & 7)


class Console:
    def __init__(self, rom_path, labels_path, skip_waits=True, nmi_delay=0):
        with open(rom_path, "rb") as handle:
            rom = handle.read()
        self.labels = load_labels(labels_path)
        self.prg = bytes(rom[INES_HEADER:INES_HEADER + PRG_SIZE])
        self.chr = bytes(rom[INES_HEADER + PRG_SIZE:INES_HEADER + PRG_SIZE + CHR_SIZE])
        self.memory = ObservableMemory()
        for offset, byte in enumerate(self.prg):
            self.memory[PRG_START + offset] = byte
        self.skip_waits = skip_waits
        self.nmi_delay = nmi_delay
        self.vram = bytearray(0x4000)
        self.oam = bytearray(256)
        self.ctrl = self.mask = 0
        self.t = self.v = self.w = 0
        self.vblank_unread = False
        self.pad = 0
        self._pad_shift = 0
        self._strobe = 0
        self.frames = []
        self.frame = Frame(0.0)     # the time before the first vblank
        self.next_vblank = FRAME_CYCLES
        self.in_nmi = False
        self.on_line = None         # called at link_line; True makes it fail
        # The link ROM's serial line (wire.py): the level of D0 at a cycle,
        # when it next leaves mark, and where OUT0's writes go.
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
        memory.subscribe_to_write([PPUSCROLL], self._write_scroll)
        memory.subscribe_to_write([PPUADDR], self._write_addr)
        memory.subscribe_to_write([PPUDATA], self._write_data)
        memory.subscribe_to_write([OAMDMA], self._write_dma)
        memory.subscribe_to_read([JOY1], self._read_joy1)
        memory.subscribe_to_write([JOY1], self._write_joy1)
        memory.subscribe_to_read([JOY2], self._read_joy2)
        self.mpu = MPU(memory=memory)
        self.mpu.pc = memory[0xFFFC] | memory[0xFFFD] << 8

    # --- time ------------------------------------------------------------------

    @property
    def now(self):
        return self.mpu.processorCycles

    def _dots(self, cycle):
        """Dots from this frame's vblank to a cycle."""
        return (cycle - self.frame.start) * 3

    def _picture_began(self, cycle):
        return self._dots(cycle) >= FIRST_LINE * DOTS_PER_LINE

    def _hit_cycle(self):
        """When sprite 0 is hit in this frame, or None if it is not."""
        if self.mask & RENDERING != RENDERING:
            return None
        y, tile, _, x = self.oam[0:4]
        line = y + 1
        if line >= 240 or x >= 255:
            return None
        if not self._tile_pixel(tile, 0, 0):
            return None             # the tests' sprite 0 is its top left pixel
        header = self.frame.header if self.frame.header is not None else self.t
        if not self.background_pixel(header, x, line):
            return None
        return self.frame.start + ((FIRST_LINE + line) * DOTS_PER_LINE + x + 2) / 3

    def _hit_clears(self):
        """The pre-render line of the next frame, where the hit flag falls."""
        return self.next_vblank + VBLANK_CYCLES

    # --- PPU registers ---------------------------------------------------------

    def _mark_header(self, cycle):
        if self.frame.header is None and self._picture_began(cycle):
            self.frame.header = self.t

    def _write_ctrl(self, address, value):
        self._mark_header(self.now + 3)
        self.ctrl = value
        self.t = (self.t & ~0x0C00) | (value & 3) << 10

    def _write_mask(self, address, value):
        self.mask = value

    def _read_status(self, address):
        cycle = self.now + 3
        value = 0
        if self.vblank_unread and cycle < self.frame.start + VBLANK_CYCLES:
            value |= VBLANK_FLAG
        self.vblank_unread = False
        # The hit of the frame before stands through this frame's vblank.
        previous = self.frames[-1] if self.frames else None
        if (previous is not None and previous.hit_at is not None
                and cycle < self.frame.start + VBLANK_CYCLES):
            value |= HIT_FLAG
        hit = self._hit_cycle()
        if hit is not None and cycle >= hit:
            self.frame.hit_at = hit
            value |= HIT_FLAG
        self.w = 0
        return value

    def _write_scroll(self, address, value):
        self._mark_header(self.now + 3)
        if self.w == 0:
            self.t = (self.t & ~0x001F) | value >> 3
        else:
            self.t = (self.t & ~0x73E0) | (value & 7) << 12 | (value >> 3) << 5
        self.w ^= 1

    def _write_addr(self, address, value):
        cycle = self.now + 3
        self._mark_header(cycle)
        if self.w == 0:
            self.t = (self.t & 0x00FF) | (value & 0x3F) << 8
        else:
            self.t = (self.t & 0x7F00) | value
            self.v = self.t
            if not self.in_nmi and self._picture_began(cycle):
                dots = int(self._dots(cycle))
                self.frame.split = self.v
                self.frame.split_line = dots // DOTS_PER_LINE - FIRST_LINE
                self.frame.split_dot = dots % DOTS_PER_LINE
                self.frame.top = self.word("top")
                self.frame.fine = self.byte("fine")
        self.w ^= 1

    @staticmethod
    def _mirror(address):
        address &= 0x3FFF
        if 0x2800 <= address < 0x3000:      # vertical mirroring
            address -= 0x800
        return address

    def _write_data(self, address, value):
        target = self._mirror(self.v)
        self.vram[target] = value
        if self.in_nmi:
            self.frame.vblank_writes.append(target)
            self.frame.last_write = self.now + 3 - self.frame.start
        elif self.mask & RENDERING:
            raise AssertionError("PPUDATA written outside the NMI with rendering on")
        self.v = (self.v + (32 if self.ctrl & PPUCTRL_DOWN else 1)) & 0x7FFF

    def _write_dma(self, address, value):
        for offset in range(256):
            self.oam[offset] = self.memory[value << 8 | offset]
        self.mpu.processorCycles += DMA_CYCLES

    # --- the picture -----------------------------------------------------------

    def _tile_pixel(self, tile, x, y):
        planes = self.chr[tile * 16:tile * 16 + 16]
        return ((planes[y] >> (7 - x)) & 1) | (((planes[8 + y] >> (7 - x)) & 1) << 1)

    def background_pixel(self, scroll, x, y):
        """The colour (0-3) at a screen position, given the scroll (t or v)
        the frame began with. X scroll is taken as 0, which it always is."""
        row = ((scroll >> 5) & 0x1F) * 8 + ((scroll >> 12) & 7) + y
        table = (scroll >> 10) & 3
        if row >= 240:
            row -= 240
            table ^= 2
        address = self._mirror(0x2000 + 0x400 * table + 32 * (row // 8) + x // 8)
        return self._tile_pixel(self.vram[address], x % 8, row % 8)

    def nametable(self, index):
        start = 0x2000 + 0x400 * index
        return bytes(self.vram[start:start + 0x400])

    def tiles(self, table, row, column, length):
        start = 0x2000 + 0x400 * table + 32 * row + column
        return bytes(self.vram[start:start + length])

    def text(self, table, row, column, length):
        """Tiles as text, with the second colour's bit taken off."""
        return bytes(tile & 0x7F for tile in self.tiles(table, row, column, length)).decode("ascii")

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
        # While the strobe is high the controller keeps loading its buttons
        # and shows the first (A). Low, each read shifts the next one out.
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

    def load_article(self, lines):
        """Replace the built-in article (the standalone ROM only): lines of
        exactly 28 tile numbers each."""
        start = self.labels["article_data"]
        for index, line in enumerate(lines):
            assert len(line) == 28
            for offset, byte in enumerate(line):
                self.memory[start + 28 * index + offset] = byte
        desc = self.labels["article_desc"]
        self.memory[desc + 2] = len(lines) & 0xFF
        self.memory[desc + 3] = len(lines) >> 8

    # --- running ---------------------------------------------------------------

    def run(self, frames=1, pad=None):
        """Run until this many more vblanks have passed. `pad` sets the
        buttons held from now on."""
        if pad is not None:
            self.pad = pad
        target = len(self.frames) + frames
        mpu = self.mpu
        stalled_at = len(self.frames)
        while len(self.frames) < target:
            if mpu.processorCycles >= self.next_vblank:
                self._vblank()
                continue
            if self.host is not None and mpu.processorCycles >= self._host_at:
                self._host_at = mpu.processorCycles + self.host_every
                self.host()
            if self._skip():
                continue
            if self.on_line is not None and mpu.pc == self.labels["link_line"]:
                if self.on_line(self):
                    self._return(carry=True)
                    continue
            mpu.step()
            if len(self.frames) - stalled_at > STALL_FRAMES and not self.ctrl & PPUCTRL_NMI:
                raise AssertionError("the ROM ran %d frames with the NMI off" % STALL_FRAMES)

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

    def _return(self, carry):
        """Leave the subroutine the CPU is at the start of."""
        mpu = self.mpu
        low = self.memory[0x100 + ((mpu.sp + 1) & 0xFF)]
        high = self.memory[0x100 + ((mpu.sp + 2) & 0xFF)]
        mpu.sp = (mpu.sp + 2) & 0xFF
        mpu.pc = ((high << 8 | low) + 1) & 0xFFFF
        mpu.p = (mpu.p | 1) if carry else (mpu.p & ~1)
        mpu.processorCycles += 12

    def _vblank(self):
        mpu = self.mpu
        if self.frame.header is None:
            self.frame.header = self.t
        self.frame.pad = self.pad
        self.frame.lines = self.window(self.frame)  # before the next NMI draws
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
        if pc == self.labels["main_wait"] and self.byte("frame_count") == self.byte("served_frame"):
            mpu.processorCycles = max(mpu.processorCycles, int(self.next_vblank) + 1)
            return True
        if pc < PRG_START:
            return False
        offset = pc - PRG_START
        if self.joy2_quiet_until is not None and self.prg[offset:offset + 6] == HUNT:
            # Whole passes of the hunt while the line rests at mark, so its
            # phase against the next start bit is kept.
            quiet = self.joy2_quiet_until(mpu.processorCycles)
            if quiet is None:
                return False
            limit = min(quiet, self.next_vblank, self._host_at)
            passes = int((limit - mpu.processorCycles - 2 * HUNT_CYCLES) // HUNT_CYCLES)
            if passes <= 0:
                return False
            mpu.processorCycles += passes * HUNT_CYCLES
            return True
        if not self.skip_waits:
            return False
        code = self.prg[offset:offset + 4]
        if code == WAIT_CLEAR:
            previous = self.frames[-1] if self.frames else None
            if previous is None or previous.hit_at is None:
                return False
            return self._skip_looks(self.frame.start + VBLANK_CYCLES)
        if code == WAIT_HIT:
            hit = self._hit_cycle()
            return hit is not None and self._skip_looks(hit)
        if code[:3] == DELAY_LOOP and mpu.x > 1:
            mpu.processorCycles += (mpu.x - 1) * DELAY_CYCLES
            mpu.x = 1
            return True
        return False

    def _skip_looks(self, until):
        """Pass over looks at PPUSTATUS that would all see the same thing,
        stopping a few short of the cycle where it changes. The loop counts
        its looks in X, and in Y every 256."""
        mpu = self.mpu
        looks = int((until - mpu.processorCycles) // WAIT_LOOK) - 3
        if looks <= 0:
            return False
        first_wrap = mpu.x or 256
        wraps = 0 if looks < first_wrap else (looks - first_wrap) // 256 + 1
        if wraps >= mpu.y:
            return False            # it would give up first: let it
        mpu.processorCycles += looks * WAIT_LOOK + wraps * WAIT_WRAP
        mpu.x = (mpu.x - looks) & 0xFF
        mpu.y -= wraps
        return True

    # --- what the reader shows -------------------------------------------------

    def window(self, frame):
        """The article's lines in view in a frame, read from the nametable
        as it is now: a list of 28 tile numbers each, 22 lines or 23 when
        the scroll is partway down one. None if the frame had no split.
        Every finished frame has this as its `lines`."""
        if frame.split is None:
            return None
        assert (frame.split >> 10) & 3 in (0, 2), "the article is in nametable 0"
        row, fine = divmod(frame.split_y, 8)
        count = 22 + (1 if fine else 0)
        return [self.tiles(0, (row + index) % 30, 2, 28) for index in range(count)]
