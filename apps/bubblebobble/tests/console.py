"""Bubble Bobble's ROM on py65, with as much of an NES round it as the ROM
uses.

TMNT II's console (apps/tmnt2/tests/console.py), with Bubble Bobble's
cartridge in place of TMNT II's.

py65 is a plain 6502. This adds:

- A frame clock. A vblank comes every 29780.5 CPU cycles, and with it an
  NMI if the ROM has them on. All of Bubble Bobble's game runs in its NMI
  handler, which turns the NMI off as it begins and on again as it ends:
  a frame that takes too long has no NMI at the next vblank (its record
  says `lag`), and the game goes on where it was.
- The PPU's registers as far as the game's logic can tell: the vblank flag
  of PPUSTATUS, and PPUADDR and PPUDATA writing to nametables and palettes
  that the tests can read back. Nothing is drawn.
- OAM filled by the DMA at $4014, with the cycles it takes.
- Controllers 1 and 2 as shift registers loaded from `pads`. Port 2 can be
  given to a serial line instead (joy2_level, on_joy1), as in nes-wiki.
- The cartridge, an MMC1: its serial port, written a bit at a time, five
  writes to a register; 16 KB PRG banks, the last fixed at $C000 in the
  mode the game keeps it in; and the 8 KB of PRG RAM at $6000 that the
  netplay ROM's header asks for, there for either ROM (the original never
  touches it), off while bit 4 of the PRG bank register is set. The CHR
  banks are only kept: nothing reads the pattern tables back.
- The sample channel as far as the CPU can tell: while a sample plays,
  each byte it fetches stops the CPU for a few cycles (`dmc_steal`). The
  game plays none; the netplay's tests may.

Time is in CPU cycles. The idle loop the game sits in between NMIs, once
its count (IDLE_COUNT) is up, the reset's waits for the vblank flag, and
the serial receiver's looks at a line that rests at mark are skipped
rather than stepped. Each frame's record says how many cycles the game was
busy for, which is what the link has to fit beside.

Two consoles do not share a clock. `frame_cycles` sets how long this one's
frames are, and run_until runs it to a cycle of its own, so a test can run
two side by side, a slice at a time, with one a little fast.
"""

import hashlib
import math

from py65.devices.mpu6502 import MPU

FRAME_CYCLES = 29780.5
VBLANK_CYCLES = 20 * 341 / 3    # 2273: the vblank flag stands this long
PRG_START = 0x8000
FIXED_START = 0xC000
BANK_SIZE = 0x4000
INES_HEADER = 16
PRG_RAM_START = 0x6000
PRG_RAM_SIZE = 0x2000
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

APU_DMC, APU_DMC_LENGTH, APU_STATUS = 0x4010, 0x4013, 0x4015
APU_STATUS_DMC = 0x10
# CPU cycles to each bit of a sample, by the rate in $4010.
DMC_PERIODS = (428, 380, 340, 320, 286, 254, 226, 214, 190, 160, 142, 128, 106, 84, 72, 54)
DMC_STEAL = 4                   # the most a fetch takes from the CPU

# The MMC1's registers, by bits 13 and 14 of the address written; bit 7 of
# a write empties its shift register. In the PRG bank register, bit 4 turns
# the PRG RAM off.
MMC1_RESET = 0x80
MMC1_PRG_RAM_OFF = 0x10

# The main loop: it counts IDLE_COUNT up to $FF and then waits for the NMI.
# Where a ROM's debug file does not name them, the original's addresses.
IDLE = "IDLE"
IDLE_COUNT = "IDLE_COUNT"
IDLE_ADDRESS = 0xE90C
IDLE_COUNT_ADDRESS = 0x0454
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
        self.lag = False        # its vblank found the last NMI's work unfinished
        self.stolen = 0         # cycles the sample channel took
        self.pads = (0, 0)


