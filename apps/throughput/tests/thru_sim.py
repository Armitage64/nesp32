"""The test ROM on py65, joined by a cycle-exact serial line to a nesp32.

The nesp32's end is its own firmware: the link and the RAW service, built
for this computer (conftest.py) and driven through nesp32's host/nesp.py.
Only the hardware under them is a stand-in: its UART is the Port of the
jukebox's line model (../jukebox/tests/wire.py), which carries a run of RAW's at
whatever rate the nesp32 set.

Time is in NES CPU cycles. Every $4017 read returns the line's level on the
cycle the instruction samples it (its fourth), and every $4016 write
reaches the nesp32's receiver on the cycle the store makes it. A vblank
comes every 29780.5 cycles, and with it an NMI if the ROM has them on; the
handler runs to its rti in one go. The nesp32's code is polled every SLICE
cycles, as its link task would be.

Both lines can be given a slow rising edge, which is what the level
shifter's transistors do to them, so that the search has a limit to find.

Loops that only pass time are skipped rather than stepped, with the cycles
they would have taken, and never past a vblank or a poll: the wait for the
next NMI, a start-bit hunt while the line rests at mark (in whole passes,
so its phase against the next start bit is kept), and the dey / bne and
dex / bne delay loops.
"""

import math

from py65.devices.mpu6502 import MPU
from py65.memory import ObservableMemory

import nesp
import nesp_proto as p
from wire import SLICE, Port, Tap, Wire, ms

__all__ = ["Bench", "Machine", "SlowTap", "SlowWire", "ms"]

FRAME_CYCLES = 29780.5
VBLANK_CYCLES = 20 * 341 / 3    # 2273: an NMI's PPU writes must be over by then
PRG_START = 0x8000
PRG_SIZE = 0x8000
INES_HEADER = 16
PPUCTRL, PPUMASK, PPUSTATUS = 0x2000, 0x2001, 0x2002
PPUADDR, PPUDATA = 0x2006, 0x2007
JOY1, JOY2 = 0x4016, 0x4017
PPUCTRL_NMI = 0x80
BACKGROUND = 0x08
VBLANK = 0x80
RTI = 0x40
PAD_A, PAD_B, PAD_SELECT, PAD_START = 0x80, 0x40, 0x20, 0x10
PAD_UP = 0x08
PORT_IDLE = 0x40                # what the port's unused bits read
READS_ABS = (0xAD, 0xCC, 0xEC, 0xCD, 0x4D)   # lda, cpy, cpx, cmp, eor: all read on their 4th cycle
STORES_ABS = (0x8D, 0x8C)       # sta, sty
# The link's wait for a start bit (nesp32's nes/lib/gen_link.py).
HUNT = bytes((0xAD, 0x17, 0x40, 0x4A, 0x90, 0xFA))   # lda $4017 / lsr / bcc
HUNT_CYCLES = 9
# The block receivers' hunt: cpy (or cpx, or cmp) $4017 / beq, three times,
# then the same with a bne back.
FAST_LOOKS = (bytes((0xCC, 0x17, 0x40)), bytes((0xEC, 0x17, 0x40)), bytes((0xCD, 0x17, 0x40)))
FAST_HUNT_BRANCHES = (0xF0, 0xF0, 0xF0, 0xD0)
FAST_HUNT_CYCLES = 25
DELAY_LOOPS = {bytes((0x88, 0xD0, 0xFD)): "y", bytes((0xCA, 0xD0, 0xFD)): "x"}
DELAY_CYCLES = 5
RETURN_TRAP = 0xFFF0


class SlowWire(Wire):
    """nesp32 to console, with a rising edge that comes late."""

    def __init__(self, rise_delay=0.0):
        super().__init__()
        self.rise_delay = rise_delay

    def level(self, cycle):
        # Falls at once, rises rise_delay later: low unless it has been
        # driven high for that long. Two looks are enough while the delay is
        # shorter than a bit.
        level = super().level
        if not level(cycle):
            return 0
        return level(cycle - self.rise_delay) if self.rise_delay else 1

    def quiet_until(self, cycle):
        return super().quiet_until(cycle - self.rise_delay)


