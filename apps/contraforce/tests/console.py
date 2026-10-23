"""Contra Force's ROM on py65, with as much of an NES round it as the ROM
uses. It is nes-contra's console (apps/contra/tests/console.py), with the
MMC3's scanline IRQ, which this game splits its picture with.

py65 is a plain 6502. This adds:

- A frame clock. A vblank comes every 29780.5 CPU cycles, and with it an
  NMI if the ROM has them on. The NMI interrupts whatever is running, as
  on a console. All of Contra Force's game runs in its NMI handler, as
  Contra's does, so a frame that takes too long is interrupted by the next
  NMI, which the game answers with a short handler of its own (a lag
  frame) and returns into the long one.
- The MMC3's scanline counter and its IRQ. The counter is clocked once a
  line while the picture is on, at dot 260 of the pre-render line and of
  each of the 240 visible ones, and the IRQ is asked for when a clock
  leaves it at 0 with the IRQ on. The CPU takes it while its I flag lets
  it. The game's IRQ handlers wait in loops for the line's end, so their
  cycles count.
- The PPU's registers as far as the game's logic can tell: the vblank flag
  of PPUSTATUS, and PPUADDR and PPUDATA writing to pattern tables,
  nametables and palettes that the tests can read back. Nothing is drawn.
- OAM filled by the DMA at $4014, with the cycles it takes.
- Controllers 1 and 2 as shift registers loaded from `pads`. Port 2 can be
  given to a serial line instead (joy2_level, on_joy1), as in nes-drmario.
- The cartridge, an MMC3: 8 KB banks picked by R6 and R7, the last two
  fixed, with the mode bit that swaps $8000 and $C000, and 8 KB of PRG
  RAM at $6000, there while $A001 has it on (the original never turns it
  on; the faster ROM does). It powers on with the mode bit set and R6 and
  R7 at banks of no use, which a reset has to put right. Its CHR banks and
  mirroring are kept for the tests to look at, but nothing is drawn.
- The sample channel as far as the CPU can tell: while a sample plays,
  each byte it fetches stops the CPU for a few cycles (`dmc_steal`). That
  is what a routine that counts cycles has to live with. Nothing is heard.

Time is in CPU cycles. The idle loop the game sits in between NMIs, the
reset's waits for the vblank flag, and the serial receiver's looks at a
line that rests at mark are skipped rather than stepped. Each frame's
record says how many cycles the game was busy for, which is what the link
has to fit beside. The original game stirs its random number in the idle
loop; `stir_idle` steps the loop instead of skipping it, for the tests
that show what that does.

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
BANK_SIZE = 0x4000
MMC3_BANK = 0x2000
MMC3 = 4                        # the header's mapper number
PRG_RAM_START = 0x6000
PRG_RAM_SIZE = 0x2000
INES_HEADER = 16
RAM_SIZE = 0x800

PPUCTRL, PPUMASK, PPUSTATUS = 0x2000, 0x2001, 0x2002
PPUSCROLL, PPUADDR, PPUDATA = 0x2005, 0x2006, 0x2007
OAMDMA, JOY1, JOY2 = 0x4014, 0x4016, 0x4017
PPUCTRL_NMI, PPUCTRL_DOWN = 0x80, 0x04
VBLANK_FLAG = 0x80
DMA_CYCLES = 513
RTI = 0x40
DOTS = 341                      # a line
CLOCK_DOT = 260                 # where in a line the MMC3's counter is clocked
VBLANK_LINES = 20               # from the vblank to the pre-render line
PRE_RENDER, LINES = -1, 240
PPUMASK_SHOW = 0x18

PAD_A, PAD_B, PAD_SELECT, PAD_START = 0x80, 0x40, 0x20, 0x10
PAD_UP, PAD_DOWN, PAD_LEFT, PAD_RIGHT = 0x08, 0x04, 0x02, 0x01

APU_DMC, APU_DMC_LENGTH, APU_STATUS = 0x4010, 0x4013, 0x4015
APU_STATUS_DMC = 0x10
# CPU cycles to each bit of a sample, by the rate in $4010.
DMC_PERIODS = (428, 380, 340, 320, 286, 254, 226, 214, 190, 160, 142, 128, 106, 84, 72, 54)
DMC_STEAL = 4                   # the most a fetch takes from the CPU

IDLE = "loc_FD62_infinite_loop" # where the game waits for the NMI
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

# What state() leaves out of the RAM: what runs to the picture's clock and
# not the game's, which a ROM with fewer lag frames has at other values; and
# the stack, whose dead bytes depend on where an NMI landed. The picture's
# are the sound engine's ($E0-$EF, $0300-$032F and $0540-$05FF, its _se
# names), ram_disable_rendering_timer ($25), which every NMI counts down,
# ram_nmi_flag_2 ($C4), which a lag frame's NMI sets for the bank switch it
# breaks into, ram_save_stack_pointer ($03A0), where a lag frame's NMI may
# have pushed the PPU's buffer from, and ram_03A1_irq_timer ($03A1), which
# the IRQ counts down a frame. The stack is $01C0 on (it is never below
# $01CC but where the PPU's buffers are read through it); below it are the
# buffers, which are kept.
STACK = range(0x1C0, 0x200)
LEFT_OUT = frozenset([0x25, 0xC4, 0x3A0, 0x3A1] + list(range(0xE0, 0xF0)) + list(STACK)
                     + list(range(0x300, 0x330)) + list(range(0x540, 0x600)))


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
        self.irq_cycles = 0     # in the IRQ's handlers
        self.stolen = 0         # cycles the sample channel took
        self.pads = (0, 0)


class Bus:
    """The CPU's address space. py65 reads and writes it by index."""

    def __init__(self, console, prg, mmc3=True):
        self.console = console
        self.ram = bytearray(RAM_SIZE)
        self.prg = prg
        self.mmc3 = mmc3
        self.prg_ram = bytearray(PRG_RAM_SIZE) if mmc3 else None
        self.windows = [0, 0, 0, 0]  # where each 8 KB from $8000 is in the PRG
        self.bank = 0               # the game's number for the bank at $8000

    def __getitem__(self, address):
        if address >= PRG_START:
            return self.prg[self.windows[(address - PRG_START) >> 13] + (address & 0x1FFF)]
        if address < 0x2000:
            return self.ram[address & 0x7FF]
        if address >= PRG_RAM_START and self.prg_ram is not None and self.console.prg_ram_on:
            return self.prg_ram[address - PRG_RAM_START]
        return self.console.read_io(address)

    def __setitem__(self, address, value):
        if address < 0x2000:
            self.ram[address & 0x7FF] = value
        elif address >= PRG_START:
            self.console.write_mapper(address, value)
        elif address >= PRG_RAM_START and self.prg_ram is not None:
            if self.console.prg_ram_on:
                self.prg_ram[address - PRG_RAM_START] = value
        else:
            self.console.write_io(address, value)

    def code(self, address, length):
        """Bytes of the program as they are mapped now."""
        return bytes(self[address + offset] for offset in range(length))

    def map_mmc3(self, r6, r7, swapped):
        """R6 and R7, and the mode bit that puts R6 at $C000."""
        banks = len(self.prg) // MMC3_BANK
        last = banks - 1
        order = (last - 1, r7, r6, last) if swapped else (r6, r7, last - 1, last)
        self.windows = [(bank % banks) * MMC3_BANK for bank in order]
        self.bank = self[PRG_START]



