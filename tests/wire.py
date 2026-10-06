"""The serial line between the console on py65 and the Stick's own code.

Time is in NES CPU cycles. Every $4017 read returns the line's level on the
cycle the lda samples it, and every $4016 write reaches the Stick's receiver
on the cycle the sta makes it (console.py passes both on). This is
nes-wiki's line model (tests/wire.py), which has it from nes-jukebox.

Wire is the Stick's transmitter as D0 sees it; Tap is OUT0 as the Stick's
UART receives it. Port is the UART that host/nesp.py's Stick drives.

link() joins a Console to a Stick: the console runs, and every SLICE cycles
the Stick is polled, as its link task would be. What the Stick writes goes
on the wire `turnaround` after the last byte of the request reached it.
"""

import bisect

from nesp_proto import NESP_CPU_HZ, NESP_PERIOD, NESP_TO_NES_BITS

MARK, SPACE = 1, 0
SLICE = 150                     # cycles between polls of the Stick's code


def ms(value):
    return value * NESP_CPU_HZ / 1000.0


class Wire:
    """Stick to console."""

    def __init__(self):
        self.starts = []
        self.bits = []
        self.bytes = []
        self.busy_until = 0.0

    def send(self, data, at, bit=NESP_PERIOD, frame_bits=NESP_TO_NES_BITS):
        """Queue bytes back to back from cycle `at`. Returns when they end."""
        start = max(at, self.busy_until)
        for byte in data:
            self.starts.append(start)
            self.bits.append(bit)
            self.bytes.append(byte)
            start += bit * frame_bits
        self.busy_until = start
        return start

    def level(self, cycle):
        index = bisect.bisect_right(self.starts, cycle) - 1
        if index < 0:
            return MARK
        offset = (cycle - self.starts[index]) / self.bits[index]
        if offset < 1:
            return SPACE
        if offset < 9:
            return (self.bytes[index] >> int(offset - 1)) & 1
        return MARK

    def quiet_until(self, cycle):
        """If the line rests at mark at this cycle, the cycle the next start
        bit falls (maybe never). None while a byte is still on it."""
        index = bisect.bisect_right(self.starts, cycle) - 1
        if index >= 0 and cycle < self.starts[index] + 9 * self.bits[index] + 1:
            return None
        return self.starts[index + 1] if index + 1 < len(self.starts) else float("inf")


class Tap:
    """Console to Stick."""

    def __init__(self):
        self.times = [float("-inf")]
        self.levels = [SPACE]   # OUT0 is low (break) until the ROM sets it

    def write(self, cycle, level):
        if level != self.levels[-1]:
            self.times.append(cycle)
            self.levels.append(level)

    def level(self, cycle):
        return self.levels[bisect.bisect_right(self.times, cycle) - 1]

    def decode(self, search_from, until, bit=NESP_PERIOD):
        """Bytes a UART with this bit length receives between two cycles, as
        (byte, the cycle its stop bit was sampled). Returns them and where
        to search from next."""
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
                out.append((byte, stop))
            search_from = stop


class Port:
    """The Stick's UART on the simulated line.

    turnaround: cycles from a request's last byte to the reply's first, a
    number or a function returning one. to_console, if given, sees every
    reply and returns what really goes on the wire (or None for nothing),
    to stage lost and damaged bytes. clock_error runs the Stick's baud
    clock fast (+) or slow (-).
    """

    def __init__(self, console, turnaround=ms(0.2), to_console=None, clock_error=0.0):
        self.console = console
        self.wire = Wire()
        self.tap = Tap()
        self.turnaround = turnaround
        self.to_console = to_console
        self.bit = NESP_PERIOD / (1.0 + clock_error)
        self.search_from = 0.0
        self.heard_at = 0.0
        self.received = []      # every run of bytes the UART took, for the tests
        self.sent = []          # (cycle, data) of every reply
        self.deaf = False       # True: the Stick is off, and reads nothing

    def read(self):
        data, self.search_from = self.tap.decode(self.search_from, self.console.now, self.bit)
        if not data or self.deaf:
            return None
        self.heard_at = data[-1][1]
        out = bytes(byte for byte, _ in data)
        self.received.append(out)
        return out

    def write(self, data):
        data = bytes(data)
        if self.to_console is not None:
            data = self.to_console(data)
            if data is None:
                return
        delay = self.turnaround() if callable(self.turnaround) else self.turnaround
        at = max(self.heard_at + delay, self.console.now)
        self.sent.append((at, data))
        self.wire.send(data, at, self.bit)


def link(console, stick_factory, **port_options):
    """Join a Console to a Stick made by stick_factory(port). Returns
    (stick, port)."""
    port = Port(console, **port_options)
    stick = stick_factory(port)
    console.joy2_level = port.wire.level
    console.joy2_quiet_until = port.wire.quiet_until
    console.on_joy1 = port.tap.write
    console.host = stick.poll
    console.host_every = SLICE
    return stick, port
