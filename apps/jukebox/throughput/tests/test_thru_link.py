"""The host's Link against the test ROM, through the simulated wire."""

import pytest

from linktest import proto, rates
from linktest.rates import BLOCK, CONTROL, TO_NES, TO_STICK, baud
from linktest.tester import FILLER, Link, LinkError
from thru_sim import Machine, SimPort, Tap, Wire, ms

# The last rate to the console is one it cannot do.
RX_RATES = [r for r in range(len(TO_NES)) if not rates.beyond_cpu(TO_NES[r])]
TX_RATES = range(len(TO_STICK))
RX_BUF = 0x0400


def console(rom, to_nes_rise=0.0, to_stick_rise=0.0, **port_options):
    machine = Machine(*rom, wire=Wire(to_nes_rise), tap=Tap(to_stick_rise))
    machine.run_until(ms(40))   # reset, and the screen is up
    port = SimPort(machine, **port_options)
    return machine, port, Link(port)


def test_the_screen_waits_for_the_stick_until_one_answers(rom):
    machine, _, link = console(rom)
    assert link.ping()
    assert machine.screen_text(2, 4, 24) == "N-ESP-32 THROUGHPUT TEST"
    assert machine.screen_text(4, 2, 21) == "WAITING FOR THE STICK"


def test_draw_puts_text_on_the_screen(rom):
    machine, _, link = console(rom)
    assert link.draw(4, 2, "RX RAMP 57735 BAUD")
    assert machine.screen_text(4, 2, 21) == "RX RAMP 57735 BAUDICK"
    assert link.draw(12, 20, "x" * 40)      # cut to what one draw carries
    assert machine.screen_text(12, 20, 12) == "x" * 12
    assert machine.screen_text(13, 0, 21) == "x" * 20 + " "     # 32 tiles, wrapped


@pytest.mark.parametrize("rate", RX_RATES)
def test_a_clean_line_passes_a_block_to_the_console(rom, rate):
    machine, port, link = console(rom)
    assert link.rx_block(rate) == 0
    baud_used, block = port.writes[-1]
    assert (baud_used, len(block)) == (baud(TO_NES[rate]), BLOCK)
    skip = rates.PREAMBLE if rates.tracked_receive(TO_NES[rate]) else 0
    assert block[:skip] == b"\xff" * skip
    assert machine.ram(RX_BUF, BLOCK)[skip:] == block[skip:]
    assert (link.repeats, link.stalls) == (0, 0)


@pytest.mark.parametrize("rate", TX_RATES)
def test_a_clean_line_passes_a_block_from_the_console(rom, rate):
    _, _, link = console(rom)
    assert link.tx_block(rate) == 0
    assert link.repeats == 0


@pytest.mark.parametrize("clock_error", [-0.01, 0.01])
def test_a_host_clock_1_percent_off_passes_every_rate(rom, clock_error):
    _, _, link = console(rom, clock_error=clock_error)
    assert [link.rx_block(rate) for rate in RX_RATES] == [0] * len(RX_RATES)
    assert [link.tx_block(rate) for rate in TX_RATES] == [0] * len(TO_STICK)


def test_a_clean_line_fails_the_rate_the_console_cannot_do(rom):
    _, _, link = console(rom)
    assert link.rx_block(len(TO_NES) - 1) > 200


def test_the_console_reports_what_its_port_reads(rom):
    machine, _, link = console(rom)
    assert link.port_value() == rates.PORT_IDLE


def test_junk_received_at_a_rate_change_does_not_shift_a_block(rom):
    # Seen on a StickC Plus2: every rate but the control rate, where the
    # UART is not changed, failed with nearly all 256 bytes bad.
    _, _, link = console(rom, switch_junk=0x00)
    assert [link.tx_block(rate) for rate in TX_RATES] == [0] * len(TO_STICK)
    assert [link.rx_block(rate) for rate in RX_RATES] == [0] * len(RX_RATES)


def test_a_failed_block_from_the_console_is_described(rom):
    _, _, link = console(rom, to_stick_rise=10.0)
    assert link.tx_block(len(TO_STICK) - 1) > 0
    assert " bytes came, first " in link.tx_detail and ", expected " in link.tx_detail


def test_slow_edges_fail_the_fast_rates_only(rom):
    # A rising edge 10 cycles late shortens every mark after a space.
    _, _, link = console(rom, to_nes_rise=10.0, to_stick_rise=10.0)
    assert link.rx_block(3) == 0 and link.tx_block(3) == 0      # 47 cycles a bit
    at_13 = TO_NES.index(13)
    assert link.rx_block(at_13) > 0 and link.tx_block(at_13) > 0
    assert link.rx_block(TO_NES.index(8)) > 0                   # the fast receiver
    assert link.rx_block(TO_NES.index(6)) > 0                   # the tracking one
    assert link.tx_block(len(TO_STICK) - 1) > 0                 # 6


def test_a_damaged_command_is_sent_again(rom):
    damaged = []

    def damage_first(baud_used, data):
        if not damaged:
            damaged.append(data)
            return data[:2] + bytes((data[2] ^ 0x10,)) + data[3:]
        return data

    machine, _, link = console(rom, to_nes=damage_first)
    assert link.draw(4, 2, "HELLO")
    assert machine.screen_text(4, 2, 5) == "HELLO"
    assert link.repeats == 1


def test_a_block_that_loses_bytes_does_not_hang_the_console(rom):
    def lose_bytes(baud_used, data):
        return data[:100] + data[110:] if len(data) == BLOCK else data

    _, port, link = console(rom, to_nes=lose_bytes)
    bad = link.rx_block(6)
    assert bad > 100                # everything after the gap is out of step
    assert link.stalls == 1
    assert (baud(CONTROL), FILLER) in port.writes
    port.to_nes = None
    assert link.rx_block(6) == 0    # and the console is listening again


def test_connect_frees_a_console_left_waiting_for_a_block(rom):
    machine, port, link = console(rom)
    assert link.ping()
    port.write(proto.command(77, proto.OP_RX, bytes((0, 1, 0))))    # and no block
    port.sleep_ms(50)
    fresh = Link(port)
    assert fresh.connect(attempts=12)
    assert fresh.rx_block(5) == 0


def test_the_console_refuses_a_rate_it_does_not_have(rom):
    _, port, link = console(rom)
    port.set_baud(baud(CONTROL))
    for payload in (bytes((len(TO_NES), 1, 0)), bytes((0, 0, 0)), bytes((0, 1))):
        seq = link._send(proto.OP_RX, payload)
        assert link._reply(seq, proto.OP_RX, 100) == proto.ERROR_VALUE
    # The two ladders differ in length, and each has its own limit.
    seq = link._send(proto.OP_TX, bytes((len(TO_STICK), 1, 0)))
    assert link._reply(seq, proto.OP_TX, 100) == proto.ERROR_VALUE


def test_a_rom_built_from_another_ladder_is_reported(rom):
    machine, _, link = console(rom)
    assert link.ping()
    # Patch the ping's answer: lda #RX_COUNT is the first one after main.
    address = machine.labels["main"]
    while not (machine.memory[address] == 0xA9 and machine.memory[address + 1] == len(TO_NES)):
        address += 1
    machine.memory[address + 1] = len(TO_NES) + 1
    with pytest.raises(LinkError):
        link.ping()
