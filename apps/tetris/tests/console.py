"""Tetris's ROM on py65, with as much of an NES round it as the ROM uses.

py65 is a plain 6502. This adds:

- A frame clock. A vblank comes every 29780.5 CPU cycles, and with it an
  NMI if the ROM has them on. The NMI interrupts whatever is running, as
  on a console: the game's handler is not held back while the main loop is
  still at work on a frame.
- The PPU's registers as far as the game's logic can tell: the vblank flag
  of PPUSTATUS, and PPUADDR and PPUDATA writing to nametables and palettes
  that the tests can read back. Nothing is drawn.
- OAM filled by the DMA at $4014, with the cycles it takes.
- Controllers 1 and 2 as shift registers loaded from `pads`. Port 2 can be
  given to a serial line instead (joy2_level, on_joy1), as in nes-wiki.
- The cartridge: writes to $8000-$FFFF go to the mapper and change nothing
  in the program, which the game counts on (it resets the MMC1 with an
  `inc $FF00`). The MMC1's PRG banking is modelled, for the netplay ROM's
  second bank; it starts as the chip does, with the last 16 KB at $C000.
  The CHR banks are only kept, for the tests to look at.

Time is in CPU cycles. The game's waits for the NMI, the reset's waits for
the vblank flag, and the serial receiver's looks at a line that rests at
mark are skipped rather than stepped. Each frame's record says how many
cycles the game was busy for, which is what the link has to fit beside.

Two consoles do not share a clock. `frame_cycles` sets how long this one's
frames are, and run_until runs it to a cycle of its own, so a test can run
two side by side, a slice at a time, with one a little fast.
"""

import hashlib

from py65.devices.mpu6502 import MPU

FRAME_CYCLES = 29780.5
VBLANK_CYCLES = 20 * 341 / 3    # 2273: the vblank flag stands this long
PRG_START = 0x8000
BANK_SIZE = 0x4000
INES_HEADER = 16
RAM_SIZE = 0x800

PPUCTRL, PPUMASK, PPUSTATUS = 0x2000, 0x2001, 0x2002
PPUSCROLL, PPUADDR, PPUDATA = 0x2005, 0x2006, 0x2007
OAMDMA, JOY1, JOY2 = 0x4014, 0x4016, 0x4017
PPUCTRL_NMI, PPUCTRL_DOWN = 0x80, 0x04
VBLANK_FLAG = 0x80
DMA_CYCLES = 513
RTI = 0x40

PAD_A, PAD_B, PAD_SELECT, PAD_START = 0x80, 0x40, 0x20, 0x10
PAD_UP, PAD_DOWN, PAD_LEFT, PAD_RIGHT = 0x08, 0x04, 0x02, 0x01

# lda ram_nmi_flag / beq: the main loop waiting for the NMI.
WAIT_NMI = bytes((0xA5, 0x33, 0xF0, 0xFC))
NMI_FLAG = 0x33
# lda $2002 / bpl: the reset code waiting for a vblank.
WAIT_VBLANK = bytes((0xAD, 0x02, 0x20, 0x10, 0xFB))
# The serial receiver's wait for a start bit: four looks, each bit $4017 /
# bne, then dex / bne, 29 cycles in all. X counts those. (A run of looks
# with no dex after the fourth is where a frame's next byte is due, and is
# not skipped.)
HUNT = bytes((0x2C, 0x17, 0x40, 0xD0))
HUNT_LOOKS = 4
HUNT_REST = (0xCA, 0xD0)        # after the last look
HUNT_CYCLES = 29


def load_labels(path):
    """Every name in ld65's debug file with its value: labels, and the
    constants that name the game's memory."""
    labels = {}
    with open(path) as handle:
        for line in handle:
            if not line.startswith("sym\t"):
                continue
            fields = dict(field.split("=", 1) for field in line[4:].strip().split(","))
            name = fields["name"].strip('"')
            if "val" in fields and not name.startswith("@"):
                labels[name] = int(fields["val"], 16)
    return labels