class Console:
    def __init__(self, rom_path, labels_path=None, frame_cycles=FRAME_CYCLES,
                 stir_idle=False, dmc_steal=DMC_STEAL, dmc_phase=0):
        with open(rom_path, "rb") as handle:
            rom = handle.read()
        # The names of several debug files; the first to have a name wins.
        self.labels = {}
        for path in ([labels_path] if isinstance(labels_path, str) else labels_path or []):
            for name, value in load_labels(path).items():
                self.labels.setdefault(name, value)
        self.prg = bytes(rom[INES_HEADER:INES_HEADER + rom[4] * BANK_SIZE])
        self.mapper = rom[6] >> 4 | (rom[7] & 0xF0)
        assert self.mapper == MMC3, "an MMC3 ROM"
        self.bus = Bus(self, self.prg)
        # The MMC3's registers. At power-on they are whatever they are; these
        # are some of no use, with the mode bit that leaves $C000 to R6.
        self.bank_select = 0x40
        self.banks = [0x11, 0x13, 0x15, 0x17, 0x19, 0x1B, 0x05, 0x09]
        self.mirroring = None       # 0 vertical, 1 horizontal: none written yet
        self.prg_ram_on = False
        # The scanline counter: its latch, its count, whether $C001 has
        # asked it to load the latch at the next clock, the IRQ on, and the
        # IRQ asked for and not yet taken or turned off.
        self.irq_latch = 0
        self.irq_counter = 0
        self.irq_reload = False
        self.irq_on = False
        self.irq_wanted = False
        self.next_line = PRE_RENDER     # the line of the counter's next clock
        self.interrupts = []        # "nmi" and "irq": the handlers not yet returned from
        self._irq_at = 0
        self.ram = self.bus.ram
        self.vram = bytearray(0x4000)
        self.oam = bytearray(256)
        self.ctrl = self.mask = 0
        self.t = self.v = self.w = 0
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
        self.stir_idle = stir_idle
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
        self._map_mmc3()
        self.mpu = MPU(memory=self.bus)
        self.mpu.pc = self.bus[0xFFFC] | self.bus[0xFFFD] << 8
        self.idle = self.labels.get(IDLE)

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
        even = not address & 1
        if address < 0xA000:
            if even:
                self.bank_select = value
            else:
                self.banks[self.bank_select & 7] = value
            self._map_mmc3()
        elif address < 0xC000:
            if even:
                self.mirroring = value & 1
            else:
                self.prg_ram_on = value & 0xC0 == 0x80
        elif address < 0xE000:
            if even:
                self.irq_latch = value
            else:
                self.irq_counter = 0
                self.irq_reload = True
        elif even:
            self.irq_on = False
            self.irq_wanted = False
        else:
            self.irq_on = True

    # --- the scanline counter --------------------------------------------------

    def _line_clock(self, line):
        """The cycle of the counter's clock on a line of this frame."""
        lines = VBLANK_LINES + (0 if line == PRE_RENDER else 1 + line)
        return self.frame.start + (lines * DOTS + CLOCK_DOT - 1) / 3

    def _step_counter(self, counter, reload):
        if counter == 0 or reload:
            return self.irq_latch
        return counter - 1

    def _clock_lines(self):
        """The clocks that are due, each on a line with the picture on."""
        while self.next_line < LINES and self.mpu.processorCycles >= self._line_clock(self.next_line):
            if self.mask & PPUMASK_SHOW:
                self.irq_counter = self._step_counter(self.irq_counter, self.irq_reload)
                self.irq_reload = False
                if self.irq_counter == 0 and self.irq_on:
                    self.irq_wanted = True
            self.next_line += 1

    def _next_irq(self):
        """The cycle the IRQ will be asked for at if nothing is written
        first; inf if it will not be this frame."""
        if not self.irq_on or not self.mask & PPUMASK_SHOW:
            return float("inf")
        counter, reload = self.irq_counter, self.irq_reload
        for line in range(self.next_line, LINES):
            counter, reload = self._step_counter(counter, reload), False
            if counter == 0:
                return self._line_clock(line)
        return float("inf")

    def _map_mmc3(self):
        self.bus.map_mmc3(self.banks[6], self.banks[7], bool(self.bank_select & 0x40))

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
        """A digest of everything the game's logic keeps: its RAM less
        LEFT_OUT."""
        ram = bytearray(self.ram)
        for address in LEFT_OUT:
            ram[address] = 0
        return hashlib.sha1(bytes(ram)).hexdigest()

    def ram_of_state(self):
        """The RAM that state() digests, for a test to say where two
        differ."""
        ram = bytearray(self.ram)
        for address in LEFT_OUT:
            ram[address] = 0
        return ram

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
            self._clock_lines()
            if self.irq_wanted and not mpu.p & mpu.INTERRUPT:
                self.irq_wanted = False
                self.interrupts.append("irq")
                self._irq_at = mpu.processorCycles
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
            if pc >= PRG_RAM_START:        # the cartridge's, ROM or the netplay's code in its RAM
                if pc == self.idle and not self.interrupts and not self.stir_idle:
                    self._wait(limit)
                    continue
                opcode = bus[pc]
                if opcode == RTI:
                    kind = self.interrupts.pop() if self.interrupts else None
                    if kind == "irq":
                        self.frame.irq_cycles += mpu.processorCycles + 6 - self._irq_at
                    elif kind == "nmi" and self.nmi_depth:
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
        until = min(int(self.next_vblank) + 1, limit, self._next_irq())
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
        self._clock_lines()
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
        self.next_line = PRE_RENDER
        self.vblank_unread = True
        if self.ctrl & PPUCTRL_NMI:
            if self.nmi_depth:
                self.frame.lag = True
            else:
                self._nmi_at = mpu.processorCycles
            self.nmi_depth += 1
            self.interrupts.append("nmi")
            mpu.nmi()