class Bus:
    """The CPU's address space. py65 reads and writes it by index."""

    def __init__(self, console, prg):
        self.console = console
        self.ram = bytearray(RAM_SIZE)
        self.prg_ram = bytearray(PRG_RAM_SIZE)
        self.prg_ram_on = True
        self.prg = prg
        self.windows = [0, len(prg) - BANK_SIZE]  # where $8000 and $C000 are in the PRG
        self.written = None         # a bytearray: the RAM written since (watch_writes)

    def __getitem__(self, address):
        if address >= PRG_START:
            return self.prg[self.windows[(address - PRG_START) >> 14] + (address & 0x3FFF)]
        if address < 0x2000:
            return self.ram[address & 0x7FF]
        if address >= PRG_RAM_START:
            return self.prg_ram[address - PRG_RAM_START] if self.prg_ram_on else address >> 8
        return self.console.read_io(address)

    def __setitem__(self, address, value):
        if address < 0x2000:
            self.ram[address & 0x7FF] = value
            if self.written is not None:
                self.written[address & 0x7FF] = 1
        elif address >= PRG_START:
            self.console.write_mapper(address, value)
        elif address >= PRG_RAM_START:
            if self.prg_ram_on:
                self.prg_ram[address - PRG_RAM_START] = value
        else:
            self.console.write_io(address, value)

    def code(self, address, length):
        """Bytes of the program as they are mapped now."""
        return bytes(self[address + offset] for offset in range(length))

    def map(self, control, bank):
        """The control register's PRG mode, and the PRG bank register."""
        banks = len(self.prg) // BANK_SIZE
        mode = control >> 2 & 3
        bank &= 0x0F
        if mode < 2:
            low = bank & ~1
            order = (low, low + 1)
        elif mode == 2:
            order = (0, bank)
        else:
            order = (bank, banks - 1)
        self.windows = [(number % banks) * BANK_SIZE for number in order]

    def bank_at(self, address):
        return self.windows[(address - PRG_START) >> 14] // BANK_SIZE