class SlowTap(Tap):
    """Console to nesp32, likewise."""

    def __init__(self, rise_delay=0.0):
        super().__init__()
        self.rise_delay = rise_delay

    def write(self, cycle, level):
        if level:
            cycle += self.rise_delay
        elif self.times[-1] >= cycle:
            self.times.pop()    # fell again before the slow rise got there
            self.levels.pop()
        super().write(cycle, level)


def load_labels(path):
    labels = {}
    with open(path) as handle:
        for line in handle:
            _, address, name = line.split()
            labels[name.lstrip(".")] = int(address, 16)
    return labels


class Machine:
    def __init__(self, rom_path, labels_path, wire=None, tap=None):
        with open(rom_path, "rb") as handle:
            rom = handle.read()
        self.labels = load_labels(labels_path)
        self.wire = wire or SlowWire()
        self.tap = tap or SlowTap()
        self.memory = ObservableMemory()
        self.prg = bytes(rom[INES_HEADER:INES_HEADER + PRG_SIZE])
        for offset, byte in enumerate(self.prg):
            self.memory[PRG_START + offset] = byte
        self.vram = bytearray(0x4000)
        self.ppu_address = 0
        self.ppu_latch = None
        self.ctrl = self.mask = 0
        self.pad = 0            # buttons held on controller 1 (PAD_*)
        self._pad_shift = 0
        self._strobe = 0
        self.port_bits = PORT_IDLE
        self.read_log = None    # set to a list to record (cycle, level) reads
        self.write_log = None   # and (cycle, level) writes
        self.frames = 0         # vblanks so far
        self.next_vblank = FRAME_CYCLES
        self.frame_start = 0.0
        self.in_nmi = False
        self.late_write = 0.0   # the latest an NMI wrote to the PPU, in cycles after its vblank
        self.host = None        # called every SLICE cycles
        self._host_at = 0
        memory = self.memory
        memory.subscribe_to_write([PPUCTRL], self._write_ctrl)
        memory.subscribe_to_write([PPUMASK], self._write_mask)
        memory.subscribe_to_read([PPUSTATUS], self._read_ppustatus)
        memory.subscribe_to_write([PPUADDR], self._write_ppuaddr)
        memory.subscribe_to_write([PPUDATA], self._write_ppudata)
        memory.subscribe_to_read([JOY2], self._read_joy2)
        memory.subscribe_to_read([JOY1], self._read_joy1)
        memory.subscribe_to_write([JOY1], self._write_joy1)
        self.mpu = MPU(memory=memory)
        self.mpu.pc = memory[0xFFFC] | memory[0xFFFD] << 8

    @property
    def now(self):
        return self.mpu.processorCycles

    # --- the PPU, as much of it as the ROM uses --------------------------------

    def _write_ctrl(self, address, value):
        self.ctrl = value

    def _write_mask(self, address, value):
        self.mask = value

    def _read_ppustatus(self, address):
        self.ppu_latch = None
        return VBLANK           # always in vblank: reset's waits for it end at once

    def _write_ppuaddr(self, address, value):
        if self.ppu_latch is None:
            self.ppu_latch = value
        else:
            self.ppu_address = (self.ppu_latch << 8 | value) & 0x3FFF
            self.ppu_latch = None

    def _write_ppudata(self, address, value):
        if self.in_nmi:
            self.late_write = max(self.late_write, self.now + 3 - self.frame_start)
        elif self.mask & BACKGROUND:
            raise AssertionError("PPUDATA written outside the NMI with the picture on")
        self.vram[self.ppu_address] = value
        self.ppu_address = (self.ppu_address + 1) & 0x3FFF

    # --- the two controller ports ----------------------------------------------

    def _read_joy2(self, address):
        mpu = self.mpu
        if self.memory[mpu.pc - 1] not in READS_ABS:
            raise AssertionError("$4017 read by opcode $%02X" % self.memory[mpu.pc - 1])
        cycle = mpu.processorCycles + 3
        level = self.wire.level(cycle)
        if self.read_log is not None:
            self.read_log.append((cycle, level))
        return self.port_bits | (level ^ 1)     # the port's buffer inverts D0

    def _read_joy1(self, address):
        # While OUT0 is high the controller keeps loading its buttons and
        # shows the first (A). Low, each read shifts the next one out.
        if self._strobe:
            return 0x40 | (self.pad >> 7)
        bit = self._pad_shift >> 7
        self._pad_shift = (self._pad_shift << 1 | 1) & 0xFF
        return 0x40 | bit

    def _write_joy1(self, address, value):
        mpu = self.mpu
        if self.memory[mpu.pc - 1] not in STORES_ABS:
            raise AssertionError("$4016 write by opcode $%02X" % self.memory[mpu.pc - 1])
        if self._strobe and not value & 1:
            self._pad_shift = self.pad  # what was held as the loading stopped
        self._strobe = value & 1
        cycle = mpu.processorCycles + 3
        self.tap.write(cycle, value & 1)
        if self.write_log is not None:
            self.write_log.append((cycle, value & 1))

    # --- running ---------------------------------------------------------------

    def _vblank(self):
        mpu = self.mpu
        self.frames += 1
        self.frame_start = self.next_vblank
        self.next_vblank += FRAME_CYCLES
        if not self.ctrl & PPUCTRL_NMI:
            return
        self.in_nmi = True
        mpu.nmi()
        while True:
            returning = self.memory[mpu.pc] == RTI
            mpu.step()
            if returning:
                break
        self.in_nmi = False

    def _skip(self):
        """Jump over a loop that only passes time. True if it did."""
        mpu = self.mpu
        now = mpu.processorCycles
        limit = min(self.next_vblank, self._host_at if self.host is not None else math.inf)
        offset = mpu.pc - PRG_START
        if offset < 0:
            return False
        if (mpu.pc == self.labels["main_wait"]
                and self.byte("frame_count") == self.byte("served_frame")
                and self.ctrl & PPUCTRL_NMI and limit < math.inf):
            if limit <= now:
                return False
            mpu.processorCycles = math.ceil(limit)
            return True
        hunt = (HUNT_CYCLES if self.prg[offset:offset + 6] == HUNT
                else FAST_HUNT_CYCLES if self._at_fast_hunt(offset) else None)
        if hunt is not None:
            quiet = self.wire.quiet_until(now)
            if quiet is None:
                return False
            passes = int((min(quiet, limit) - now - 2 * hunt) // hunt)
            if passes <= 0:
                return False
            mpu.processorCycles += passes * hunt
            return True
        register = DELAY_LOOPS.get(self.prg[offset:offset + 3])
        if register is None:
            return False
        # From 0 the loop runs 256 times. Its last pass is stepped.
        passes = (getattr(mpu, register) - 1) & 0xFF
        if limit < math.inf:
            passes = min(passes, int((limit - now) // DELAY_CYCLES))
        if passes <= 0:
            return False
        mpu.processorCycles += passes * DELAY_CYCLES
        setattr(mpu, register, (getattr(mpu, register) - passes) & 0xFF)
        return True

    def _at_fast_hunt(self, offset):
        """True at the top of a fast receiver's hunt loop."""
        code = self.prg[offset:offset + 20]
        return (len(code) == 20
                and all(code[5 * look:5 * look + 3] in FAST_LOOKS
                        and code[5 * look + 3] == FAST_HUNT_BRANCHES[look] for look in range(4))
                and code[19] == 0xEC)       # the bne goes back to the top

    def _advance(self):
        mpu = self.mpu
        if mpu.processorCycles >= self.next_vblank:
            self._vblank()
            return
        if self.host is not None and mpu.processorCycles >= self._host_at:
            self._host_at = mpu.processorCycles + SLICE
            self.host()
        if not self._skip():
            mpu.step()

    def run(self, frames=1):
        """Run until this many more vblanks have passed."""
        target = self.frames + frames
        while self.frames < target:
            self._advance()

    def run_until(self, condition, frames=600):
        """Run a frame at a time until condition() is true. Returns how many
        frames that took; raises if it never is."""
        for count in range(frames):
            if condition():
                return count
            self.run(1)
        raise AssertionError("still waiting after %d frames:\n%s" % (frames, self.screen()))

    def call(self, name, a=0, x=0, y=0, limit=50_000_000):
        """Run one subroutine from a fresh stack, with no vblanks and no
        nesp32. Returns the MPU."""
        mpu = self.mpu
        mpu.sp = 0xFD
        self.memory[0x01FE] = (RETURN_TRAP - 1) & 0xFF
        self.memory[0x01FF] = (RETURN_TRAP - 1) >> 8
        mpu.pc = self.labels[name]
        mpu.a, mpu.x, mpu.y = a, x, y
        start = mpu.processorCycles
        self.next_vblank = math.inf
        while mpu.pc != RETURN_TRAP:
            if not self._skip():
                mpu.step()
            if mpu.processorCycles - start > limit:
                raise AssertionError("%s did not return" % name)
        return mpu

    # --- what it holds ---------------------------------------------------------

    def byte(self, name, offset=0):
        return self.memory[self.labels[name] + offset]

    def word(self, name):
        return self.byte(name) | self.byte(name, 1) << 8

    def ram(self, start, count):
        return bytes(self.memory[start + offset] for offset in range(count))

    def nametable(self):
        return bytes(self.vram[0x2000:0x2400])

    def text(self, row, column=0, length=32):
        start = 0x2000 + 32 * row + column
        return bytes(self.vram[start:start + length]).decode("latin-1")

    def screen(self):
        """The picture as text, a line a row; a tile that is not a
        character shows as '^'."""
        return "\n".join("".join(char if " " <= char < "\x7f" else "^"
                                 for char in self.text(row)).rstrip() for row in range(30))


class Bench:
    """The ROM and a nesp32 with the line between them.

    to_nes_rise and from_nes_rise are how late each line's rising edges
    come, in cycles. blocks, if given, is how many a trial has, in place of
    the ROM's own. The rest are the Port's: turnaround, to_console,
    clock_error. attached=False leaves the port with nothing on it.
    """

    def __init__(self, rom, to_nes_rise=0.0, from_nes_rise=0.0, blocks=None, attached=True,
                 **port_options):
        self.machine = machine = Machine(*rom, wire=SlowWire(to_nes_rise),
                                         tap=SlowTap(from_nes_rise))
        if blocks is not None:
            machine.memory[machine.labels["trial_blocks"]] = blocks
        self.port = Port(machine, **port_options)
        self.port.wire, self.port.tap = machine.wire, machine.tap
        # Everything the nesp32's UART took: (the cycle it was read, the
        # UART's rate then in cycles a bit, the bytes).
        self.heard = []
        read = self.port.read

        def hear():
            data = read()
            if data:
                self.heard.append((machine.now, self.port.period, data))
            return data
        self.port.read = hear
        self.stick = None
        if attached:
            self.attach()

    def attach(self):
        """A nesp32 on the port, which knows nothing of the console. Its
        UART is at the link's rate."""
        self.port.line_rate(p.NESP_PERIOD)
        self.port.rates.pop()
        self.stick = nesp.Stick(self.port)
        self.machine.host = self.stick.poll

    def detach(self):
        self.stick = None
        self.machine.host = None

    def in_a_run(self, cycle):
        """True if the UART's rate was a run's at a cycle, or had just been."""
        changes = [at for at, _ in self.port.rates] + [math.inf]
        return any(changed < cycle <= back + 2 * SLICE
                   for changed, back in zip(changes[0::2], changes[1::2]))

    def requests(self, since=0, until=math.inf):
        """What the UART heard between two cycles with the line the link's,
        as the requests in it, (service, op, payload) each, and the number
        of bytes that were part of none."""
        data = b"".join(data for cycle, _, data in self.heard
                        if since <= cycle <= until and not self.in_a_run(cycle))
        out, stray, at = [], 0, 0
        while at < len(data):
            total = p.NESP_OVERHEAD + data[at + 4] if at + 4 < len(data) else 0
            frame = data[at:at + total]
            if (total and data[at] == p.NESP_REQUEST_MARKER and len(frame) == total
                    and nesp.checks(frame[1:-2]) == frame[-2:]):
                out.append((frame[1], frame[2], frame[5:-2]))
                at += total
            else:
                stray += 1
                at += 1
        return out, stray

    def press_a(self):
        """Button A on the nesp32."""
        self.stick.event(p.NESP_EVENT_BUTTON_A)

    def press_start(self, frames=3, button=PAD_START):
        """Start on controller 1, held for some frames."""
        self.machine.pad = button
        self.machine.run(frames)
        self.machine.pad = 0

    def press_sweep(self, frames=3):
        """Up on controller 1: a sweep."""
        self.press_start(frames, PAD_UP)
