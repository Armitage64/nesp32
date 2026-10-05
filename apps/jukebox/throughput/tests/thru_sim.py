"""The test ROM on py65, with a cycle-exact serial line to the host's code.

Time is in NES CPU cycles. Every $4017 read returns the line's level on the
cycle the lda samples it (its fourth), and every $4016 write reaches the
host's receiver on the sta's fourth cycle, as in the jukebox's harness
(../../tests). Unlike that one, each byte on the wire carries its own bit
length, since the host changes rate between a command and a block.

SimPort is the port the host's code (linktest.tester) drives. The host's
code is the one running; the console only advances inside the port's calls,
by exactly the time the call would take on the Stick.

Both lines can be given a slow rising edge, which is what the level
shifter's transistors do to them, so that the search has a limit to find.

Two loops are skipped rather than stepped, with the cycles they would have
taken: a start-bit hunt while the line rests at mark, in whole passes so
its phase against the next start bit is kept, and the dey / bne and
dex / bne delay loops.
"""

import bisect

from py65.devices.mpu6502 import MPU
from py65.memory import ObservableMemory

from linktest.rates import CONTROL, CPU_HZ, baud

PRG_START = 0x8000
PRG_SIZE = 0x8000
INES_HEADER = 16
PPUSTATUS = 0x2002
PPUADDR = 0x2006
PPUDATA = 0x2007
JOY1 = 0x4016
JOY2 = 0x4017
VBLANK = 0x80
READS_ABS = (0xAD, 0xCC, 0xEC, 0xCD, 0x4D)   # lda, cpy, cpx, cmp, eor: all read on their 4th cycle
STORES_ABS = (0x8D, 0x8C)        # sta, sty
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
MARK, SPACE = 1, 0
SLICE = 2000                    # cycles the console runs between host polls


def ms(value):
    return value * CPU_HZ / 1000.0


class Wire:
    """Host to NES: the host's transmitter as D0 sees it."""

    def __init__(self, rise_delay=0.0):
        self.rise_delay = rise_delay
        self.starts = []
        self.bits = []
        self.bytes = []
        self.busy_until = 0.0

    def send(self, data, at, bit, frame_bits=11):
        """Queue bytes back to back from cycle at. Returns when they end."""
        start = max(at, self.busy_until)
        for byte in data:
            self.starts.append(start)
            self.bits.append(bit)
            self.bytes.append(byte)
            start += bit * frame_bits
        self.busy_until = start
        return start

    def _driven(self, cycle):
        index = bisect.bisect_right(self.starts, cycle) - 1
        if index < 0:
            return MARK
        offset = (cycle - self.starts[index]) / self.bits[index]
        if offset < 1:
            return SPACE
        if offset < 9:
            return (self.bytes[index] >> int(offset - 1)) & 1
        return MARK

    def level(self, cycle):
        # Falls at once, rises rise_delay later: low unless it has been
        # driven high for that long. Two looks are enough while the delay is
        # shorter than a bit.
        if self._driven(cycle) == SPACE:
            return SPACE
        return self._driven(cycle - self.rise_delay) if self.rise_delay else MARK

    def quiet_until(self, cycle):
        """If the line rests at mark at this cycle, the cycle the next start
        bit falls (maybe never). None while a byte is still on it."""
        index = bisect.bisect_right(self.starts, cycle) - 1
        if index >= 0 and cycle < self.starts[index] + 9 * self.bits[index] + self.rise_delay + 1:
            return None
        return self.starts[index + 1] if index + 1 < len(self.starts) else float("inf")