class Console:
    def __init__(self, rom_path, labels_path=None, frame_cycles=FRAME_CYCLES,
                 dmc_steal=DMC_STEAL, dmc_phase=0):
        with open(rom_path, "rb") as handle:
            rom = handle.read()
        # The names of several debug files; the first to have a name wins.
        self.labels = {}
        for path in ([labels_path] if isinstance(labels_path, str) else labels_path or []):
            for name, value in load_labels(path).items():
                self.labels.setdefault(name, value)
        self.prg = bytes(rom[INES_HEADER:INES_HEADER + rom[4] * 0x4000])
        self.bus = Bus(self, self.prg)
        self.ram = self.bus.ram
        self.vram = bytearray(0x4000)
        self.oam = bytearray(256)
        self.ctrl = self.mask = 0
        self.t = self.v = self.w = 0
        self.read_buffer = 0
        self.vblank_unread = False
        self.pads = [0, 0]
        self._pad_shift = [0, 0]
        self._strobe = 0
        # The sample channel: cycles to a bit, the length register, bytes
        # still to fetch, and the cycle of the next fetch. dmc_steal is the
        # cycles a fetch stops the CPU for (0: the channel takes none), and
        # dmc_phase how long after it is started the first one comes.
        self.dmc_steal = dmc_steal
        self.dmc_phase = dmc_phase
        self.dmc_period = DMC_PERIODS[0]
        self.dmc_length = 0
        self.dmc_left = 0
        self.dmc_at = 0
        self.samples = 0            # samples started
        self.frames = []
        self.frame = Frame(0.0)     # the time before the first vblank
        self.frame_cycles = frame_cycles
        self.next_vblank = frame_cycles
        self.nmi_depth = 0          # NMI handlers not yet returned from
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
        self.marks = {}             # address: [(frame, cycle in it)] (mark)
        # The MMC1: its shift register and the writes in it, and its four
        # registers. It starts with the last bank fixed at $C000.
        self.mmc1_shift = 0
        self.mmc1_writes = 0
        self.mmc1_control = 0x0C
        self.chr_banks = [0, 0]
        self.prg_bank = 0
        self.bus.map(self.mmc1_control, self.prg_bank)
        self.mpu = MPU(memory=self.bus)
        self.mpu.pc = self.bus[0xFFFC] | self.bus[0xFFFD] << 8
        self.idle = self.labels.get(IDLE, IDLE_ADDRESS)
        self.idle_count = self.labels.get(IDLE_COUNT, IDLE_COUNT_ADDRESS)

    @property
    def in_nmi(self):
        return self.nmi_depth > 0

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
                value = self.read_buffer
                self.read_buffer = self.vram[self._mirror(self.v)]
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
        if address == APU_STATUS:
            return APU_STATUS_DMC if self.dmc_left else 0     # a sample has bytes to fetch
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
        elif address == APU_DMC:
            self.dmc_period = DMC_PERIODS[value & 0x0F]
        elif address == APU_DMC_LENGTH:
            self.dmc_length = value
        elif address == APU_STATUS:
            if not value & APU_STATUS_DMC:
                self.dmc_left = 0
            elif not self.dmc_left:
                self.dmc_left = self.dmc_length * 16 + 1
                self.dmc_at = self.now + 3 + self.dmc_phase
                self.samples += 1

    def write_mapper(self, address, value):
        if value & MMC1_RESET:
            self.mmc1_shift = 0
            self.mmc1_writes = 0
            self.mmc1_control |= 0x0C
        else:
            self.mmc1_shift |= (value & 1) << self.mmc1_writes
            self.mmc1_writes += 1
            if self.mmc1_writes < 5:
                return
            register = address >> 13 & 3
            if register == 0:
                self.mmc1_control = self.mmc1_shift
            elif register == 3:
                self.prg_bank = self.mmc1_shift
                self.bus.prg_ram_on = not self.prg_bank & MMC1_PRG_RAM_OFF
            else:
                self.chr_banks[register - 1] = self.mmc1_shift
            self.mmc1_shift = 0
            self.mmc1_writes = 0
        self.bus.map(self.mmc1_control, self.prg_bank)

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
        self.calls[self.labels.get(name, name)] = 0

    def calls_of(self, name):
        return self.calls[self.labels.get(name, name)]

    def watch_writes(self):
        """Note from now which bytes of the RAM the program writes: read
        them back with written."""
        self.bus.written = bytearray(RAM_SIZE)

    def written(self):
        return [address for address, hit in enumerate(self.bus.written) if hit]

    def mark(self, name):
        """Note from now the frame and the cycle in it of each time the
        program comes to a label, or an address: read them back with
        marks_of."""
        self.marks[self.labels.get(name, name)] = []

    def marks_of(self, name):
        return self.marks[self.labels.get(name, name)]

    def state(self):
        """A digest of everything the game's logic keeps. Left out are what
        the sound engine keeps ($CA-$F0), since it runs to the picture's
        clock and not the game's in a session; what the NMI keeps of the
        hardware for the sprites' flicker ($20, the PPU's status as the NMI
        read it, and $049F, where the OAM's DMA begins); and the stack
        (page 1 from $01D0), whose dead bytes depend on where an NMI
        landed. The tasks' stacks below it are the game's."""
        ram = self.ram
        return hashlib.sha1(bytes(ram[:0x20]) + bytes(ram[0x21:0xCA]) + bytes(ram[0xF1:0x1D0])
                            + bytes(ram[0x200:0x49F]) + bytes(ram[0x4A0:])).hexdigest()

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
            if self.dmc_left and mpu.processorCycles >= self.dmc_at:
                mpu.processorCycles += self.dmc_steal
                self.frame.stolen += self.dmc_steal
                self.dmc_left -= 1
                self.dmc_at += 8 * self.dmc_period
            pc = mpu.pc
            if pc in self.calls:
                self.calls[pc] += 1
            if pc in self.marks:
                self.marks[pc].append((len(self.frames), mpu.processorCycles - self.frame.start))
            if pc >= PRG_START:
                if pc == self.idle and not self.nmi_depth and bus[self.idle_count] == 0xFF:
                    self._wait(limit)
                    continue
                opcode = bus[pc]
                if opcode == RTI:
                    if self.nmi_depth:
                        self.nmi_depth -= 1
                        if not self.nmi_depth:
                            self.frame.nmi_cycles = mpu.processorCycles + 6 - self._nmi_at
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
        if self.dmc_left:
            until = min(until, self.dmc_at)
        # Up to a whole cycle: a limit between two (run_until's, on a clock
        # that runs fast or slow) is passed, not fallen short of.
        until = math.ceil(until) if until != float("inf") else until
        # Already there (a sample's fetch may have taken the clock past it):
        # the caller's loop sees to what is due, and the idle loop is not
        # stepped.
        if until > mpu.processorCycles:
            self.frame.busy -= until - mpu.processorCycles
            mpu.processorCycles = until

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
        if self.dmc_left:
            until = min(until, self.dmc_at)
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
        self.frame.lag = self.nmi_depth > 0
        if self.ctrl & PPUCTRL_NMI:
            if not self.nmi_depth:
                self._nmi_at = mpu.processorCycles
            self.nmi_depth += 1
            mpu.nmi()
