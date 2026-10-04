"""Every rate's receive and send routine, measured cycle by cycle.

Each test calls a routine directly on py65 with the line model, so every
$4017 read and $4016 write lands on its real CPU cycle. The sweeps cover
what a real wire cannot be set to on purpose: where the start bit falls
against the hunt loop, and baud error.
"""

import pytest

from linktest import proto
from linktest import rates
from linktest.rates import BLOCK, CONTROL, TO_NES, TO_STICK
from thru_sim import HUNT_CYCLES, SPACE, Machine, Tap, Wire

# The last rate to the console is one it cannot do; it has its own test.
RX_RATES = [r for r in range(len(TO_NES)) if not rates.beyond_cpu(TO_NES[r])]
TX_RATES = range(len(TO_STICK))
PHASES = (0, 2.5, 4.5, 7, 8.5)  # cycles into a pass of the 9-cycle hunt
RX_BUF = 0x0400
TX_BUF = 0x0500
START = 500


def receive_block(rom, rate, phase=0.0, clock_error=0.0):
    """Returns (machine, the block sent, the block as the routine left it:
    scrambled, until the ROM decodes it)."""
    wire = Wire()
    machine = Machine(*rom, wire=wire)
    machine.read_log = []
    data = proto.pattern(0x1D0C + rate, BLOCK)
    if rates.tracked_receive(TO_NES[rate]):
        data = b"\xff" * rates.PREAMBLE + data[rates.PREAMBLE:]
    wire.send(data, START + phase, TO_NES[rate] / (1.0 + clock_error))
    machine.call("rx_block_%d" % rate)
    stored = bytes(rates.raw_byte(byte) for byte in data)
    return machine, data, stored


def received(rom, rate, phase=0.0, clock_error=0.0):
    """True if the block arrived, the tracking receiver's preamble aside."""
    machine, _, stored = receive_block(rom, rate, phase, clock_error)
    skip = rates.PREAMBLE if rates.tracked_receive(TO_NES[rate]) else 0
    return machine.ram(RX_BUF, BLOCK)[skip:] == stored[skip:]


HUNTING = [r for r in RX_RATES if not rates.tracked_receive(TO_NES[r])]
TRACKED = [r for r in RX_RATES if rates.tracked_receive(TO_NES[r])]


@pytest.mark.parametrize("rate", TRACKED)
def test_the_tracking_receiver_settles_from_any_start_phase(rom, rate):
    period = TO_NES[rate]
    for phase in (0, 1, 2, 3, 4, 5, 5.5):
        assert received(rom, rate, phase), "phase %.1f" % phase
    # Once settled, every sample is within 2.5 cycles of the middle of its
    # bit: a cycle either way from tracking, and what the padding rounds.
    machine, data, _ = receive_block(rom, rate, 3)
    samples = [cycle for cycle, _ in machine.read_log]
    worst = 0.0
    for byte in range(rates.PREAMBLE, BLOCK):
        start = START + 3 + byte * 11 * period
        centers = [start + (1.5 + k) * period for k in range(8)]
        for center in centers:
            worst = max(worst, min(abs(cycle - center) for cycle in samples
                                   if abs(cycle - center) < period))
    assert worst <= 2.5 and worst < period / 2


def test_the_rate_past_the_last_cannot_be_received(rom):
    """At 5 cycles a bit the console runs its 6-cycle routine, which is the
    only reason that rate is on the ladder: it needs more cycles than the
    byte has, and every block fails."""
    rate = len(TO_NES) - 1
    assert TO_NES[rate] == 5 and rates.beyond_cpu(5) and not rates.beyond_cpu(6)
    assert rates.to_nes_work(5) > rates.to_nes_byte(5) == 55
    assert rates.to_nes_work(6) == rates.to_nes_byte(6) == 66
    for phase in (0, 2.5, 5):
        machine, _, stored = receive_block(rom, rate, phase)
        got = machine.ram(RX_BUF, BLOCK)
        wrong = sum(a != b for a, b in zip(got[rates.PREAMBLE:], stored[rates.PREAMBLE:]))
        assert wrong > 200
    # It is the 6-cycle routine, byte for byte, but for the page it is on.
    def code(index):
        start = machine.labels["rx_block_%d" % index]
        page = bytes((start >> 8,))
        return bytes(machine.prg[start - 0x8000:start - 0x8000 + 96]).replace(page, b"")

    assert code(rate) == code(rate - 1)


@pytest.mark.parametrize("rate", HUNTING)
def test_a_block_is_received_at_every_start_phase(rom, rate):
    period = TO_NES[rate]
    worst = 0.0
    for phase in PHASES:
        machine, _, stored = receive_block(rom, rate, phase)
        assert machine.ram(RX_BUF, BLOCK) == stored, "phase %.1f" % phase
        reads = machine.read_log
        detect = next(i for i, (_, level) in enumerate(reads) if level == SPACE)
        centers = [START + phase + (1.5 + k) * period for k in range(8)]
        for (cycle, _), center in zip(reads[detect + 1:detect + 9], centers):
            worst = max(worst, abs(cycle - center))
    # The hunt's looks are 6 or 7 cycles apart, so a sample is up to 3.5
    # off center, and a little more for rounding the first pad.
    assert worst <= 7 / 2 + 1 and worst < period / 2


@pytest.mark.parametrize("rate", HUNTING)
def test_the_hunt_resumes_inside_the_stop_bits(rom, rate):
    """After a byte's last sample the hunt must not read again until the
    last data bit is over, or a 0 there is taken for a start bit; and it
    must be reading before the next start bit falls, or the samples of that
    byte slide late."""
    period = TO_NES[rate]
    for phase in (0, 8.5):
        machine, _, _ = receive_block(rom, rate, phase)
        reads = machine.read_log
        detect = next(i for i, (_, level) in enumerate(reads) if level == SPACE)
        resumed = reads[detect + 9][0]
        assert START + phase + 9 * period < resumed <= START + phase + 11 * period