class Tap:
    """NES to host: OUT0 as the host's receiver sees it."""

    def __init__(self, rise_delay=0.0):
        self.rise_delay = rise_delay
        self.times = [float("-inf")]
        self.levels = [SPACE]   # OUT0 is low (break) until the ROM sets it

    def write(self, cycle, level):
        if level == MARK:
            cycle += self.rise_delay
        elif self.times[-1] >= cycle:
            self.times.pop()    # fell again before the slow rise got there
            self.levels.pop()
        if level != self.levels[-1]:
            self.times.append(cycle)
            self.levels.append(level)

    def level(self, cycle):
        return self.levels[bisect.bisect_right(self.times, cycle) - 1]

    def decode(self, search_from, until, bit):
        """Bytes a UART with this bit length receives between two cycles.
        Returns (bytes, where to search from next)."""
        out = []
        while True:
            index = bisect.bisect_right(self.times, search_from)
            while index < len(self.times) and self.levels[index] != SPACE:
                index += 1
            if index == len(self.times):
                return out, search_from
            edge = self.times[index]
            if edge + 9.5 * bit > until:
                return out, search_from
            if self.level(edge + 0.5 * bit) != SPACE:
                search_from = edge      # a glitch, not a start bit
                continue
            byte = 0
            for k in range(8):
                byte |= self.level(edge + (1.5 + k) * bit) << k
            stop = edge + 9.5 * bit
            if self.level(stop) == MARK:
                out.append(byte)
            search_from = stop


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
        self.wire = wire or Wire()
        self.tap = tap or Tap()
        self.memory = ObservableMemory()
        for offset, byte in enumerate(rom[INES_HEADER:INES_HEADER + PRG_SIZE]):
            self.memory[PRG_START + offset] = byte
        self.prg = bytes(rom[INES_HEADER:INES_HEADER + PRG_SIZE])
        self.vram = bytearray(0x4000)
        self.ppu_address = 0
        self.ppu_latch = None
        self.pad = 0            # buttons held on controller 1 (proto.PAD_*)
        self._pad_shift = 0
        self._strobe = 0
        self.read_log = None    # set to a list to record (cycle, level) reads
        self.write_log = None   # and (cycle, level) writes
        self.memory.subscribe_to_read([PPUSTATUS], self._read_ppustatus)
        self.memory.subscribe_to_write([PPUADDR], self._write_ppuaddr)
        self.memory.subscribe_to_write([PPUDATA], self._write_ppudata)
        self.memory.subscribe_to_read([JOY2], self._read_joy2)
        self.memory.subscribe_to_read([JOY1], self._read_joy1)
        self.memory.subscribe_to_write([JOY1], self._write_joy1)
        self.mpu = MPU(memory=self.memory)
        self.mpu.pc = self.memory[0xFFFC] | self.memory[0xFFFD] << 8

    @property
    def now(self):
        return self.mpu.processorCycles

    def _read_ppustatus(self, address):
        self.ppu_latch = None
        return VBLANK           # always in vblank: waits for it end at once

    def _write_ppuaddr(self, address, value):
        if self.ppu_latch is None:
            self.ppu_latch = value
        else:
            self.ppu_address = (self.ppu_latch << 8 | value) & 0x3FFF
            self.ppu_latch = None

    def _write_ppudata(self, address, value):
        self.vram[self.ppu_address] = value
        self.ppu_address = (self.ppu_address + 1) & 0x3FFF

    def _read_joy2(self, address):
        mpu = self.mpu
        if self.memory[mpu.pc - 1] not in READS_ABS:
            raise AssertionError("$4017 read by opcode $%02X" % self.memory[mpu.pc - 1])
        cycle = mpu.processorCycles + 3
        level = self.wire.level(cycle)
        if self.read_log is not None:
            self.read_log.append((cycle, level))
        return 0x40 | (level ^ 1)   # the port's buffer inverts D0

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

    def _skip(self, until):
        """Jump over a loop that only passes time. True if it did."""
        mpu = self.mpu
        offset = mpu.pc - PRG_START
        if offset < 0:
            return False
        hunt = (HUNT_CYCLES if self.prg[offset:offset + 6] == HUNT
                else FAST_HUNT_CYCLES if self._at_fast_hunt(offset) else None)
        if hunt is not None:
            quiet = self.wire.quiet_until(mpu.processorCycles)
            if quiet is None:
                return False
            limit = min(quiet, until)
            passes = int((limit - mpu.processorCycles - 2 * hunt) // hunt)
            if passes <= 0:
                return False
            mpu.processorCycles += passes * hunt
            return True
        register = DELAY_LOOPS.get(self.prg[offset:offset + 3])
        if register is None:
            return False
        count = getattr(mpu, register)
        if count == 1:
            return False
        passes = (count - 1) & 0xFF     # from 0 the loop runs 256 times
        mpu.processorCycles += passes * DELAY_CYCLES
        setattr(mpu, register, 1)
        return True

    def _at_fast_hunt(self, offset):
        """True at the top of a fast receiver's hunt loop."""
        code = self.prg[offset:offset + 20]
        return (len(code) == 20
                and all(code[5 * look:5 * look + 3] in FAST_LOOKS
                        and code[5 * look + 3] == FAST_HUNT_BRANCHES[look] for look in range(4))
                and code[19] == 0xEC)       # the bne goes back to the top

    def run_until(self, cycle):
        mpu = self.mpu
        while mpu.processorCycles < cycle:
            if not self._skip(cycle):
                mpu.step()

    def call(self, name, a=0, x=0, y=0, limit=50_000_000):
        """Run one subroutine from a fresh stack. Returns the MPU."""
        mpu = self.mpu
        mpu.sp = 0xFD
        self.memory[0x01FE] = (RETURN_TRAP - 1) & 0xFF
        self.memory[0x01FF] = (RETURN_TRAP - 1) >> 8
        mpu.pc = self.labels[name]
        mpu.a, mpu.x, mpu.y = a, x, y
        start = mpu.processorCycles
        while mpu.pc != RETURN_TRAP:
            if not self._skip(start + limit):
                mpu.step()
            if mpu.processorCycles - start > limit:
                raise AssertionError("%s did not return" % name)
        return mpu

    def ram(self, start, count):
        return bytes(self.memory[start + offset] for offset in range(count))

    def screen_text(self, row, column, length):
        start = 0x2000 + 32 * row + column
        return bytes(self.vram[start:start + length]).decode("latin-1")


class SimPort:
    """The Stick's UART, on the simulated wire.

    clock_error runs the host's baud clock fast (+) or slow (-). to_nes, if
    given, sees every write and returns what really goes on the wire, to
    stage lost and damaged bytes. switch_junk is a byte the receiver finds
    in its buffer after every change of rate, as a real UART may.
    """

    def __init__(self, machine, clock_error=0.0, to_nes=None, switch_junk=None):
        self.switch_junk = switch_junk
        self.machine = machine
        self.clock_error = clock_error
        self.to_nes = to_nes
        self.received = []
        self.writes = []        # (baud, data), for the tests to look at
        self.bit = None
        self.baud = None
        self.set_baud(baud(CONTROL))    # as the Stick opens its UART

    def set_baud(self, baud):
        self._receive()
        if self.switch_junk is not None and self.bit is not None and baud != self.baud:
            self.received.append(self.switch_junk)
        self.baud = baud
        self.bit = CPU_HZ / (baud * (1.0 + self.clock_error))
        self.search_from = self.machine.now     # a byte in flight is lost

    def write(self, data):
        self.writes.append((self.baud, bytes(data)))
        if self.to_nes is not None:
            data = self.to_nes(self.baud, bytes(data))
        end = self.machine.wire.send(data, self.machine.now, self.bit)
        self.machine.run_until(end)

    def _receive(self):
        if self.bit is None:
            return                      # not open yet
        data, self.search_from = self.machine.tap.decode(
            self.search_from, self.machine.now, self.bit)
        self.received += data

    def read(self, count, timeout_ms):
        machine = self.machine
        deadline = machine.now + ms(timeout_ms)
        self._receive()
        while len(self.received) < count and machine.now < deadline:
            machine.run_until(min(deadline, machine.now + SLICE))
            self._receive()
        data = bytes(self.received[:count])
        del self.received[:count]
        return data

    def discard(self):
        self._receive()
        self.received = []

    def sleep_ms(self, duration):
        self.machine.run_until(self.machine.now + ms(duration))

    def ticks_ms(self):
        return int(self.machine.now * 1000 // CPU_HZ)
