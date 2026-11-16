"""River City Ransom's ROM on py65, with as much of an NES round it as the
ROM uses.

Bubble Bobble's console (apps/bubblebobble/tests/console.py), with the
cartridge an MMC3 as Jackal's is, and the MMC3's scanline counter, which
River City Ransom splits the screen with. py65 is a plain 6502. This adds:

- A frame clock. A vblank comes every 29780.5 CPU cycles, and with it an
  NMI if the ROM has them on. The game's logic runs in its main loop, once
  every two NMIs; the NMI writes to the PPU and sets up the IRQ.
- The MMC3's IRQ. Its counter is clocked once a line while the picture is
  on, on the line before the picture and each of its 240, a little after
  the line's 256th dot, when the sprites' patterns are fetched from $1000.
  When a clock leaves it at 0 with the IRQ on, the IRQ is asserted until
  $E000 is written. The game's first IRQ, line 29's, splits off the HUD
  and runs the sound engine; its second splits off the text at the foot.
- The PPU's registers as far as the game's logic can tell: the vblank flag
  of PPUSTATUS, and PPUADDR and PPUDATA writing to pattern tables,
  nametables (mirrored as the MMC3 is told) and palettes that the tests
  can read back, and reading them back through the PPU's buffer, as the
  game's queue of PPU writes can. Nothing is drawn.
- OAM filled by the DMA at $4014, with the cycles it takes.
- Controllers 1 and 2 as shift registers loaded from `pads`. Port 2 can be
  given to a serial line instead (joy2_level, on_joy1).
- The cartridge, as the ROM's header says: an MMC3, 8 KB banks picked by
  R6 and R7 (the game always picks a pair, 2n and 2n+1), the last 16 KB
  fixed, CHR banks kept for the tests to look at, and 8 KB of PRG RAM at
  $6000, there while $A001 has it on.

Time is in CPU cycles. The game's waits for an interrupt (a load of a
byte and a branch back to it, which only an NMI or an IRQ can end), the
reset's waits for the vblank flag, and the serial receiver's looks at a
line that rests at mark are skipped rather than stepped. Each frame's
record says how many cycles the game was busy for.

Two consoles do not share a clock. `frame_cycles` sets how long this one's
frames are, and run_until runs it to a cycle of its own, so a test can run
two side by side, a slice at a time, with one a little fast.
"""

import hashlib
import math

from py65.devices.mpu6502 import MPU

FRAME_CYCLES = 29780.5
LINE_DOTS = 341
VBLANK_CYCLES = 20 * LINE_DOTS / 3  # 2273: the vblank flag stands this long
# Where in a line the MMC3's counter is clocked: the sprites' first fetch
# from $1000, a little after dot 256.
CLOCK_DOT = 260
PRG_START = 0x8000
MMC3_BANK = 0x2000
INES_HEADER = 16
PRG_RAM_START = 0x6000
PRG_RAM_SIZE = 0x2000
RAM_SIZE = 0x800

PPUCTRL, PPUMASK, PPUSTATUS = 0x2000, 0x2001, 0x2002
PPUSCROLL, PPUADDR, PPUDATA = 0x2005, 0x2006, 0x2007
OAMDMA, JOY1, JOY2 = 0x4014, 0x4016, 0x4017
PPUCTRL_NMI, PPUCTRL_DOWN = 0x80, 0x04
PPUMASK_RENDER = 0x18
VBLANK_FLAG = 0x80
DMA_CYCLES = 513
RTI = 0x40
# The NMI with NMI_MODE 0 (the game's wait for one, $FC60) does not return
# with an RTI: it takes its return address off the stack and returns from
# the wait's caller. Its first PLA ends the NMI.
NMI_WAIT_END = 0xFF6D
INTERRUPT = 0x04                # the 6502's I flag

PAD_A, PAD_B, PAD_SELECT, PAD_START = 0x80, 0x40, 0x20, 0x10
PAD_UP, PAD_DOWN, PAD_LEFT, PAD_RIGHT = 0x08, 0x04, 0x02, 0x01

APU_STATUS = 0x4015

