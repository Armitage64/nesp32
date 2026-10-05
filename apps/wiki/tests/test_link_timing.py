"""The console's two serial routines, cycle by cycle.

rx_block is given bytes on a simulated line at every phase against its
hunt loop, and with the Stick's clock fast and slow; every read of $4017 is
compared with the middle of the bit it is meant to sample. tx_byte's writes
to $4016 are checked against the bit grid and decoded as a UART would.
"""

import random

import pytest
from console import HUNT, PRG_START
from wire import Tap, Wire

from neswiki.linkrate import PERIOD, REPLY_SIZE, TO_NES_BITS, baud

# The hunt sees a start bit 0 to 9 cycles after its edge, so with a true
# clock a sample is at most 4.5 cycles, 0.21 of a bit, from the middle.
SAMPLE_LIMIT = 0.25
PHASES = [step / 2 for step in range(2 * PERIOD)]
AWKWARD = bytes((0x00, 0xFF, 0x55, 0xAA, 0x80, 0x01, 0x7F, 0xFE))


def receive(link_console, data, start, error=0.0, gap=0.0):
    """Run rx_block against bytes sent from cycle `start` (after the call
    begins), with the sender's clock out by `error`. Returns (bytes it
    stored, each sample's distance from mid-bit in bits)."""
    c = link_console()
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
    c.call("rx_block")
    hunt = PRG_START + c.prg.index(HUNT)
    samples = [cycle for cycle, pc, _ in c.joy2_reads if pc != hunt]
    assert len(samples) == 8 * len(data)
    offsets = []
    for index, first in enumerate(starts):
        for k in range(8):
            offsets.append((samples[8 * index + k] - first) / bit - (1.5 + k))
    return c.memory[c.labels["rx_buf"]:c.labels["rx_buf"] + REPLY_SIZE], offsets


def block(seed):
    generator = random.Random(seed)
    return AWKWARD + bytes(generator.randrange(256) for _ in range(REPLY_SIZE - len(AWKWARD)))


def test_the_rate_is_the_one_both_sides_share():
    assert PERIOD == 21 and baud() == 85227 and TO_NES_BITS == 11


def test_every_sample_is_near_the_middle_of_its_bit(link_console):
    worst = 0.0
    total = count = 0
    for phase in PHASES:
        data = block(int(2 * phase))
        stored, offsets = receive(link_console, data, phase)
        assert bytes(stored) == data
        worst = max(worst, max(abs(offset) for offset in offsets))
        total += sum(offsets)
        count += len(offsets)
    assert worst <= SAMPLE_LIMIT, worst
    assert abs(total / count) < 0.03        # and centered on it, on average


@pytest.mark.parametrize("error", [-0.025, -0.01, 0.01, 0.025])
def test_a_stick_whose_clock_is_out_is_still_read(link_console, error):
    for phase in PHASES[::3]:
        data = block(int(phase))
        stored, offsets = receive(link_console, data, phase, error)
        assert bytes(stored) == data, (error, phase)
        assert max(abs(offset) for offset in offsets) < 0.5


def test_how_far_out_the_clock_may_be(link_console):
    """The plan counts on more than an ESP32's UART is ever out by."""
    def reads(error):
        return all(bytes(receive(link_console, block(3), phase, error)[0]) == block(3)
                   for phase in PHASES[::4])
    slow = next(step for step in range(1, 12) if not reads(-step / 100)) - 1
    fast = next(step for step in range(1, 12) if not reads(step / 100)) - 1
    assert slow >= 3 and fast >= 3, (slow, fast)


def test_bytes_with_gaps_between_them_are_read(link_console):
    # A Stick that pauses mid-reply: the hunt just waits.
    for gap in (1, 10, 100, 1000.5):
        data = block(8)
        stored, _ = receive(link_console, data, 3.5, gap=gap)
        assert bytes(stored) == data


def test_the_receiver_reads_the_port_with_nothing_but_lda(link_console):
    # console.py raises if $4017 is read any other way: a read-modify-write
    # instruction would also write the APU's frame counter.
    receive(link_console, block(1), 0)


def send(link_console, byte):
    c = link_console()
    c.joy1_writes = []
    tap = Tap()
    tap.write(c.now, 1)             # the line rests at mark
    c.on_joy1 = tap.write
    start = c.now
    c.call("tx_byte", a=byte)
    return c.joy1_writes, tap, start, c.now


def test_every_bit_is_written_on_the_grid(link_console):
    for byte in (0x00, 0xFF, 0x57, 0xA5, 0x01, 0x80):
        writes, _, _, end = send(link_console, byte)
        times = [cycle for cycle, _ in writes]
        assert [after - before for before, after in zip(times, times[1:])] == [PERIOD] * 9
        levels = [level for _, level in writes]
        assert levels == [0] + [(byte >> bit) & 1 for bit in range(8)] + [1]
        assert end - times[-1] >= PERIOD        # a whole stop bit before it returns


@pytest.mark.parametrize("error", [-0.03, 0.0, 0.03])
def test_a_uart_receives_every_byte_it_sends(link_console, error):
    for byte in range(256):
        _, tap, start, end = send(link_console, byte)
        received, _ = tap.decode(start, end + 10 * PERIOD, PERIOD / (1.0 + error))
        assert [value for value, _ in received] == [byte], (byte, error)
