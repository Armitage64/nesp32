"""The search for the fastest stable rate: by itself with staged trials,
then the whole session against the test ROM on lines with slow edges."""

import pytest

import gen_screen
from linktest import proto, rates, tester
from linktest.tester import RX, TX, Link, Session, find_fastest
from thru_sim import Machine, SimPort, Tap, Wire, ms


def climb(passes):
    """find_fastest over rates that pass or fail as listed.
    Returns (the answer, the rates tried in order)."""
    tried = []

    def run(rate):
        tried.append(rate)
        return passes[rate]

    return find_fastest(run, len(passes)), tried


def test_it_climbs_until_a_rate_fails_and_backs_off_to_the_one_before():
    assert climb([True, True, True, False, False]) == (2, [0, 1, 2, 3])


def test_no_rate_is_tried_twice():
    for passes in ([True] * 5, [True, False, True], [False, True]):
        _, tried = climb(passes)
        assert len(tried) == len(set(tried))


def test_every_rate_passing_returns_the_fastest():
    assert climb([True] * 4) == (3, [0, 1, 2, 3])


def test_the_slowest_rate_failing_returns_none():
    assert climb([False, True, True]) == (None, [0])


class Display:
    def __init__(self):
        self.rows = {}

    def set(self, **rows):
        self.rows.update(rows)


def session(rom, to_nes_rise, to_stick_rise):
    """A session on lines whose rising edges come late by so many cycles,
    with trials of one block."""
    machine = Machine(*rom, wire=Wire(to_nes_rise), tap=Tap(to_stick_rise))
    machine.run_until(ms(40))
    display, log = Display(), []
    run = Session(Link(SimPort(machine)), display=display, log=log.append, blocks=1,
                  button=lambda: True)
    return machine, run, display, log


def state_row(machine):
    return machine.screen_text(tester.STATE_ROW, tester.LEFT, tester.WIDTH).rstrip()


def waiting(rom, presses, start_after=None, again=False):
    """Connect and wait to be started, with the Stick's button answering as
    listed and Start going down on the controller after so many looks.
    Returns (machine, session, display, looks at the button)."""
    machine = Machine(*rom)
    machine.run_until(ms(40))
    display, looks = Display(), []

    def button():
        assert run.trials == [] and state_row(machine).endswith("PRESS START")
        assert machine.screen_text(RX.top, tester.LEFT, tester.WIDTH).strip() == ""
        if len(looks) == start_after:
            machine.pad = proto.PAD_START | 0x01
        looks.append(machine.pad)
        return presses.pop(0)

    run = Session(Link(SimPort(machine)), display=display, button=button)
    assert run.link.connect()
    run.wait_start(again)
    return machine, run, display, looks


def test_nothing_runs_until_the_stick_s_button_is_pressed(rom):
    machine, run, display, looks = waiting(rom, [False] * 5 + [True])
    assert len(looks) == 6
    assert state_row(machine) == "PRESS START"
    assert display.rows["state"] == "PRESS A OR START"


def test_start_on_controller_1_starts_it_too(rom):
    machine, run, display, looks = waiting(rom, [False] * 9, start_after=3)
    assert looks == [0, 0, 0, proto.PAD_START | 0x01]   # the read after it went down


def test_other_buttons_do_not_start_it(rom):
    machine = Machine(*rom)
    machine.run_until(ms(40))
    machine.pad = 0xFF & ~proto.PAD_START
    presses = [False] * 4 + [True]
    run = Session(Link(SimPort(machine)), button=lambda: presses.pop(0))
    run.wait_start()
    assert presses == []


def test_a_second_run_waits_with_the_first_one_s_results_up(rom):
    machine, run, display, looks = waiting(rom, [False, True], again=True)
    assert state_row(machine) == "DONE. PRESS START"
    assert display.rows["state"] == "DONE. A OR START"


def half(machine, direction):
    """A direction's part of the console's screen: {row name: value}."""
    values = {}
    for index, name in enumerate(tester.ROWS):
        row = machine.screen_text(direction.top + 1 + index, tester.LEFT, tester.WIDTH)
        assert row.startswith(" " + name)
        values[name] = row[tester.VALUE_COLUMN - tester.LEFT:].rstrip()
    return values


def test_a_session_finds_each_direction_s_limit(rom):
    # The line to the console rises 8 cycles late, the line back 9.
    machine, run, display, log = session(rom, 8.0, 9.0)
    assert run.run() == (21, 19)

    # Each rate up to the first that failed was tried once, and none after.
    for direction, best in ((RX, 21), (TX, 19)):
        trials = [trial for trial in run.trials if trial[0] == direction.name]
        tried = [period for _, period, _, _ in trials]
        reached = direction.periods.index(best) + 1
        assert tried == list(direction.periods[:reached + 1])
        assert [bad for _, _, _, bad in trials[:-1]] == [0] * reached and trials[-1][3] > 0

    # Each half is left showing the rate that held, not the one that failed.
    assert machine.screen_text(RX.top, tester.LEFT, 12) == "STICK TO NES"
    assert half(machine, RX) == {"STATUS": "DONE", "SPEED": "85227 BPS", "SENT": "256 BYTES",
                                 "BAD": "0 BYTES", "CPU": "30%", "FASTEST": "7747 BYTES/S"}
    assert machine.screen_text(TX.top, tester.LEFT, 12) == "NES TO STICK"
    assert half(machine, TX) == {"STATUS": "DONE", "SPEED": "94199 BPS", "SENT": "256 BYTES",
                                 "BAD": "0 BYTES", "CPU": "35%", "FASTEST": "9419 BYTES/S"}
    assert RX.top + len(tester.ROWS) < TX.top and TX.top >= 15  # upper half, lower half

    def row(number):
        return machine.screen_text(number, tester.LEFT, tester.WIDTH).rstrip()

    header = 32 * (gen_screen.LOGO_LAST_ROW + 1)                    # is left alone
    assert bytes(machine.vram[0x2000:0x2000 + header]) == gen_screen.build_screen().nametable()[:header]
    assert row(tester.STATE_ROW) == "DONE"
    assert "BOTH WAYS" not in machine.vram.decode("latin-1")

    assert display.rows["state"] == "DONE"
    assert display.rows["rx"] == "85227 BPS 7747 B/S"
    assert display.rows["tx"] == "94199 BPS 9419 B/S"
    assert "both" not in display.rows
    assert display.rows["last"].startswith("TX 105281: ")
    assert "RX fastest stable: 85227 bps 7747 b/s" in log
    assert "RX  85227 bps: 0 of 256 bytes bad, cpu 30%, " in "\n".join(log)
    assert log[-1] == "0 commands repeated, 0 blocks stalled"


