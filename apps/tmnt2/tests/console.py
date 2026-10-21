"""TMNT II's ROM on py65, with as much of an NES round it as the ROM uses.

Contra's console (apps/contra/tests/console.py), with TMNT II's cartridge
in place of Contra's.

py65 is a plain 6502. This adds:

- A frame clock. A vblank comes every 29780.5 CPU cycles, and with it an
  NMI if the ROM has them on. The NMI interrupts whatever is running, as
  on a console. All of TMNT II's game runs in its NMI handler, so a frame
  that takes too long is interrupted by the next NMI, which the game
  answers with a short handler of its own (a lag frame) and returns into
  the long one.
- The PPU's registers as far as the game's logic can tell: the vblank flag
  of PPUSTATUS, and PPUADDR and PPUDATA writing to pattern tables,
  nametables and palettes that the tests can read back. Nothing is drawn.
- OAM filled by the DMA at $4014, with the cycles it takes.
- Controllers 1 and 2 as shift registers loaded from `pads`. Port 2 can be
  given to a serial line instead (joy2_level, on_joy1), as in nes-drmario.
- The cartridge, an MMC3: 8 KB PRG banks picked by R6 and R7, and the
  last two fixed, with the mode bit that swaps $8000 and $C000; and its
  scanline counter, which raises the IRQ line. The counter is clocked
  where the PPU's address line A12 rises: once a line while the picture
  is drawn (at dot 260 of the pre-render line and of each visible one,
  with the background's tiles at $0000), and, while it is not, by a write
  to PPUADDR that moves the address from below $1000 to above, as the
  game's own IRQ setup does. The IRQ is taken when the line is up and the
  CPU's I flag is clear, as on a console, so a handler that runs with
  interrupts off holds it back; each frame's record says when it was
  raised and when it was taken. There is no PRG RAM, and the CHR banks
  are not kept: nothing reads the pattern tables back.
- The sample channel as far as the CPU can tell: while a sample plays,
  each byte it fetches stops the CPU for a few cycles (`dmc_steal`). That
  is what a routine that counts cycles has to live with. Nothing is heard.

Time is in CPU cycles. The idle loop the game sits in between NMIs, the
reset's waits for the vblank flag, and the serial receiver's looks at a
line that rests at mark are skipped rather than stepped. Each frame's
record says how many cycles the game was busy for, which is what the link
has to fit beside. The original game stirs its random number in the idle
loop (INF_LOOP_COUNTER); `stir_idle` steps the loop instead of skipping
it, for the tests that show what that does.

Two consoles do not share a clock. `frame_cycles` sets how long this one's
frames are, and run_until runs it to a cycle of its own, so a test can run
two side by side, a slice at a time, with one a little fast.
"""

import hashlib

from py65.devices.mpu6502 import MPU

FRAME_CYCLES = 29780.5
VBLANK_CYCLES = 20 * 341 / 3    # 2273: the vblank flag stands this long
PRG_START = 0x8000
BANK_SIZE = 0x2000
INES_HEADER = 16
# Where the counter is clocked, in CPU cycles from the start of the vblank
# (scanline 241, dot 1): dot 260 of the pre-render line (261), and of each
# visible line after it.
LINE_CYCLES = 341 / 3
PRERENDER_CLOCK = (20 * 341 + 259) / 3
VISIBLE_LINES = 240
PPUMASK_RENDERING = 0x18
A12 = 0x1000
RAM_SIZE = 0x800

PPUCTRL, PPUMASK, PPUSTATUS = 0x2000, 0x2001, 0x2002
PPUSCROLL, PPUADDR, PPUDATA = 0x2005, 0x2006, 0x2007
OAMDMA, JOY1, JOY2 = 0x4014, 0x4016, 0x4017
PPUCTRL_NMI, PPUCTRL_DOWN = 0x80, 0x04
VBLANK_FLAG = 0x80
DMA_CYCLES = 513
RTI = 0x40
INTERRUPT = 0x04                # the I flag

PAD_A, PAD_B, PAD_SELECT, PAD_START = 0x80, 0x40, 0x20, 0x10
PAD_UP, PAD_DOWN, PAD_LEFT, PAD_RIGHT = 0x08, 0x04, 0x02, 0x01

APU_DMC, APU_DMC_LENGTH, APU_STATUS = 0x4010, 0x4013, 0x4015
APU_STATUS_DMC = 0x10
# CPU cycles to each bit of a sample, by the rate in $4010.
DMC_PERIODS = (428, 380, 340, 320, 286, 254, 226, 214, 190, 160, 142, 128, 106, 84, 72, 54)
DMC_STEAL = 4                   # the most a fetch takes from the CPU

