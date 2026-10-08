"""The console's serial routines, cycle by cycle.

nesp_rx_frame is given replies on a simulated line at every phase against
its hunt loop, of every kind of length, and with the Stick's clock fast and
slow; every read of $4017 is compared with the middle of the bit it is
meant to sample. Both receivers are measured: the one whose timeout is the
caller's NMI, and the one that counts its looks. nesp_tx_byte's writes to
$4016 are checked against the bit grid and decoded as a UART would.
"""

import random

import nesp_proto as p
import pytest
from console import HUNT, HUNT_TIMEOUT, PRG_START
from nesp import reply_frame
from wire import Tap, Wire

PERIOD = p.NESP_PERIOD
PHASES = [step / 2 for step in range(2 * PERIOD)]
RX_MASK = 0x3F                  # the setup ROM's: replies of up to 63 bytes
# Payload lengths: none, one, a few, and the longest the ROM takes.
LENGTHS = (0, 1, 2, 7, 30, RX_MASK)
AWKWARD = bytes((0x00, 0xFF, 0x55, 0xAA, 0x80, 0x01, 0x7F, 0xFE))


class Receiver:
    """One of the two receivers: the ROM it is in, how its hunt is found,
    and how near the middle of a bit its samples must fall."""

    def __init__(self, make, hunt, limit, clock, tries=None, early=0.0):
        self.make = make
        self.hunt_code, self.hunt_pass = hunt
        self.limit = limit
        self.clock = clock          # percent the Stick's clock may be out, at least
        self.tries = tries
        self.early = early          # bits before mid-bit that its samples are aimed


@pytest.fixture(params=["nmi", "timeout"])
def receiver(request, console, timeout_console):
    if request.param == "nmi":
        # The hunt sees a start bit 0 to 9 cycles after its edge, so with a
        # true clock a sample is at most 4.5 cycles, 0.21 of a bit, out.
        return Receiver(console, HUNT, 0.25, clock=3)
    # Its first byte's start bit is seen 0 to 11 cycles after its edge at
    # the worst, and each later byte's 0 to 6, where it is due: a first
    # byte's sample is at most 6 cycles out, 0.29 of a bit, and a later
    # byte's 3.5. An ESP32's UART is within a tenth of a percent.
    return Receiver(timeout_console, HUNT_TIMEOUT, 0.30, clock=2, tries=1)


def payload(length, seed):
    generator = random.Random(seed)
    data = AWKWARD + bytes(generator.randrange(256) for _ in range(length))
    return data[:length]


def frame(length, seed=0):
    return reply_frame(seed & 0x7F, (seed * 7) & 0xFF, (seed * 13) & 0xFF, payload(length, seed))


