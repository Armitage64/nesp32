"""Write-order model of the 2A03 APU registers.

This is not an audio emulator. It captures exactly the register behavior
that decides whether the converter may drop, merge, or reorder writes inside
one frame, and nothing more:

- Most registers are plain latches. Writing the value already there does
  nothing, and only the last write in a frame matters.
- Writing $4003, $4007, $400B or $400F restarts the note (length counter,
  envelope, and the pulse phase), even with an unchanged value. Games repeat
  these on purpose, so every such write is an event.
- A sweep register ($4001, $4005) with the enable bit set reloads the sweep
  divider when written, so it is an event too. With the enable bit clear it
  is a plain latch.
- $4017 resets the frame sequencer, so every write is an event.
- $4011 loads the DMC output level. With DMC sample playback off, as in v1,
  it is a plain latch. It still matters: the level shifts how loud the
  triangle and noise channels mix, and some games (Super Mario Bros.) set
  it every frame for exactly that.
- A length load only takes effect while $4015 enables that channel, and
  clearing an enable bit zeroes the channel's length. That is the one
  place where order within a frame changes the result, so the model tracks
  per-channel enabled and active bits.

Two write sequences are equivalent when they leave the same register values,
the same enabled and active bits, and the same multiset of events. Events at
the same instant on different channels commute, so order among them is not
compared.
"""

PULSE1_SWEEP = 0x01
PULSE2_SWEEP = 0x05
DMC_LEVEL = 0x11
STATUS = 0x15
FRAME_COUNTER = 0x17

PLAIN_REGISTERS = frozenset(
    {0x00, 0x02, 0x04, 0x06, 0x08, 0x0A, 0x0C, 0x0E, DMC_LEVEL, STATUS}
)
SWEEP_REGISTERS = frozenset({PULSE1_SWEEP, PULSE2_SWEEP})
SWEEP_ENABLE = 0x80
LENGTH_LOADS = {0x03: 0x01, 0x07: 0x02, 0x0B: 0x04, 0x0F: 0x08}
CHANNEL_BITS = 0x0F

# Everything the v1 stream carries. DMC sample playback ($4010, $4012,
# $4013) and the unused, test and I/O registers ($4009, $400D, $4014, $4016,
# $4018-$401F) are dropped.
STREAMED_REGISTERS = (
    PLAIN_REGISTERS | SWEEP_REGISTERS | frozenset(LENGTH_LOADS) | {FRAME_COUNTER}
)


def is_redundant(register, value, known):
    """True when writing value cannot change anything the APU does.

    known maps registers to the values the console is known to hold. A
    missing register is unknown, so its write is never redundant.
    """
    if known.get(register) != value:
        return False
    if register in PLAIN_REGISTERS:
        return True
    return register in SWEEP_REGISTERS and not value & SWEEP_ENABLE


def is_event(register, value):
    if register in LENGTH_LOADS or register == FRAME_COUNTER:
        return True
    return register in SWEEP_REGISTERS and bool(value & SWEEP_ENABLE)


class ApuState:
    __slots__ = ("registers", "enabled", "active")

    def __init__(self, enabled=0, active=0):
        self.registers = {}
        self.enabled = enabled
        self.active = active

    def copy(self):
        other = ApuState(self.enabled, self.active)
        other.registers = dict(self.registers)
        return other

    def write(self, register, value, events):
        if register == STATUS:
            self.enabled = value & CHANNEL_BITS
            self.active &= self.enabled
        elif register in LENGTH_LOADS and self.enabled & LENGTH_LOADS[register]:
            self.active |= LENGTH_LOADS[register]
        if is_event(register, value):
            events.append((register, value))
        self.registers[register] = value

    def run(self, writes):
        """Apply one frame's writes in order and return its sorted events."""
        events = []
        for register, value in writes:
            self.write(register, value, events)
        return tuple(sorted(events))

    def snapshot(self):
        return (tuple(sorted(self.registers.items())), self.enabled, self.active)


# Channels are independent in this model, so these three starting points
# cover every per-channel combination of enabled and active.
_START_STATES = ((0, 0), (CHANNEL_BITS, 0), (CHANNEL_BITS, CHANNEL_BITS))


def equivalent(first, second, known=None):
    """True when two write sequences for one frame are interchangeable
    regardless of which channels are enabled or sounding beforehand.

    known holds the register values both sequences start from, so a write
    one side skipped as redundant compares equal.
    """
    known = known or {}
    for enabled, active in _START_STATES:
        if STATUS in known:
            # The console's enables are whatever $4015 last held.
            enabled = known[STATUS] & CHANNEL_BITS
            active &= enabled
        a, b = ApuState(enabled, active), ApuState(enabled, active)
        a.registers = dict(known)
        b.registers = dict(known)
        if a.run(first) != b.run(second) or a.snapshot() != b.snapshot():
            return False
    return True