IDLE = "INFINITE_LOOP"          # where the game waits for the NMI
# bit $2002 / bpl: the reset code waiting for a vblank.
WAIT_VBLANK = bytes((0x2C, 0x02, 0x20, 0x10, 0xFB))
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
        self.prg = prg
        self.windows = [0, 0, 0, 0]  # where each 8 KB from $8000 is in the PRG
        self.written = None         # a bytearray: the RAM written since (watch_writes)

    def __getitem__(self, address):
        if address >= PRG_START:
            return self.prg[self.windows[(address - PRG_START) >> 13] + (address & 0x1FFF)]
        if address < 0x2000:
            return self.ram[address & 0x7FF]
        return self.console.read_io(address)

    def __setitem__(self, address, value):
        if address < 0x2000:
            self.ram[address & 0x7FF] = value
            if self.written is not None:
                self.written[address & 0x7FF] = 1
        elif address >= PRG_START:
            self.console.write_mapper(address, value)
        else:
            self.console.write_io(address, value)

    def code(self, address, length):
        """Bytes of the program as they are mapped now."""
        return bytes(self[address + offset] for offset in range(length))

    def map(self, r6, r7, swapped):
        """R6 and R7, and the mode bit that puts R6 at $C000."""
        banks = len(self.prg) // BANK_SIZE
        last = banks - 1
        order = (last - 1, r7, r6, last) if swapped else (r6, r7, last - 1, last)
        self.windows = [(bank % banks) * BANK_SIZE for bank in order]

    def bank_at(self, address):
        return self.windows[(address - PRG_START) >> 13] // BANK_SIZE


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
        self.prg = bytes(rom[INES_HEADER:INES_HEADER + rom[4] * 0x4000])
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
        self.marks = {}             # address: [(frame, cycle in it)] (mark)
        # The MMC3: its bank select, its eight bank registers, and the
        # scanline counter.
        self.bank_select = 0
        self.banks = [0, 2, 4, 5, 6, 7, 0, 1]
        self.mirroring = 0
        self.irq_latch = 0
        self.irq_counter = 0
        self.irq_reload = False
        self.irq_enabled = False
        self.irq_line = False
        self._irq_raised = None
        self.next_line = PRERENDER_CLOCK    # the counter's next clock from the picture
        self._line = 0                      # which of the frame's clocks that is
        self.bus.map(0, 1, False)
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
                    if not self.v & A12 and self.t & A12 and not self._drawing():
                        self._clock_counter()
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
            self.bus.map(self.banks[6], self.banks[7], bool(self.bank_select & 0x40))
        elif address < 0xC000:
            if even:
                self.mirroring = value & 1
        elif address < 0xE000:
            if even:
                self.irq_latch = value
            else:
                self.irq_counter = 0
                self.irq_reload = True
        elif even:
            self.irq_enabled = False
            self.irq_line = False
        else:
            self.irq_enabled = True

    def _drawing(self):
        """Whether the PPU is fetching the picture now, rather than letting
        PPUADDR's address stand on its bus."""
        if not self.mask & PPUMASK_RENDERING:
            return False
        return self.now >= self.frame.start + PRERENDER_CLOCK - 260 / 3

    def _clock_counter(self):
        if self.irq_counter == 0 or self.irq_reload:
            self.irq_counter = self.irq_latch
            self.irq_reload = False
        else:
            self.irq_counter -= 1
        if self.irq_counter == 0 and self.irq_enabled and not self.irq_line:
            self.irq_line = True
            self._irq_raised = self.now

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
        """The line the picture is on at a cycle of the frame: -1 the
        pre-render line, 240 and on the vblank."""
        return int((cycle - PRERENDER_CLOCK + 260 / 3) // LINE_CYCLES) - 1

    def tiles(self, address, length):
        return bytes(self.vram[address:address + length])

    def count_calls(self, name):
        """Count from now how often the program comes to a label: read it
        back with calls_of."""
        self.calls[self.labels[name]] = 0

    def calls_of(self, name):
        return self.calls[self.labels[name]]

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
        """A digest of the RAM, less the stack, whose dead bytes depend on
        where an NMI landed. (What the sound engine keeps is not yet known,
        and is in it.)"""
        ram = self.ram
        return hashlib.sha1(bytes(ram[:0x100]) + bytes(ram[0x200:])).hexdigest()

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
            if mpu.processorCycles >= self.next_line:
                self._picture_line()
                continue
            if self.irq_line and not mpu.p & INTERRUPT:
                if self._irq_raised is not None:
                    self.frame.irqs.append((self._irq_raised - self.frame.start,
                                            mpu.processorCycles - self.frame.start))
                    self._irq_raised = None
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
            if pc >= PRG_START:
                if pc == self.idle and not self.nmi_depth and not self.stir_idle:
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

    def _picture_line(self):
        """The counter's clock from a line of the picture, if it is drawn."""
        if self.mask & PPUMASK_RENDERING:
            self._clock_counter()
        self._line += 1
        if self._line <= VISIBLE_LINES:
            self.next_line = self.frame.start + PRERENDER_CLOCK + self._line * LINE_CYCLES
        else:
            self.next_line = self.next_vblank + PRERENDER_CLOCK

    def _wait(self, limit):
        """Pass the time to the next vblank, or to the host's next turn."""
        mpu = self.mpu
        until = min(int(self.next_vblank) + 1, int(self.next_line) + 1, limit)
        if self.host is not None:
            until = min(until, self._host_at)
        if self.dmc_left:
            until = min(until, self.dmc_at)
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
        until = min(quiet, limit, self.next_line)
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
        self.next_line = self.frame.start + PRERENDER_CLOCK
        self._line = 0
        self.vblank_unread = True
        if self.ctrl & PPUCTRL_NMI:
            if self.nmi_depth:
                self.frame.lag = True
            else:
                self._nmi_at = mpu.processorCycles
            self.nmi_depth += 1
            mpu.nmi()