@pytest.mark.parametrize("rate", [r for r in RX_RATES if TO_NES[r] >= 19])
@pytest.mark.parametrize("clock_error", [-0.02, 0.02])
def test_a_block_survives_2_percent_baud_error(rom, rate, clock_error):
    for phase in (0, 8.5):
        assert received(rom, rate, phase, clock_error)


def test_receive_tolerance_is_reported(rom):
    """For the record: the host baud error a receiver takes, for every
    fourth of the shared rates and for each of the rest. It falls as the
    hunt's 6 or 7 cycles become more of a bit; the tracking receiver takes
    what it can make up at a cycle a byte."""
    print()
    shared = len(rates.SHARED)
    for rate in RX_RATES[:shared:4] + RX_RATES[shared:]:
        limits = []
        for sign in (1, -1):
            error = 0.0
            while error < 0.08:
                trial = sign * (error + 0.005)
                clean = all(received(rom, rate, phase, trial) for phase in (0, 3, 6, 8.5))
                if not clean:
                    break
                error += 0.005
            limits.append(error)
        print("%3d cycles a bit: host baud error +%.1f%% / -%.1f%%"
              % (TO_NES[rate], limits[0] * 100, limits[1] * 100))
        if TO_NES[rate] >= 13:
            assert min(limits) >= 0.025


def send_block(rom, rate):
    machine = Machine(*rom)
    machine.tap.write(0, 1)     # OUT0 already at mark, as reset leaves it
    data = proto.pattern(0x2B0D + rate, BLOCK)
    for offset, byte in enumerate(data):
        machine.memory[TX_BUF + offset] = byte
    machine.write_log = []
    machine.call("tx_block_%d" % rate)
    return machine, data


@pytest.mark.parametrize("rate", TX_RATES)
def test_a_block_is_sent_with_every_bit_on_its_cycle(rom, rate):
    machine, data = send_block(rom, rate)
    period = TO_STICK[rate]
    writes = machine.write_log
    assert len(writes) == 10 * BLOCK
    first = writes[0][0]
    for index, (cycle, level) in enumerate(writes):
        byte, bit = divmod(index, 10)
        expected = 0 if bit == 0 else 1 if bit == 9 else (data[byte] >> (bit - 1)) & 1
        at = byte * rates.to_stick_byte(period) + bit * period
        assert (cycle - first, level) == (at, expected), "write %d" % index


def test_the_stop_bit_is_never_shorter_than_a_data_bit():
    for period in TO_STICK:
        assert period <= rates.to_stick_stop(period) <= max(period, 13)
        assert rates.to_stick_byte(period) == 10 * period or period < 13


def test_the_receivers_share_of_the_cpu_is_what_rates_says(rom):
    """Count a routine's cycles that are not padding, by its opcodes, and
    compare with rates.to_nes_work: at 13 cycles a bit, where the padding
    is plain to see, and at 8 and 6, where there is next to none."""
    machine = Machine(*rom)

    def body(period):
        first = machine.labels["rx_block_%d" % TO_NES.index(period)]
        return bytes(machine.prg[first - 0x8000:first - 0x8000 + 256])

    # 6 cycles a bit: check 4, branch and nop or jump 5 on average, 8
    # samples 46, store and loop 11. Nothing else is in the loop.
    assert rates.to_nes_work(6) == rates.to_nes_byte(6) == 4 + 5 + 46 + 11
    assert body(6).count(0xEA) == 1 and body(6).count(0x24) == 0    # the one nop is a way out
    # 8 cycles a bit: 7 pads of 2 between samples, and the hunt idles the rest.
    assert body(8).count(0xEA) == 7 + 1
    assert rates.to_nes_byte(8) - rates.to_nes_work(8) - 7 * 2 == 10
    # 13 cycles a bit: 7 pads of 7 (pha, pla), a first pad of 5, a rest of 4.
    code = body(13)
    assert code.count(0x48) == code.count(0x68) == 7
    assert rates.to_nes_work(13) == 12 + 46 + 11


@pytest.mark.parametrize("rate", TX_RATES)
@pytest.mark.parametrize("clock_error", [-0.02, 0.0, 0.02])
def test_a_uart_receives_the_sent_block(rom, rate, clock_error):
    machine, data = send_block(rom, rate)
    bit = TO_STICK[rate] / (1.0 + clock_error)
    received, _ = machine.tap.decode(0, machine.now + 100 * bit, bit)
    assert bytes(received) == data


@pytest.mark.parametrize("byte", (0x00, 0xFF, 0x55, 0xAA, 0xC5, 0x01, 0x80))
def test_the_control_rate_byte_routines(rom, byte):
    period = CONTROL
    for phase in PHASES:
        wire = Wire()
        machine = Machine(*rom, wire=wire)
        wire.send([byte], START + phase, period)
        assert machine.call("ctl_rx_byte", x=0x5A).a == byte
        assert machine.mpu.x == 0x5A    # recv_command counts in X

    machine = Machine(*rom)
    machine.tap.write(0, 1)
    machine.write_log = []
    mpu = machine.call("ctl_tx_byte", a=byte, x=0x5A)
    writes = machine.write_log
    levels = [0] + [(byte >> k) & 1 for k in range(8)] + [1]
    assert [(cycle - writes[0][0], level) for cycle, level in writes] == [
        (k * period, level) for k, level in enumerate(levels)]
    assert mpu.x == 0x5A                # send_reply counts in X
    assert mpu.processorCycles - writes[-1][0] >= period    # a whole stop bit