class Frame:
    """One frame, from the vblank that began it to the next."""

    def __init__(self, start):
        self.start = start
        self.nmi_cycles = 0     # the handler's length; 0 if no NMI fired
        self.busy = 0           # cycles not spent waiting for the next NMI
        self.pads = (0, 0)


class Bus:
    """The CPU's address space. py65 reads and writes it by index."""

    def __init__(self, console, prg):
        self.console = console
        self.ram = bytearray(RAM_SIZE)
        self.prg = prg
        self.low = self.high = 0    # where $8000 and $C000 are in the PRG

    def __getitem__(self, address):
        if address >= 0xC000:
            return self.prg[self.high + address - 0xC000]
        if address >= PRG_START:
            return self.prg[self.low + address - PRG_START]
        if address < 0x2000:
            return self.ram[address & 0x7FF]
        return self.console.read_io(address)

    def __setitem__(self, address, value):
        if address < 0x2000:
            self.ram[address & 0x7FF] = value
        elif address >= PRG_START:
            self.console.write_mapper(address, value)
        else:
            self.console.write_io(address, value)

    def code(self, address, length):
        """Bytes of the program as they are mapped now."""
        return bytes(self[address + offset] for offset in range(length))

    def map(self, control, bank):
        banks = len(self.prg) // BANK_SIZE
        mode = (control >> 2) & 3
        if mode < 2:                # 32 KB at a time
            low = bank & ~1
            high = low + 1
        elif mode == 2:             # the first bank at $8000
            low, high = 0, bank
        else:                       # the last bank at $C000
            low, high = bank, banks - 1
        self.low = (low % banks) * BANK_SIZE
        self.high = (high % banks) * BANK_SIZE


