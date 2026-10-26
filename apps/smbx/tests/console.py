"""The SMB two-player hack's ROM on py65, with as much of an NES round it as
the ROM uses.

TMNT II's console (apps/tmnt2/tests/console.py), with the hack's cartridge
in place of an MMC3, and the 2A03's unofficial opcodes (mpu6502x.py).

py65 is a plain 6502. This adds:

- A frame clock. A vblank comes every 29780.5 CPU cycles, and with it an
  NMI if the ROM has them on. The NMI interrupts whatever is running, as
  on a console. All of the game runs in its NMI handler, so a frame that
  takes too long is interrupted by the next NMI, which the game answers
  with a short handler of its own (a lag frame) and returns into the long
  one.
- The PPU's registers as far as the game's logic can tell: the vblank flag
  of PPUSTATUS, and PPUADDR and PPUDATA writing to pattern tables,
  nametables and palettes that the tests can read back. Nothing is drawn.
- OAM filled by the DMA at $4014, with the cycles it takes.
- Controllers 1 and 2 as shift registers loaded from `pads`. Port 2 can be
  given to a serial line instead (joy2_level, on_joy1), as in nes-drmario.
- The cartridge, a VRC6 (mapper 24): a 16 KB PRG bank at $8000, an 8 KB
  one at $C000 and the last 8 KB fixed at $E000; the 8 KB of PRG RAM at
  $6000, which the game turns on at its reset; and the IRQ counter, in its
  scanline mode, which counts CPU cycles and nothing of the PPU's: a
  prescaler of 341 that three cycles step, and a counter that each of its
  ends steps up, from the latch to $FF and an IRQ. The IRQ is taken when
  the CPU's I flag lets it, as on a console, so a handler that runs with
  interrupts off holds it back; each frame's record says when it was raised
  and when it was taken. The CHR banks and the expansion sound are not
  kept: nothing reads them back.
- The sample channel as far as the CPU can tell: while a sample plays,
  each byte it fetches stops the CPU for a few cycles (`dmc_steal`). That
  is what a routine that counts cycles has to live with. Nothing is heard.

Time is in CPU cycles. The idle loop the game sits in between NMIs, the
reset's waits for the vblank flag, and the serial receiver's looks at a
line that rests at mark are skipped rather than stepped. Each frame's
record says how many cycles the game was busy for, which is what the link
has to fit beside.

Two consoles do not share a clock. `frame_cycles` sets how long this one's
frames are, and run_until runs it to a cycle of its own, so a test can run
two side by side, a slice at a time, with one a little fast.
"""

import hashlib
import math

from mpu6502x import MPU

FRAME_CYCLES = 29780.5
VBLANK_CYCLES = 20 * 341 / 3    # 2273: the vblank flag stands this long
LINE_CYCLES = 341 / 3
PRG_START = 0x8000
INES_HEADER = 16
PRG_RAM_START = 0x6000
PRG_RAM_SIZE = 0x2000
RAM_SIZE = 0x800
BANK_16K = 0x4000
BANK_8K = 0x2000
VRC6 = 24                       # the header's mapper number

PPUCTRL, PPUMASK, PPUSTATUS = 0x2000, 0x2001, 0x2002
PPUSCROLL, PPUADDR, PPUDATA = 0x2005, 0x2006, 0x2007
OAMDMA, JOY1, JOY2 = 0x4014, 0x4016, 0x4017
PPUCTRL_NMI, PPUCTRL_DOWN = 0x80, 0x04
VBLANK_FLAG = 0x80
DMA_CYCLES = 513
RTI = 0x40
INTERRUPT = 0x04                # the I flag

# The VRC6's registers, by the top of the address and its two lowest bits.
VRC6_PRG16 = 0x8000
VRC6_PPU = 0xB003               # bit 7: the PRG RAM on
VRC6_PRG8 = 0xC000
VRC6_IRQ_LATCH = 0xF000
VRC6_IRQ_CONTROL = 0xF001
VRC6_IRQ_ACK = 0xF002
VRC6_RAM_ON = 0x80
IRQ_AFTER_ACK, IRQ_ENABLE, IRQ_CYCLE_MODE = 0x01, 0x02, 0x04

PAD_A, PAD_B, PAD_SELECT, PAD_START = 0x80, 0x40, 0x20, 0x10
PAD_UP, PAD_DOWN, PAD_LEFT, PAD_RIGHT = 0x08, 0x04, 0x02, 0x01