def receive(receiver, data, start, error=0.0, gap=0.0):
    """Run nesp_rx_frame against bytes sent from cycle `start` (after the
    call begins), with the sender's clock out by `error`. Returns (bytes it
    stored, each sample's distance from mid-bit in bits, the MPU)."""
    c = receiver.make()
    wire = Wire()
    bit = PERIOD / (1.0 + error)
    begin = c.now + 200 + start
    starts = []
    at = begin
    for byte in data:
        starts.append(at)
        at = wire.send(bytes((byte,)), at, bit) + gap
    c.joy2_level = wire.level
    c.joy2_quiet_until = wire.quiet_until
    c.joy2_reads = []
    if receiver.tries is not None:
        c.memory[c.labels["nesp_tries"]] = receiver.tries
    mpu = c.call("nesp_rx_frame")
    routine = c.labels["nesp_rx_frame"] - PRG_START
    hunt = PRG_START + c.prg.index(receiver.hunt_code, routine)
    # A sample is an lda; the counting receiver's looks for a start bit are
    # bit, and the other's are one lda, at its hunt.
    samples = [cycle for cycle, pc, _ in c.joy2_reads
               if pc != hunt and c.prg[pc - PRG_START] == 0xAD]
    offsets = []
    for index in range(min(len(samples) // 8, len(starts))):
        for k in range(8):
            offsets.append((samples[8 * index + k] - starts[index]) / bit - (1.5 + k))
    return c.data("nesp_rx", len(data)), offsets, mpu


def test_the_rate_is_the_one_both_sides_share():
    assert PERIOD == 21 and p.NESP_BAUD == 85227 and p.NESP_TO_NES_BITS == 11


@pytest.mark.parametrize("length", LENGTHS)
def test_every_sample_is_near_the_middle_of_its_bit(receiver, length):
    worst = 0.0
    total = count = 0
    for phase in PHASES:
        data = frame(length, int(2 * phase))
        stored, offsets, mpu = receive(receiver, data, phase)
        assert stored == data, (length, phase)
        assert len(offsets) == 8 * len(data)        # and it stopped at the frame's end
        assert not mpu.p & 1                        # carry clear: a frame came
        worst = max(worst, max(abs(offset) for offset in offsets))
        total += sum(offsets)
        count += len(offsets)
    assert worst <= receiver.limit, worst
    # And centered on it, on average, or as much before it as it is aimed.
    assert abs(total / count + receiver.early) < 0.04


@pytest.mark.parametrize("share", [-0.8, -0.4, 0.4, 0.8])
def test_a_stick_whose_clock_is_out_is_still_read(receiver, share):
    error = share * receiver.clock / 100
    for length in (0, 7, RX_MASK):
        for phase in PHASES[::3]:
            data = frame(length, int(phase))
            stored, offsets, _ = receive(receiver, data, phase, error)
            assert stored == data, (error, length, phase)
            assert max(abs(offset) for offset in offsets) < 0.5


def test_how_far_out_the_clock_may_be(receiver):
    """More than an ESP32's UART is ever out by."""
    def reads(error):
        return all(receive(receiver, frame(length, 3), phase, error)[0] == frame(length, 3)
                   for phase in PHASES[::4] for length in (0, 30))
    slow = next(step for step in range(1, 12) if not reads(-step / 100)) - 1
    fast = next(step for step in range(1, 12) if not reads(step / 100)) - 1
    assert slow >= receiver.clock and fast >= receiver.clock, (slow, fast)


def test_bytes_with_gaps_between_them_are_read(receiver):
    # A Stick that pauses mid-reply: the hunt just waits.
    for gap in (1, 10, 100, 1000.5):
        data = frame(12, 8)
        stored, _, _ = receive(receiver, data, 3.5, gap=gap)
        assert stored == data


def test_a_length_past_the_buffer_is_cut_not_followed(receiver):
    # A header that claims more than the ROM takes: the routine stores no
    # more than its buffer holds, whatever follows on the line.
    c = receiver.make()
    room = c.labels["nesp_tx"] - c.labels["nesp_rx"]
    assert room == RX_MASK + 1 + p.NESP_OVERHEAD
    for claimed in (RX_MASK + 1, 0x7F, 0x80, 0xFF):
        data = bytes((p.NESP_REPLY_MARKER, 0, 0, 1, claimed)) + bytes(range(1, 250))
        c = receiver.make()
        guard = c.labels["nesp_rx"] + room
        c.memory[guard] = 0xEE
        wire = Wire()
        wire.send(data, c.now + 500)
        c.joy2_level = wire.level
        c.joy2_quiet_until = wire.quiet_until
        if receiver.tries is not None:
            c.memory[c.labels["nesp_tries"]] = receiver.tries
        c.call("nesp_rx_frame")
        assert c.memory[guard] == 0xEE, claimed
        assert c.byte("nesp_rx_end") == (claimed & RX_MASK) + p.NESP_OVERHEAD


def test_the_receivers_read_the_port_with_nothing_but_lda(receiver):
    # console.py raises if $4017 is read any other way: a read-modify-write
    # instruction would also write the APU's frame counter.
    receive(receiver, frame(4), 0)


def test_the_counting_receiver_gives_up(timeout_console):
    c = timeout_console()
    c.joy2_level = lambda cycle: 1          # the line rests, for ever
    c.memory[c.labels["nesp_tries"]] = 3
    before = c.now
    mpu = c.call("nesp_rx_frame")
    assert mpu.p & 1                        # carry set: nothing came
    # 3 passes of 256 counts of 29 cycles: 12.4 ms.
    assert 3 * 256 * 29 <= c.now - before <= 3 * 256 * 29 + 100


def test_the_counting_receiver_gives_up_in_the_middle_of_a_frame(timeout_console):
    c = timeout_console()
    wire = Wire()
    wire.send(frame(20)[:9], c.now + 500)   # and then nothing more
    c.joy2_level = wire.level
    c.memory[c.labels["nesp_tries"]] = 3
    assert c.call("nesp_rx_frame").p & 1


# --- sending ---------------------------------------------------------------------

def send(console, byte):
    c = console()
    c.joy1_writes = []
    tap = Tap()
    tap.write(c.now, 1)             # the line rests at mark
    c.on_joy1 = tap.write
    start = c.now
    c.call("nesp_tx_byte", a=byte)
    return c.joy1_writes, tap, start, c.now


def test_every_bit_is_written_on_the_grid(console):
    for byte in (0x00, 0xFF, p.NESP_REQUEST_MARKER, 0xA5, 0x01, 0x80):
        writes, _, _, end = send(console, byte)
        times = [cycle for cycle, _ in writes]
        assert [after - before for before, after in zip(times, times[1:])] == [PERIOD] * 9
        levels = [level for _, level in writes]
        assert levels == [0] + [(byte >> bit) & 1 for bit in range(8)] + [1]
        assert end - times[-1] >= PERIOD        # a whole stop bit before it returns


@pytest.mark.parametrize("error", [-0.03, 0.0, 0.03])
def test_a_uart_receives_every_byte_it_sends(console, error):
    for byte in range(256):
        _, tap, start, end = send(console, byte)
        received, _ = tap.decode(start, end + 10 * PERIOD, PERIOD / (1.0 + error))
        assert [value for value, _ in received] == [byte], (byte, error)


def test_the_routines_each_sit_on_one_page(console, timeout_console):
    # A branch that crossed a page would take a cycle more. The assembler
    # checks each routine's ends; this checks they are where it was told.
    for make in (console, timeout_console):
        c = make()
        assert c.labels["nesp_rx_frame"] & 0xFF == 0
        assert c.labels["nesp_tx_byte"] & 0xFF == 0


# --- a sample being played ---------------------------------------------------------

def receive_through_a_sample(make, data, start, first_fetch, stolen=4, every=432):
    """nesp_rx_frame against a reply, on a console that is playing a sample
    at the fastest rate: every 432 cycles a byte of it is fetched, and the
    CPU stops for up to four. Returns what the routine stored."""
    c = make()
    wire = Wire()
    wire.send(data, c.now + 200 + start)
    fetch = [c.now + first_fetch]

    def level(cycle):
        # The fetch falls before the instruction that reads the port, if it
        # is due: that read, and all after it, come later.
        value = wire.level(cycle + (stolen if cycle >= fetch[0] else 0))
        if cycle >= fetch[0]:
            fetch[0] += every
            c.mpu.processorCycles += stolen
        return value

    c.joy2_level = level
    c.memory[c.labels["nesp_tries"]] = 3
    c.call("nesp_rx_frame")
    return c.data("nesp_rx", len(data))


def test_the_counting_receiver_reads_through_a_sample(timeout_console):
    """nes-contra's music has samples for its drums, and on a real console
    its replies were misheard, one in twelve, by a receiver that looked for
    every byte's start bit 13 cycles apart: with four cycles stolen it had
    none to spare, and a real line's edges are not as sharp as these.
    Wherever in a frame the fetches fall, and wherever its first start bit
    falls in the hunt, this one reads every byte; and with six stolen, two
    more than a fetch takes, every byte but a frame's first, which it has
    to find without knowing where to look. (The old one misread one frame
    in eight with five stolen, and three in ten with six.)"""
    for data in (frame(0, 5), frame(7, 6), bytes((0xB1, 0x34, 0x00, 0xFF, 0x55, 0xAA))):
        for phase in PHASES[::2]:
            for first_fetch in range(150, 150 + 432, 9):
                stored = receive_through_a_sample(timeout_console, data, phase, first_fetch)
                assert stored == data, (phase, first_fetch)
                stored = receive_through_a_sample(timeout_console, data, phase, first_fetch,
                                                  stolen=6)
                assert stored[1:] == data[1:], (phase, first_fetch)