class Console:
    def __init__(self, rom_path, labels_path=None, frame_cycles=FRAME_CYCLES):
        with open(rom_path, "rb") as handle:
            rom = handle.read()
        # The names of several debug files; the first to have a name wins.
        self.labels = {}
        for path in ([labels_path] if isinstance(labels_path, str) else labels_path or []):
            for name, value in load_labels(path).items():
                self.labels.setdefault(name, value)
        self.prg = bytes(rom[INES_HEADER:INES_HEADER + rom[4] * BANK_SIZE])
        self.bus = Bus(self, self.prg)
        self.ram = self.bus.ram
        self.vram = bytearray(0x4000)
        self.oam = bytearray(256)
        self.ctrl = self.mask = 0
        self.t = self.v = self.w = 0
        self.vblank_unread = False
        self.pads = [0, 0]
        self._pad_shift = [0, 0]
        self._strobe = 0
        self.mapper = [0x0C, 0, 0, 0]   # the MMC1's control, CHR 0, CHR 1, PRG
        self._mapper_shift = 0
        self._mapper_count = 0
        self.frames = []
        self.frame = Frame(0.0)     # the time before the first vblank
        self.frame_cycles = frame_cycles
        self.next_vblank = frame_cycles
        self.in_nmi = False
        # Port 2 as a serial line (wire.py): the level of D0 at a cycle,
        # when it next leaves mark, and where OUT0's writes go. None leaves
        # controller 2 on the port.
        self.joy2_level = None
        self.joy2_quiet_until = None
        self.on_joy1 = None
        self.on_vblank = None       # called with the console before each NMI
        self.host = None            # called every host_every cycles
        self.host_every = 0
        self._host_at = 0
        self.calls = {}             # address: times the program has come to it (count_calls)
        self.bus.map(self.mapper[0], self.mapper[3])
        self.mpu = MPU(memory=self.bus)
        self.mpu.pc = self.bus[0xFFFC] | self.bus[0xFFFD] << 8

    @property
    def now(self):
        return self.mpu.processorCycles

    # --- the registers ---------------------------------------------------------

    def read_io(self, address):
        if address < 0x4000:
            address &= 0x2007
            if address == PPUSTATUS:
                value = 0
                if self.vblank_unread and self.now + 3 < self.frame.start + VBLANK_CYCLES:
                    value = VBLANK_FLAG
                self.vblank_unread = False
                self.w = 0
                return value
            if address == PPUDATA:
                value = self.vram[self._mirror(self.v)]
                self._step_v()
                return value
            return 0
        if address == JOY1:
            return 0x40 | self._read_pad(0)
        if address == JOY2:
            if self.joy2_level is not None:
                # Bit 0 is D0 inverted; the rest is the $40 the bus held.
                return 0x40 | (self.joy2_level(self.now + 3) ^ 1)
            return 0x40 | self._read_pad(1)
        return 0

    def write_io(self, address, value):
        if address < 0x4000:
            address &= 0x2007
            if address == PPUCTRL:
                self.ctrl = value
                self.t = (self.t & ~0x0C00) | (value & 3) << 10
            elif address == PPUMASK:
                self.mask = value
            elif address == PPUSCROLL:
                self.w ^= 1
            elif address == PPUADDR:
                if self.w == 0:
                    self.t = (self.t & 0x00FF) | (value & 0x3F) << 8
                else:
                    self.t = (self.t & 0x7F00) | value
                    self.v = self.t
                self.w ^= 1
            elif address == PPUDATA:
                self.vram[self._mirror(self.v)] = value
                self._step_v()
        elif address == OAMDMA:
            page = value << 8
            for offset in range(256):
                self.oam[offset] = self.bus[page | offset]
            self.mpu.processorCycles += DMA_CYCLES
        elif address == JOY1:
            if self.on_joy1 is not None:
                self.on_joy1(self.now + 3, value & 1)
            # While OUT0 is high the controllers keep loading their buttons,
            # so what they shift out is what was held when OUT0 fell.
            if self._strobe or value & 1:
                self._pad_shift = list(self.pads)
            self._strobe = value & 1

    def write_mapper(self, address, value):
        if value & 0x80:
            self._mapper_shift = self._mapper_count = 0
            self.mapper[0] |= 0x0C
        else:
            self._mapper_shift |= (value & 1) << self._mapper_count
            self._mapper_count += 1
            if self._mapper_count < 5:
                return
            self.mapper[(address >> 13) & 3] = self._mapper_shift
            self._mapper_shift = self._mapper_count = 0
        self.bus.map(self.mapper[0], self.mapper[3] & 0x0F)

    def _step_v(self):
        self.v = (self.v + (32 if self.ctrl & PPUCTRL_DOWN else 1)) & 0x7FFF

    @staticmethod
    def _mirror(address):
        address &= 0x3FFF
        if address >= 0x3F00:
            return 0x3F00 | (address & 0x1F)
        return address

    def _read_pad(self, port):
        if self._strobe:
            return self.pads[port] >> 7
        bit = self._pad_shift[port] >> 7
        self._pad_shift[port] = (self._pad_shift[port] << 1 | 1) & 0xFF
        return bit

    # --- what the tests look at --------------------------------------------------

    def byte(self, name, offset=0):
        return self.bus[self.labels[name] + offset]

    def tiles(self, address, length):
        return bytes(self.vram[address:address + length])

    def count_calls(self, name):
        """Count from now how often the program comes to a label: read it
        back with calls_of."""
        self.calls[self.labels[name]] = 0

    def calls_of(self, name):
        return self.calls[self.labels[name]]

    def state(self):
        """A digest of everything the game's logic keeps: all of RAM but the
        stack page, whose dead bytes depend on where an NMI landed."""
        return hashlib.sha1(bytes(self.ram[:0x100]) + bytes(self.ram[0x200:])).hexdigest()

    # --- running -----------------------------------------------------------------

    def run(self, frames=1, pads=None):
        """Run until this many more vblanks have passed. `pads` sets the
        buttons held on the two controllers from now on."""
        if pads is not None:
            self.pads = list(pads)
        target = len(self.frames) + frames
        while len(self.frames) < target:
            self._advance(float("inf"), target)

    def run_until(self, cycle, pads=None):
        """Run to a cycle of this console's clock, or an instruction past."""
        if pads is not None:
            self.pads = list(pads)
        self._advance(cycle, float("inf"))

    def _advance(self, limit, frames):
        mpu = self.mpu
        bus = self.bus
        while mpu.processorCycles < limit and len(self.frames) < frames:
            if mpu.processorCycles >= self.next_vblank:
                self._vblank()
                continue
            if self.host is not None and mpu.processorCycles >= self._host_at:
                self._host_at = mpu.processorCycles + self.host_every
                self.host()
            pc = mpu.pc
            if pc in self.calls:
                self.calls[pc] += 1
            if pc >= PRG_START:
                opcode = bus[pc]
                if (opcode == WAIT_NMI[0] and not self.in_nmi
                        and bus.code(pc, 4) == WAIT_NMI and not self.ram[NMI_FLAG]):
                    self._wait(limit)
                    continue
                if opcode == RTI:
                    if self.in_nmi:
                        self.frame.nmi_cycles = mpu.processorCycles + 6 - self._nmi_at
                    self.in_nmi = False
                elif opcode == WAIT_VBLANK[0]:
                    if bus.code(pc, 5) == WAIT_VBLANK and not self.vblank_unread:
                        self._wait(limit)
                        continue
                elif opcode == HUNT[0]:
                    if self._skip_hunt(pc, limit):
                        continue
            mpu.step()

    def _wait(self, limit):
        """Pass the time to the next vblank, or to the host's next turn."""
        mpu = self.mpu
        until = min(int(self.next_vblank) + 1, limit)
        if self.host is not None:
            until = min(until, self._host_at)
        until = int(until) if until != float("inf") else until
        if until > mpu.processorCycles:
            self.frame.busy -= until - mpu.processorCycles
            mpu.processorCycles = until
        else:
            mpu.step()

    def _skip_hunt(self, pc, limit):
        """Pass over whole looks of the receiver's hunt while the line rests
        at mark, so its phase against the next start bit is kept. True if
        it did."""
        if self.joy2_quiet_until is None:
            return False
        code = self.bus.code(pc, 5 * HUNT_LOOKS + 2)
        if (any(code[5 * look:5 * look + 4] != HUNT for look in range(HUNT_LOOKS))
                or tuple(code[5 * HUNT_LOOKS:]) != HUNT_REST):
            return False
        mpu = self.mpu
        quiet = self.joy2_quiet_until(mpu.processorCycles)
        if quiet is None:
            return False
        until = min(quiet, limit)
        if self.host is not None:
            until = min(until, self._host_at)
        looks = int((until - mpu.processorCycles) // HUNT_CYCLES) - 2
        looks = min(looks, (mpu.x or 256) - 2)
        if looks <= 0:
            return False
        mpu.processorCycles += looks * HUNT_CYCLES
        mpu.x = (mpu.x - looks) & 0xFF
        return True

    def _vblank(self):
        mpu = self.mpu
        if self.on_vblank is not None:
            self.on_vblank(self)
        frame = self.frame
        frame.busy += mpu.processorCycles - frame.start
        frame.pads = tuple(self.pads)
        self.frames.append(frame)
        self.frame = Frame(self.next_vblank)
        # The cycles past the vblank that the last instruction ran on belong
        # to the new frame, and are counted when it ends.
        self.next_vblank += self.frame_cycles
        self.vblank_unread = True
        if self.ctrl & PPUCTRL_NMI:
            self.in_nmi = True
            self._nmi_at = mpu.processorCycles
            mpu.nmi()