def test_the_screen_follows_the_trial_that_is_running(rom):
    machine, run, _, _ = session(rom, 8.0, 9.0)
    run.blocks = 3
    seen = []
    block = run.link.rx_block

    def watched(rate):
        seen.append(dict(half(machine, RX), lower=half(machine, TX)["STATUS"]))
        return block(rate)

    run.link.rx_block = watched
    run.link.connect()
    run.paint()
    run.search(RX)
    # As each block of the first trial goes out, and the first of the fourth.
    assert seen[0] == {"STATUS": "CLIMBING", "SPEED": "9622 BPS", "SENT": "0 BYTES",
                       "BAD": "0 BYTES", "CPU": "3%", "FASTEST": "", "lower": "WAITING"}
    assert [state["SENT"] for state in seen[:3]] == ["0 BYTES", "256 BYTES", "512 BYTES"]
    assert (seen[9]["SPEED"], seen[9]["CPU"], seen[9]["SENT"]) == ("38080 BPS", "13%", "0 BYTES")


def test_a_clean_line_reaches_the_top_of_both_ladders(rom):
    machine, run, _, log = session(rom, 0.0, 0.0)
    assert run.run() == (6, 6)
    assert half(machine, RX) == {
        "STATUS": "DONE", "SPEED": "298296 BPS", "SENT": "256 BYTES",
        "BAD": "0 BYTES", "CPU": "100%", "FASTEST": "27117 BYTES/S"}
    assert half(machine, TX) == {
        "STATUS": "DONE", "SPEED": "298296 BPS", "SENT": "256 BYTES",
        "BAD": "0 BYTES", "CPU": "97%", "FASTEST": "26713 BYTES/S"}
    assert len(run.trials) == len(RX.periods) + len(TX.periods)     # each rate once
    # The one rate that fails is the one the console's CPU cannot do.
    assert [trial[:2] for trial in run.trials if trial[3]] == [("RX", 5)]
    assert "RX 357955 bps: " in "\n".join(log) and ", cpu 120%, " in "\n".join(log)


def test_a_console_whose_port_reads_otherwise_runs_nothing_to_it(rom):
    machine, run, display, log = session(rom, 0.0, 0.0)
    read = machine._read_joy2
    machine.memory._read_subscribers[0x4017] = [lambda address: read(address) | 0x08]
    run.link.connect()
    run.check_port()
    assert run.rate_count(RX) == 0 and run.rate_count(TX) == len(TX.periods)
    assert log == ["the console's $4017 reads 48, not 40: its receivers cannot work"]
    run.paint()
    assert run.search(RX) is None and run.trials == []
    assert half(machine, RX)["FASTEST"] == "NONE" and display.rows["rx"] == "NO STABLE RATE"


def test_a_session_with_no_usable_line_says_so(rom):
    # Commands get through, and every block to the console has a bad byte.
    machine, run, display, _ = session(rom, 0.0, 0.0)
    run.link.port.to_nes = lambda baud_used, data: (
        data[:5] + bytes((data[5] ^ 0x04,)) + data[6:] if len(data) == 256 else data)
    assert run.run() == (None, 6)
    assert half(machine, RX) == {"STATUS": "DONE", "SPEED": "9622 BPS", "SENT": "256 BYTES",
                                 "BAD": "1 BYTES", "CPU": "3%", "FASTEST": "NONE"}
    assert display.rows["rx"] == "NO STABLE RATE"


def test_the_cpu_share_rises_with_the_rate():
    # All the way up each ladder, with no drop where one routine hands over
    # to the next, and past 100% only at the rate that is there to fail.
    for direction in (RX, TX):
        shares = [direction.cpu_percent(period) for period in direction.periods]
        assert shares == sorted(shares)
    received = {period: RX.cpu_percent(period) for period in RX.periods}
    assert [received[period] for period in (186, 47, 13, 12, 8, 7, 6, 5)] == [
        3, 13, 48, 48, 73, 86, 100, 120]
    sent = {period: TX.cpu_percent(period) for period in TX.periods}
    assert [sent[period] for period in (186, 47, 13, 8, 6)] == [4, 14, 52, 81, 97]
    assert RX.bytes_per_second(13) == 12515 and TX.bytes_per_second(13) == 13767
    # Under 11 cycles a bit the console's stop bit is longer than the rest.
    assert TX.bytes_per_second(8) == rates.CPU_HZ // (9 * 8 + 11)
    assert TX.bytes_per_second(6) == rates.CPU_HZ // (9 * 6 + 13)


def test_every_line_fits_the_screen():
    assert max(len(name) for name in tester.ROWS) + 2 <= tester.VALUE_COLUMN - tester.LEFT
    assert TX.top + len(tester.ROWS) <= 27      # rows 28 and 29 are overscan
