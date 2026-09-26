"""The 38400-baud receive and send routines, measured cycle by cycle.

Each test calls rx_byte or tx_byte directly on py65 with the line model, so
every $4017 read and $4016 write lands on its real CPU cycle, including
the extra cycles branches pay when they cross a page. The sweeps cover
things a real wire can't be set to on purpose: every start-bit arrival
phase against the hunt loop, and baud error in either direction.
"""

import random
import shutil
import subprocess
import os

import pytest

from link_harness import HUNT_LOOP_CYCLES, LinkConsole
from serial_line import SPACE, HostToNes, NesToHost, bit_cycles

ROOT = os.path.join(os.path.dirname(__file__), "..")
BYTES = (0x00, 0xFF, 0x55, 0xAA, 0xA5, 0x01, 0x80, 0x7E)
PHASES = [step / 2 for step in range(2 * HUNT_LOOP_CYCLES)]  # 0, 0.5, ... 8.5

pytestmark = pytest.mark.skipif(
    not (shutil.which("ca65") and shutil.which("ld65")), reason="cc65 not installed"
)


@pytest.fixture(scope="session")
def link_rom(tmp_path_factory):
    build = tmp_path_factory.mktemp("link_build")
    subprocess.run(["make", "-s", "BUILD=%s" % build, "verify"], cwd=ROOT, check=True)
    return str(build / "jukebox_link.nes"), str(build / "jukebox_link.labels")


def receive(link_rom, byte, phase, clock_error=0.0, fast_forward=True):
    """rx_byte with a start bit arriving phase cycles into a hunt loop pass.
    Returns (byte, framing_error, sample offsets from bit centers in bits)."""
    line = HostToNes(clock_error=clock_error)
    machine = LinkConsole(*link_rom, to_nes=line, fast_forward=fast_forward)
    machine.read_log = []
    start = 200 + phase
    line.send([byte], at=start)
    mpu = machine.call("rx_byte")
    reads = machine.read_log
    detect = next(i for i, (_, level) in enumerate(reads) if level == SPACE)
    samples = [cycle for cycle, _ in reads[detect + 1:]]
    assert len(samples) == 9
    centers = [start + (1.5 + k) * line.bit for k in range(9)]
    offsets = [(cycle - center) / line.bit for cycle, center in zip(samples, centers)]
    return mpu.a, bool(mpu.p & 1), offsets


def test_the_hunt_loop_samples_every_nine_cycles(link_rom):
    line = HostToNes()
    machine = LinkConsole(*link_rom, to_nes=line, fast_forward=False)
    machine.read_log = []
    line.send([0x00], at=300)
    machine.call("rx_byte")
    hunt = [cycle for cycle, level in machine.read_log if cycle < 300]
    gaps = {b - a for a, b in zip(hunt, hunt[1:])}
    assert gaps == {HUNT_LOOP_CYCLES}


@pytest.mark.parametrize("byte", BYTES)
def test_every_phase_receives_correctly_near_bit_centers(link_rom, byte):
    worst = 0.0
    for phase in PHASES:
        got, framing_error, offsets = receive(link_rom, byte, phase)
        assert (got, framing_error) == (byte, False), "phase %.1f" % phase
        worst = max(worst, max(abs(offset) for offset in offsets))
    # Hunt granularity (9 cycles) and rounding the 46.61-cycle bit to whole
    # cycles put every sample within 0.12 bit of center, leaving 0.38 of the
    # 0.5 margin for baud error.
    assert worst < 0.12


def test_fast_forwarding_the_hunt_does_not_change_the_samples(link_rom):
    for phase in (0, 3.5, 8.5):
        assert receive(link_rom, 0xA5, phase) == receive(link_rom, 0xA5, phase, fast_forward=False)


@pytest.mark.parametrize("clock_error", [-0.03, -0.02, 0.02, 0.03])
def test_host_baud_error_up_to_3_percent(link_rom, clock_error):
    for byte in BYTES:
        for phase in (0, 4.5, 8.5):
            got, framing_error, _ = receive(link_rom, byte, phase, clock_error)
            assert (got, framing_error) == (byte, False)


def test_receive_tolerance_is_reported(link_rom):
    """Find the baud error at which reception first fails, both ways, for
    the record. The design needs 2%; UARTs are typically within 1%."""
    limits = []
    for sign in (1, -1):
        error = 0.0
        while error < 0.10:
            trial = sign * (error + 0.0025)
            ok = all(
                receive(link_rom, byte, phase, trial)[:2] == (byte, False)
                for byte in (0x00, 0xFF, 0x55, 0xAA) for phase in (0, 8.5)
            )
            if not ok:
                break
            error += 0.0025
        limits.append(error)
    print("\nrx_byte tolerates host baud error of +%.2f%% / -%.2f%%"
          % (limits[0] * 100, limits[1] * 100))
    assert min(limits) >= 0.03


def test_a_low_stop_bit_is_a_framing_error(link_rom):
    line = HostToNes(stop_bits=0)  # the next start bit lands on the stop bit
    machine = LinkConsole(*link_rom, to_nes=line)
    line.send([0x55, 0x00], at=200)
    mpu = machine.call("rx_byte")
    assert mpu.p & 1


def transmit(link_rom, byte):
    machine = LinkConsole(*link_rom)
    machine.to_host.write(0, 1)  # OUT0 already at mark, as link_init leaves it
    machine.write_log = []
    mpu = machine.call("tx_byte", a=byte, x=0x5A)
    return machine, mpu


@pytest.mark.parametrize("byte", BYTES)
def test_transmit_writes_every_bit_within_half_a_cycle(link_rom, byte):
    machine, mpu = transmit(link_rom, byte)
    writes = machine.write_log
    assert len(writes) == 10
    start = writes[0][0]
    bit = bit_cycles()
    levels = [0] + [(byte >> k) & 1 for k in range(8)] + [1]
    for k, (cycle, level) in enumerate(writes):
        assert level == levels[k]
        assert abs(cycle - start - k * bit) <= 0.62, "bit %d" % k
    assert mpu.x == 0x5A  # send_request relies on X surviving


@pytest.mark.parametrize("clock_error", [-0.03, 0.0, 0.03])
def test_host_receives_transmitted_bytes_with_baud_error(link_rom, clock_error):
    for byte in BYTES:
        machine, _ = transmit(link_rom, byte)
        host = NesToHost(clock_error=clock_error)
        host.write(0, 1)
        for cycle, level in machine.write_log:
            host.write(cycle, level)
        decoded = host.decode(machine.mpu.processorCycles + 1000)
        assert [b for _, b in decoded] == [byte]


def test_transmit_holds_a_full_stop_bit_before_returning(link_rom):
    machine, mpu = transmit(link_rom, 0x00)
    stop_write = machine.write_log[-1][0]
    assert mpu.processorCycles - stop_write >= bit_cycles()
