"""A cycle-exact model of the controller-port serial line.

Time is in NES CPU cycles. The host's UART clock is independent of the
console's, so each direction has its own bit length, and tests can skew
either one to model baud error.

HostToNes is the host's transmitter as the NES sees it on D0: the line level
at any cycle. Each byte carries its own bit length, since a host changes
its UART's rate to send sampled sound. NesToHost is the host's receiver: it takes OUT0 levels as the
NES writes them and decodes bytes the way a UART does, finding the falling
edge of a start bit and sampling each bit at its center.
"""

import bisect

CPU_HZ = 1789773.0  # NTSC: 21.477272 MHz / 12
BAUD = 38400
MARK, SPACE = 1, 0


def bit_cycles(baud=BAUD, clock_error=0.0):
    """Cycles per bit for a UART whose clock runs clock_error fast (+) or
    slow (-)."""
    return CPU_HZ / (baud * (1.0 + clock_error))


class HostToNes:
    def __init__(self, stop_bits=2, clock_error=0.0):
        self.bit = bit_cycles(clock_error=clock_error)
        self.frame_bits = 1 + 8 + stop_bits
        self.starts = []
        self.bytes = []
        self.bits = []
        self.busy_until = 0.0
        self.sent = 0

    def send(self, data, at, bit=None):
        """Queue bytes back to back, starting no earlier than cycle at, at
        the link's rate or with bits of another length. Returns the cycle
        they end."""
        bit = self.bit if bit is None else bit
        start = max(at, self.busy_until)
        for byte in data:
            self.starts.append(start)
            self.bytes.append(byte)
            self.bits.append(bit)
            start += bit * self.frame_bits
        self.busy_until = start
        self.sent += len(data)
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

    def in_frame(self, cycle):
        """True from a start bit until its stop bits begin."""
        index = bisect.bisect_right(self.starts, cycle) - 1
        return index >= 0 and cycle < self.starts[index] + 9 * self.bits[index]

    def next_start_after(self, cycle):
        index = bisect.bisect_right(self.starts, cycle)
        return self.starts[index] if index < len(self.starts) else float("inf")


class NesToHost:
    def __init__(self, clock_error=0.0, initial=SPACE):
        self.bit = bit_cycles(clock_error=clock_error)
        self.times = [float("-inf")]
        self.levels = [initial]  # OUT0 idles low (break) until the ROM sets it
        self.search_from = float("-inf")
        self.framing_errors = 0

    def write(self, cycle, level):
        if level != self.levels[-1]:
            self.times.append(cycle)
            self.levels.append(level)

    def level(self, cycle):
        return self.levels[bisect.bisect_right(self.times, cycle) - 1]

    def decode(self, until):
        """Return [(cycle the byte completed, byte)] for bytes whose stop bit
        center has passed by cycle until."""
        out = []
        while True:
            edge = self._next_falling_edge(self.search_from)
            if edge is None or edge + 9.5 * self.bit > until:
                return out
            if self.level(edge + 0.5 * self.bit) != SPACE:
                self.search_from = edge + 0.5  # a glitch, not a start bit
                continue
            byte = 0
            for k in range(8):
                byte |= self.level(edge + (1.5 + k) * self.bit) << k
            stop = edge + 9.5 * self.bit
            if self.level(stop) == MARK:
                out.append((stop, byte))
            else:
                self.framing_errors += 1
            self.search_from = stop

    def _next_falling_edge(self, after):
        index = bisect.bisect_right(self.times, after)
        while index < len(self.times):
            if self.levels[index] == SPACE and self.levels[index - 1] == MARK:
                return self.times[index]
            index += 1
        return None