APU_DMC, APU_DMC_LENGTH, APU_STATUS = 0x4010, 0x4013, 0x4015
APU_STATUS_DMC = 0x10
# CPU cycles to each bit of a sample, by the rate in $4010.
DMC_PERIODS = (428, 380, 340, 320, 286, 254, 226, 214, 190, 160, 142, 128, 106, 84, 72, 54)
DMC_STEAL = 4                   # the most a fetch takes from the CPU

IDLE = "GAME_IDLE"              # where the game waits for the NMI
# bit $2002 / bpl, and lda $2002 / bpl: the reset waiting for a vblank.
WAIT_VBLANK = (bytes((0x2C, 0x02, 0x20, 0x10, 0xFB)), bytes((0xAD, 0x02, 0x20, 0x10, 0xFB)))
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
        self.lag = False        # its NMI found the last frame's work unfinished
        self.stolen = 0         # cycles the sample channel took
        self.pads = (0, 0)
        self.irqs = []          # (raised, taken), cycles from the frame's start


class Bus:
    """The CPU's address space. py65 reads and writes it by index."""

    def __init__(self, console, prg):
        self.console = console
        self.ram = bytearray(RAM_SIZE)
        self.prg_ram = bytearray(PRG_RAM_SIZE)
        self.prg_ram_on = False
        self.prg = prg
        last = len(prg) - BANK_8K
        # Where each 8 KB from $8000 is in the PRG.
        self.windows = [0, BANK_8K, last, last]
        self.written = None         # a bytearray: the RAM written since (watch_writes)

    def __getitem__(self, address):
        if address >= PRG_START:
            return self.prg[self.windows[(address - PRG_START) >> 13] + (address & 0x1FFF)]
        if address < 0x2000:
            return self.ram[address & 0x7FF]
        if address >= PRG_RAM_START:
            return self.prg_ram[address - PRG_RAM_START] if self.prg_ram_on else 0x60
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

    def map(self, bank16, bank8):
        """The 16 KB bank at $8000 and the 8 KB one at $C000."""
        size = len(self.prg)
        low = (bank16 * BANK_16K) % size
        self.windows[0] = low
        self.windows[1] = low + BANK_8K
        self.windows[2] = (bank8 * BANK_8K) % size

    def bank16(self):
        return self.windows[0] // BANK_16K


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
        self.mapper = rom[6] >> 4 | (rom[7] & 0xF0)
        assert self.mapper == VRC6, "mapper %d" % self.mapper
        self.prg = bytes(rom[INES_HEADER:INES_HEADER + rom[4] * 0x4000])
        self.bus = Bus(self, self.prg)
        self.ram = self.bus.ram
        # The pattern tables are the CHR ROM, which the game reads through
        # PPUDATA: its title screen is kept there.
        self.vram = bytearray(0x4000)
        chr_rom = rom[INES_HEADER + len(self.prg):][:0x2000]
        self.vram[:len(chr_rom)] = chr_rom
        self.oam = bytearray(256)
        self.ctrl = self.mask = 0
        self.t = self.v = self.w = 0
        self.vblank_unread = False
        self.read_buffer = 0
        self.pads = [0, 0]
        self._pad_shift = [0, 0]
        self._strobe = 0
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
        # The interrupts not yet returned from, the latest last: "nmi" or
        # "irq". An IRQ handler ends in RTI as an NMI handler does.
        self.interrupts = []
        # Port 2 as a serial line (wire.py).
        self.joy2_level = None
        self.joy2_quiet_until = None
        self.on_joy1 = None
        self.on_vblank = None       # called with the console before each NMI
        self.host = None            # called every host_every cycles
        self.host_every = 0
        self._host_at = 0
        self.calls = {}             # address: times the program has come to it (count_calls)
        self.marks = {}             # address: [(frame, cycle in it)] (mark)
        self.on_pc = {}             # address: called with the console when the program comes to it
        # The VRC6: its PRG banks, and the IRQ counter. irq_at is the cycle
        # the counter next comes to its IRQ, None while it is off.
        self.bank16 = 0
        self.bank8 = 0
        self.irq_latch = 0
        self.irq_control = 0
        self.irq_at = None
        self.irq_line = False
        self._irq_raised = None
        self.bus.map(0, 0)
        self.mpu = MPU(memory=self.bus)
        self.reset_pc = self.bus[0xFFFC] | self.bus[0xFFFD] << 8
        self.mpu.pc = self.reset_pc
        self.idle = self.labels.get(IDLE)

    @property
    def nmi_depth(self):
        """NMI handlers not yet returned from."""
        return self.interrupts.count("nmi")

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
                # A read gives what the last one fetched, and fetches the
                # next: the PPU's read buffer.
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
        register = address & 0xF003
        top = address & 0xF000
        if top == VRC6_PRG16:
            self.bank16 = value & 0x0F
            self.bus.map(self.bank16, self.bank8)
        elif top == VRC6_PRG8:
            self.bank8 = value & 0x1F
            self.bus.map(self.bank16, self.bank8)
        elif register == VRC6_PPU:
            self.bus.prg_ram_on = bool(value & VRC6_RAM_ON)
        elif register == VRC6_IRQ_LATCH:
            self.irq_latch = value
        elif register == VRC6_IRQ_CONTROL:
            assert not value & IRQ_CYCLE_MODE, "the counter's cycle mode"
            self.irq_control = value
            self._irq_ack()
            # E set: the counter starts again from the latch, and the
            # prescaler from 341.
            self.irq_at = (self._irq_due(self.now + 4, self.irq_latch)
                           if value & IRQ_ENABLE else None)
        elif register == VRC6_IRQ_ACK:
            self._irq_ack()
            if self.irq_control & IRQ_AFTER_ACK:
                self.irq_control |= IRQ_ENABLE
            else:
                self.irq_control &= ~IRQ_ENABLE
                self.irq_at = None

    @staticmethod
    def _irq_due(start, latch):
        """The cycle a counter started at `start` from `latch` raises its
        IRQ: it is stepped every 341/3 cycles, and raises it when stepped
        at $FF."""
        return start + (256 - latch) * LINE_CYCLES

    def _irq_ack(self):
        self.irq_line = False
        self._irq_raised = None

    def _irq_count(self):
        """The counter has come to $FF and been stepped: the IRQ, and the
        counter from the latch again."""
        self.irq_line = True
        self._irq_raised = self.irq_at
        self.irq_at = self._irq_due(self.irq_at, self.irq_latch)

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

    def scanline(self, cycle):
        """The line the picture is on at a cycle of the frame: 0 the top
        of the picture, 240 and on the vblank, -1 the pre-render line."""
        return int((cycle - VBLANK_CYCLES) // LINE_CYCLES) - 1

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
        """A digest of the console's RAM."""
        return hashlib.sha1(bytes(self.ram)).hexdigest()

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
            if self.irq_at is not None and mpu.processorCycles >= self.irq_at:
                self._irq_count()
                continue
            if self.irq_line and not mpu.p & INTERRUPT:
                if self._irq_raised is not None:
                    self.frame.irqs.append((self._irq_raised - self.frame.start,
                                            mpu.processorCycles - self.frame.start))
                    self._irq_raised = None
                self.interrupts.append("irq")
                mpu.irq()
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
            if pc in self.on_pc:
                self.on_pc[pc](self)
            if pc == self.reset_pc:
                self.interrupts = []    # a reset from inside one: none is returned from
            if pc >= PRG_START:
                if pc == self.idle and not self.nmi_depth:
                    self._wait(limit)
                    continue
                opcode = bus[pc]
                if opcode == RTI:
                    if self.interrupts and self.interrupts.pop() == "nmi" and not self.nmi_depth:
                        self.frame.nmi_cycles = mpu.processorCycles + 6 - self._nmi_at
                elif opcode in (0x2C, 0xAD):
                    if bus.code(pc, 5) in WAIT_VBLANK and not self.vblank_unread:
                        self._wait(limit)
                        continue
                    if opcode == HUNT[0] and self._skip_hunt(pc, limit):
                        continue
            mpu.step()

    def _wait(self, limit):
        """Pass the time to the next vblank, or to the host's next turn."""
        mpu = self.mpu
        until = min(int(self.next_vblank) + 1, limit)
        if self.irq_at is not None:
            until = min(until, int(self.irq_at) + 1)
        if self.host is not None:
            until = min(until, self._host_at)
        if self.dmc_left:
            until = min(until, self.dmc_at)
        until = math.ceil(until) if until != float("inf") else until
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
        if self.irq_at is not None:
            until = min(until, self.irq_at)
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
        self.next_vblank += self.frame_cycles
        self.vblank_unread = True
        if self.ctrl & PPUCTRL_NMI:
            if self.nmi_depth:
                self.frame.lag = True
            else:
                self._nmi_at = mpu.processorCycles
            self.interrupts.append("nmi")
            mpu.nmi()