# lda $2002 / bpl, and bit $2002 / bpl: waits for a vblank.
WAIT_VBLANK = (bytes((0xAD, 0x02, 0x20, 0x10, 0xFB)), bytes((0x2C, 0x02, 0x20, 0x10, 0xFB)))
# A wait for an interrupt: lda abs (and cmp #, or and #), and a branch back
# to the lda.
LDA_ABS, LDA_ZP = 0xAD, 0xA5
CMP_IMM, AND_IMM = 0xC9, 0x29
BRANCHES = {0x10: ("N", False), 0x30: ("N", True), 0x90: ("C", False), 0xB0: ("C", True),
            0xD0: ("Z", False), 0xF0: ("Z", True)}
# The serial receiver's wait for a start bit: four looks, each bit $4017 /
# bne, then dex / bne, 29 cycles in all. X counts those.
HUNT = bytes((0x2C, 0x17, 0x40, 0xD0))
HUNT_LOOKS = 4
HUNT_REST = (0xCA, 0xD0)
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
        self.busy = 0           # cycles not spent waiting for an interrupt
        self.irqs = []          # the cycle in the frame each IRQ was taken at
        self.pads = (0, 0)


class Bus:
    """The CPU's address space. py65 reads and writes it by index."""

    def __init__(self, console, prg):
        self.console = console
        self.ram = bytearray(RAM_SIZE)
        self.prg_ram = bytearray(PRG_RAM_SIZE)
        self.prg_ram_on = False
        self.prg = prg
        last = len(prg) // MMC3_BANK - 1
        self.windows = [0, MMC3_BANK, (last - 1) * MMC3_BANK, last * MMC3_BANK]
        self.written = None         # a bytearray: the RAM written since (watch_writes)

    def __getitem__(self, address):
        if address >= PRG_START:
            return self.prg[self.windows[(address - PRG_START) >> 13] + (address & 0x1FFF)]
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

    def map(self, r6, r7):
        banks = len(self.prg) // MMC3_BANK
        self.windows[0] = (r6 % banks) * MMC3_BANK
        self.windows[1] = (r7 % banks) * MMC3_BANK

    def bank_at(self, address):
        """The 16 KB bank at an address, as the game numbers them: the
        file's last is the fixed one."""
        if address >= 0xC000:
            return len(self.prg) // 0x4000 - 1
        return self.windows[0] // 0x4000


