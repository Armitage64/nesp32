"""A ROM on py65, with as much of an NES round it as the setup ROM uses.

py65 is a plain 6502. This adds:

- A frame clock. A vblank comes every 29780.5 CPU cycles, and with it an
  NMI if the ROM has them on. The handler runs to its rti in one go.
- The PPU's address register and its data port, a nametable with its
  attributes, the palette, OAM filled by the DMA at $4014, and controller 1
  as a shift register loaded from `pad`.
- Controller port 2 as the link's line (wire.py): what a read of $4017
  sees on the cycle it looks, and where the writes to OUT0 go.
- The cartridge's MMC1, if the ROM's header says it has one: the banks of
  PRG and CHR its registers ask for, beginning as the chip does with the
  last 16 KB at $C000. A write at $8000 or above goes to it and changes
  nothing in the program. Reset does not reach it.

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
BANK_SIZE = 0x4000              # of PRG, as a mapper counts it
INES_HEADER = 16
CHR_SIZE = 0x2000
CHR_PAGE = 0x1000               # of CHR, as the MMC1 counts it
MAPPER_MMC1 = 1
MMC1_RESET = 0x80               # a write with this bit set, to any register
MMC1_LAST_FIXED = 0x0C          # control: the last bank at $C000, as at power-on
MMC1_CHR_PAGES = 0x10           # control: two pages of CHR, not one of 8 KB
RESET_VECTOR = 0xFFFC

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
# Four looks, each bit / bne, then dex / bne: 29 cycles a count. A run of
# looks with no dex after the fourth is the window's, where a frame's next
# byte is due: those are not skipped.
HUNT_TIMEOUT = (bytes((0x2C, 0x17, 0x40, 0xD0)), 29)
HUNT_TIMEOUT_LOOKS = 4
HUNT_TIMEOUT_REST = (0xCA, 0xD0)                                    # after the last look
READS_ABS = (0xAD, 0x2C)        # lda and bit: each reads on its 4th cycle
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
        chr_start = INES_HEADER + rom[4] * BANK_SIZE
        self.rom_prg = bytes(rom[INES_HEADER:chr_start])
        self.rom_chr = bytes(rom[chr_start:chr_start + rom[5] * CHR_SIZE])
        self.mmc1 = rom[6] >> 4 == MAPPER_MMC1
        self.mapper = [MMC1_LAST_FIXED, 0, 0, 0]    # control, CHR 0, CHR 1, PRG
        self._mapper_shift = self._mapper_count = 0
        self.mapper_writes = []     # (the instruction's address, the register's, the value)
        # What the tests ask of the setup ROM and the menu, and not of the
        # other programs on the cartridge: the controller ports through
        # lda and sta, the PPU written to only when it may be, an NMI on.
        self.strict = True
        self.memory = ObservableMemory()
        self.prg = self.chr = None  # the 32 KB and the 8 KB that are mapped
        self._map()
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
        if self.mmc1:
            memory.subscribe_to_write(range(PRG_START, 0x10000), self._write_mapper)
        self.mpu = MPU(memory=memory)
        self.mpu.pc = memory[RESET_VECTOR] | memory[RESET_VECTOR + 1] << 8

    @property
    def now(self):
        return self.mpu.processorCycles

    def reset(self):
        """The reset button: the program at $C000 starts again from its
        vector, with the picture and the NMI off. A mapper keeps what it
        held."""
        mpu = self.mpu
        self.ctrl = self.mask = 0
        self.in_nmi = False
        mpu.p |= mpu.INTERRUPT
        mpu.sp = (mpu.sp - 3) & 0xFF
        mpu.pc = self.memory[RESET_VECTOR] | self.memory[RESET_VECTOR + 1] << 8

    # --- the mapper ------------------------------------------------------------

    def _map(self):
        """Put the banks the mapper asks for where the CPU and the picture
        find them. `home` says the last bank is at $C000, which is where
        the labels are from."""
        if self.mmc1:
            control, chr0, chr1, bank = self.mapper
            banks = len(self.rom_prg) // BANK_SIZE
            bank &= 0x0F
            mode = control >> 2 & 3
            if mode < 2:                # 32 KB at a time
                low = bank & ~1
                high = low + 1
            elif mode == 2:             # the first bank at $8000
                low, high = 0, bank
            else:                       # the last bank at $C000
                low, high = bank, banks - 1
            pages = (chr0, chr1) if control & MMC1_CHR_PAGES else (chr0 & ~1, chr0 | 1)
            count = len(self.rom_chr) // CHR_PAGE
            self.chr = b"".join(self.rom_chr[page % count * CHR_PAGE:][:CHR_PAGE]
                                for page in pages)
            self.home = high % banks == banks - 1
            prg = b"".join(self.rom_prg[each % banks * BANK_SIZE:][:BANK_SIZE]
                           for each in (low, high))
        else:
            self.chr = self.rom_chr[:CHR_SIZE]
            self.home = True
            prg = self.rom_prg[:PRG_SIZE]
        if prg != self.prg:
            self.prg = prg
            self.memory.write(PRG_START, prg)

    def _write_mapper(self, address, value):
        self.mapper_writes.append((self.mpu.pc - 1, address, value))
        if value & MMC1_RESET:
            self._mapper_shift = self._mapper_count = 0
            self.mapper[0] |= MMC1_LAST_FIXED
        else:
            self._mapper_shift |= (value & 1) << self._mapper_count
            self._mapper_count += 1
            if self._mapper_count == 5:
                self.mapper[address >> 13 & 3] = self._mapper_shift
                self._mapper_shift = self._mapper_count = 0
        self._map()
        return self.prg[address - PRG_START]    # the program is not written to

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
        elif self.strict and self.mask & RENDERING:
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
        if self.strict and self.memory[mpu.pc - 1] not in READS_ABS:
            raise AssertionError("$4017 read by opcode $%02X" % self.memory[mpu.pc - 1])
        cycle = mpu.processorCycles + 3
        level = self.joy2_level(cycle) if self.joy2_level is not None else 1
        if self.joy2_reads is not None:
            self.joy2_reads.append((cycle, mpu.pc - 1, level))
        return 0x40 | (level ^ 1)

    def _write_joy1(self, address, value):
        mpu = self.mpu
        if self.strict and self.memory[mpu.pc - 1] not in STORES_ABS:
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
                elif self.strict and len(self.frames) - nmi_off_since > STALL_FRAMES:
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
        if (self.home and pc == self.labels.get("main_wait")
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
            if code is HUNT_TIMEOUT[0] and (
                    any(self.prg[offset + 5 * look:offset + 5 * look + 4] != code
                        for look in range(HUNT_TIMEOUT_LOOKS))
                    or tuple(self.prg[offset + 5 * HUNT_TIMEOUT_LOOKS:
                                      offset + 5 * HUNT_TIMEOUT_LOOKS + 2]) != HUNT_TIMEOUT_REST):
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
