"""The ladders of line rates the test climbs, one for each direction.

A rate is a whole number of NES CPU cycles per bit, so the console's
bit-banged routines hit every bit exactly and need no rounding. The Stick's
UART takes any baud rate, and is set to the nearest whole one. 47 cycles is
38080 baud, within 1% of the jukebox's 38400.

Each ladder ends where its routines do.

To the console there are two receivers, and neither is the jukebox's (which
takes 11 cycles to sample a bit and hunts for the start bit every 9; an
earlier build ran it up to 12 cycles a bit). Both keep the byte in A and
fold each read of the port into it, 6 cycles a sample, which they can do
because they count on what the unused bits of $4017 read as (PORT_IDLE).
Both leave each byte scrambled in a known way, which the console undoes
after the block (raw_byte).

Down to 8 cycles a bit the fast receiver hunts for each start bit, looking
every 6 or 7 cycles. At 8 that hunt is nearly a bit long, so at 7 and 6
the tracking receiver does not hunt at all: it looks at the line once a
byte, where the start bit should fall, and runs a cycle longer or shorter
for what it sees. It needs the first PREAMBLE bytes of a block to settle,
and those are $FF and not counted. 6 cycles is the floor: a sample takes 6.

The last rate to the console, 5 cycles a bit, is there to fail. The console
has no routine for it and runs its 6-cycle one, which needs more cycles
than such a byte has: the CPU figure for it is over 100%.

From the console, the sender takes 6 cycles a bit. Down to 8 it loads the
next byte during the start bit and needs 11 cycles between bytes, so under
11 its stop bit is longer than its data bits. At 6 it loads the byte
before the start bit and needs 13. Periods of 9 and 7 would need a pad of
one cycle.

Commands, replies and the screen's text always travel at CONTROL, whatever
rate is being tested.

tools/gen_rates.py builds the console's routines from these ladders, so the
two sides cannot disagree.
"""

CPU_HZ = 1789773                # NTSC: 21.477272 MHz / 12
SHARED = (186, 93, 62, 47, 39, 34, 28, 25, 21, 19, 17, 16, 14, 13)
TO_NES = SHARED + (12, 11, 10, 9, 8, 7, 6, 5)
TO_STICK = SHARED + (12, 11, 10, 8, 6)
CONTROL = 186                   # cycles a bit for commands and replies
BLOCK = 256                     # bytes in one test block
PREAMBLE = 8                    # of those, $FF for the tracking receiver to settle on
TO_NES_BITS = 11                # the Stick sends 8N2

# Port 2 as an instruction with $4017 as its operand reads it: bit 0 is D0
# inverted, so 0 at mark; D1 to D4 are pulled up and inverted, so 0 with
# nothing on them; bits 5 to 7 are whatever was last on the bus, the $40 of
# the address. The fast receiver is only used on a console that reads this.
PORT_IDLE = 0x40

# Cycles of a byte that the console's routines spend on instructions they
# need, the rest being padding or waiting for a start bit. The fast
# receiver: 9 to find the start bit and get to the byte's code, 4 and 6 a
# sample, 9 to store the byte and loop; above 12 cycles a bit its padding
# needs Y, so the hunt compares with A and both ends take a little longer,
# 12 and 11. The tracking receiver: 4 and 5 to look at the start bit and
# act on it, 4 and 6 a sample, 11 to store the byte and loop. Sending: 10
# for the start bit (8 at 6 cycles a bit), 6 a data bit, 4 for the stop
# bit, 5 to loop.
FASTEST_SAMPLE = 6              # asl, eor
ROOMY_TO_NES_WORK = 12 + 4 + 7 * 6 + 11
FAST_TO_NES_WORK = 9 + 4 + 7 * 6 + 9
TRACKED_TO_NES_WORK = 4 + 5 + 4 + 7 * 6 + 11
TO_STICK_WORK = 10 + 8 * 6 + 4 + 5
TO_STICK_STOP_MIN = 11
FAST_TO_STICK_STOP_MIN = 13


def baud(period):
    return (CPU_HZ + period // 2) // period


def tracked_receive(period):
    """True for the rates the tracking receiver takes; the fast one takes
    the rest."""
    return period < 8


def roomy(period):
    """True for the rates where the fast receiver's padding is long enough
    to need a loop, and so a register."""
    return period > 12


def beyond_cpu(period):
    """True for a rate faster than any routine the console has."""
    return period < FASTEST_SAMPLE


def routine_period(period):
    """The cycles a bit of the routine the console runs for a rate."""
    return max(period, FASTEST_SAMPLE)


def tracked_gaps(period):
    """Cycles between the tracking receiver's 8 samples. A gap is 6 or at
    least 8, so at 7 cycles a bit they take turns."""
    period = routine_period(period)
    if period - FASTEST_SAMPLE == 1:
        return [6, 8, 6, 8, 6, 8, 6]
    return [period] * 7


def fast_send(period):
    """True for the rates where the sender loads a byte ahead of its start
    bit, the start bit being too short to do it in."""
    return period < 8


def raw_byte(byte):
    """What the two faster receivers store for a byte. They shift A left and XORs
    the port in, 8 times, so the bits land in reverse order and inverted,
    with the port's $40 left in from the last two reads."""
    reverse = int("{:08b}".format(byte)[::-1], 2)
    return reverse ^ 0xFF ^ (PORT_IDLE | (PORT_IDLE << 1) & 0xFF)


def to_stick_stop(period):
    """Cycles of the stop bit the console sends."""
    least = FAST_TO_STICK_STOP_MIN if fast_send(period) else TO_STICK_STOP_MIN
    stop = max(period, least)
    return stop + 1 if stop - least == 1 else stop


def to_nes_byte(period):
    """Cycles from one byte's start bit to the next, sent back to back."""
    return TO_NES_BITS * period


def to_stick_byte(period):
    return 9 * period + to_stick_stop(period)


def to_nes_work(period):
    if tracked_receive(period):
        return TRACKED_TO_NES_WORK
    return ROOMY_TO_NES_WORK if roomy(period) else FAST_TO_NES_WORK


def to_stick_work(period):
    return TO_STICK_WORK - (2 if fast_send(period) else 0)