class Console:
    def __init__(self, rom_path, labels_path=None, frame_cycles=FRAME_CYCLES):
        with open(rom_path, "rb") as handle:
            rom = handle.read()
        self.labels = {}
        for path in ([labels_path] if isinstance(labels_path, str) else labels_path or []):
            for name, value in load_labels(path).items():
                self.labels.setdefault(name, value)
        prg_size = (rom[4] | (rom[9] & 0x0F) << 8) * 0x4000 if rom[7] & 0x0C == 0x08 \
            else rom[4] * 0x4000
        self.prg = bytes(rom[INES_HEADER:INES_HEADER + prg_size])
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
        self.frames = []
        self.frame = Frame(0.0)     # the time before the first vblank
        self.frame_cycles = frame_cycles
        self.next_vblank = frame_cycles
        self.interrupts = []        # the handlers under way: "N" or "I", innermost last
        self._nmi_at = 0
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
        self.watches = {}           # address: a function called with the console there (watch)
        self._waits = {}            # pc: the wait for an interrupt there, or None
        # The MMC3. At power-on its registers are whatever they are; these
        # are some of no use, which the reset has to put right.
        self.bank_select = 0
        self.banks = [0, 2, 4, 5, 6, 7, 0, 1]
        self.mirroring = 0
        self.irq_latch = 0
        self.irq_counter = 0
        self.irq_reload = False
        self.irq_enabled = False
        self.irq_line = False
        self.next_clock = float("inf")
        self._clock_line = 0
        self._schedule_clocks(0.0)
        self.mpu = MPU(memory=self.bus)
        self.mpu.pc = self.bus[0xFFFC] | self.bus[0xFFFD] << 8

    @property
    def in_nmi(self):
        return "N" in self.interrupts

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
                at = self._mirror(self.v)
                if at >= 0x3F00:
                    value = self.vram[at]
                    self.read_buffer = self.vram[self._mirror(self.v & 0x2FFF)]
                else:
                    value = self.read_buffer
                    self.read_buffer = self.vram[at]
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
        even = not address & 1
        if address < 0xA000:
            if even:
                self.bank_select = value
            else:
                self.banks[self.bank_select & 7] = value
                self.bus.map(self.banks[6], self.banks[7])
        elif address < 0xC000:
            if even:
                self.mirroring = value & 1
            else:
                self.bus.prg_ram_on = value & 0xC0 == 0x80
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

    def _step_v(self):
        self.v = (self.v + (32 if self.ctrl & PPUCTRL_DOWN else 1)) & 0x7FFF

    def _mirror(self, address):
        address &= 0x3FFF
        if address >= 0x3F00:
            address = 0x3F00 | (address & 0x1F)
            if address & 0x13 == 0x10:
                address &= ~0x10
            return address
        if address >= 0x2000:
            address = 0x2000 | (address & 0x0FFF)
            if self.mirroring:      # horizontal: $2400 is $2000, $2C00 is $2800
                return address & ~0x0400
            return address & ~0x0800    # vertical: $2800 is $2000
        return address

    def _read_pad(self, port):
        if self._strobe:
            return self.pads[port] >> 7
        bit = self._pad_shift[port] >> 7
        self._pad_shift[port] = (self._pad_shift[port] << 1 | 1) & 0xFF
        return bit

    # --- the scanline counter ----------------------------------------------------

    def _schedule_clocks(self, start):
        """The times of this frame's clocks of the counter: the line before
        the picture (the 20th after the vblank's) and the picture's 240."""
        self._clock_times = [start + ((20 + line) * LINE_DOTS + CLOCK_DOT) / 3
                             for line in range(241)]
        self._clock_line = 0
        self.next_clock = self._clock_times[0]

    def _clock(self):
        self._clock_line += 1
        self.next_clock = (self._clock_times[self._clock_line]
                           if self._clock_line < len(self._clock_times) else float("inf"))
        if not self.mask & PPUMASK_RENDER:
            return
        if self.irq_counter == 0 or self.irq_reload:
            self.irq_counter = self.irq_latch
            self.irq_reload = False
        else:
            self.irq_counter -= 1
        if self.irq_counter == 0 and self.irq_enabled:
            self.irq_line = True

    # --- what the tests look at --------------------------------------------------

    def byte(self, name, offset=0):
        return self.bus[self.labels[name] + offset]

    def tiles(self, address, length):
        return bytes(self.vram[self._mirror(address + at)] for at in range(length))

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

    def watch(self, name, function):
        """Call a function with the console each time the program comes to
        a label, or an address, before the instruction there."""
        self.watches[self.labels.get(name, name)] = function

    def marks_of(self, name):
        return self.marks[self.labels.get(name, name)]

    # What keeps the frames' time and not the game's: the scratch at
    # $00-$13, IRQ_SPLIT ($14), the netplay's link's zero page ($15-$17,
    # $F3, $F9-$FA), the background's columns and colours as far as they
    # are drawn, which is as far as the PPU's queue has had room for
    # ($1A-$1C, $24-$26, $2A-$2B, $0585-$058D, and the colours' buffer at
    # $058E-$060D, which only the queue's filling reads), the stack, the NMI's queue
    # of writes to the PPU ($0545-$0584 and its two ends, $06B6-$06B7), the
    # HUD's redraw ($0517), what the NMI last put in place of the main
    # thread's asks: a palette ($051B-$051C) and the sprites' banks
    # ($0525-$0528), the most NMIs a pass took ($06D3), the PPU's shadows
    # ($F7-$F8), the banks as the interrupts saw them ($FB-$FF) and the
    # sound engine's memory ($0700-$07FF). And one bit: $3E's bit 3, a new
    # palette for the NMI to upload, which the main thread sets and the
    # NMI clears, and nothing else reads (UNKEPT_BITS).
    UNKEPT = ([(0x00, 0x18), (0x1A, 0x1D), (0x24, 0x27), (0x2A, 0x2C), (0xF3, 0xF4), (0xF7, 0x100),
               (0x100, 0x200), (0x517, 0x518), (0x51B, 0x51D), (0x525, 0x529), (0x545, 0x60E),
               (0x6B6, 0x6B8), (0x6D3, 0x6D4), (0x700, 0x800)])
    UNKEPT_BITS = ((0x3E, 0x08),)

    def kept(self):
        """The bytes of the RAM the game's logic keeps (UNKEPT left out)."""
        ram = bytearray(self.ram)
        for start, end in self.UNKEPT:
            ram[start:end] = bytes(end - start)
        for address, bits in self.UNKEPT_BITS:
            ram[address] &= ~bits & 0xFF
        return bytes(ram)

    def state(self):
        return hashlib.sha1(self.kept()).hexdigest()

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
            if mpu.processorCycles >= self.next_clock:
                self._clock()
                continue
            if self.irq_line and not mpu.p & INTERRUPT:
                self.interrupts.append("I")
                self.frame.irqs.append(mpu.processorCycles - self.frame.start)
                mpu.irq()
                continue
            if self.host is not None and mpu.processorCycles >= self._host_at:
                self._host_at = mpu.processorCycles + self.host_every
                self.host()
            pc = mpu.pc
            if pc in self.calls:
                self.calls[pc] += 1
            if pc in self.marks:
                self.marks[pc].append((len(self.frames), mpu.processorCycles - self.frame.start))
            if pc in self.watches:
                self.watches[pc](self)
            if pc >= PRG_START:
                opcode = bus[pc]
                if opcode == RTI:
                    if self.interrupts:
                        kind = self.interrupts.pop()
                        if kind == "N":
                            self.frame.nmi_cycles = mpu.processorCycles + 6 - self._nmi_at
                elif pc == NMI_WAIT_END and self.interrupts and self.interrupts[-1] == "N":
                    self.interrupts.pop()
                    self.frame.nmi_cycles = mpu.processorCycles - self._nmi_at
                elif opcode in BRANCHES and bus[pc + 1] == 0xFE:
                    if self._branch_taken(opcode):
                        self._wait(limit)
                        continue
                elif opcode in (LDA_ABS, LDA_ZP, 0x2C):
                    if self._waiting(pc):
                        self._wait(limit)
                        continue
                    if opcode == HUNT[0] and self._skip_hunt(pc, limit):
                        continue
            mpu.step()

    def _wait_at(self, pc):
        """The wait for an interrupt at pc, if one is: (address, mask,
        compare, flag, taken) or ("vblank",)."""
        if pc in self._waits:
            return self._waits[pc]
        bus = self.bus
        wait = None
        code = bus.code(pc, 7)
        if code[:5] in WAIT_VBLANK:
            wait = ("vblank",)
        elif code[0] in (LDA_ABS, LDA_ZP):
            size = 3 if code[0] == LDA_ABS else 2
            address = code[1] | (code[2] << 8 if size == 3 else 0)
            rest = code[size:]
            op = None
            if rest[0] in (CMP_IMM, AND_IMM):
                op = (rest[0], rest[1])
                rest = rest[2:]
            branch_at = pc + size + (2 if op else 0)
            if rest[0] in BRANCHES:
                target = (branch_at + 2 + ((rest[1] ^ 0x80) - 0x80)) & 0xFFFF
                # Only RAM that the main thread does not write while it waits.
                if target == pc and address < 0x0800:
                    wait = (address, op) + BRANCHES[rest[0]]
        # Only code in the fixed bank is the same whenever it is reached.
        if pc >= 0xC000:
            self._waits[pc] = wait
        return wait

    def _waiting(self, pc):
        """Whether the program is at a wait for an interrupt that will go
        round again."""
        wait = self._wait_at(pc)
        if wait is None:
            return False
        if wait[0] == "vblank":
            return not self.vblank_unread
        address, op, flag, taken = wait
        value = self.ram[address]
        if op is None:
            flags = {"N": value >= 0x80, "Z": value == 0, "C": None}
        elif op[0] == AND_IMM:
            value &= op[1]
            flags = {"N": value >= 0x80, "Z": value == 0, "C": None}
        else:
            diff = (value - op[1]) & 0xFF
            flags = {"N": diff >= 0x80, "Z": value == op[1], "C": value >= op[1]}
        if flags[flag] is None:
            return False
        return flags[flag] == taken

    def _branch_taken(self, opcode):
        """Whether a branch to itself, a wait for an interrupt, is taken."""
        flag, taken = BRANCHES[opcode]
        p = self.mpu.p
        bit = {"N": p & 0x80, "Z": p & 0x02, "C": p & 0x01}[flag]
        return bool(bit) == taken

    def _wait(self, limit):
        """Pass the time to the next event that might end a wait: the next
        vblank, the counter's next clock, or the host's next turn."""
        mpu = self.mpu
        until = min(self.next_vblank, self.next_clock, limit)
        if self.host is not None:
            until = min(until, self._host_at)
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
        self._schedule_clocks(self.next_vblank)
        self.next_vblank += self.frame_cycles
        self.vblank_unread = True
        if self.ctrl & PPUCTRL_NMI:
            if not self.in_nmi:
                self._nmi_at = mpu.processorCycles
            self.interrupts.append("N")
            mpu.nmi()
