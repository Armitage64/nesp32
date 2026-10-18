"""The test ROM against nesp32's own firmware, over the simulated line: the
hello, the wait to be started, a whole test on clean lines and on lines
with slow edges, and what happens when the nesp32 goes away."""

import gen_screen
import gen_ui
import nesp
import nesp_proto as p
import pytest

import rates
from rates import BLOCK, FROM_NES, TO_NES
from thru_sim import PAD_SELECT, PAD_START, VBLANK_CYCLES, Bench, ms

RAW = p.NESP_SVC_RAW
ROWS = [name for name, _ in gen_screen.ROWS]
RX, TX = 0, 1                   # the halves of the screen
WAITING, PRESS, TESTING, AGAIN = (gen_screen.WAITING, "PRESS START", "TESTING",
                                  "DONE. PRESS START")
BLANK = dict.fromkeys(ROWS, "")
FAILED_AT_5 = "357955 BPS, "    # the rate the console's CPU cannot do


def state(bench):
    return bench.machine.text(gen_screen.STATE_ROW, gen_screen.LEFT, gen_screen.WIDTH).rstrip()


def half(bench, which):
    """A direction's part of the screen: {row name: value}."""
    title, top = gen_screen.HALVES[which]
    assert bench.machine.text(top, gen_screen.LEFT, gen_screen.WIDTH).rstrip() == title
    values = {}
    for index, name in enumerate(ROWS):
        row = bench.machine.text(top + 1 + index, gen_screen.LEFT, gen_screen.WIDTH)
        assert row.startswith(" " + name)
        values[name] = row[gen_screen.VALUE_COLUMN - gen_screen.LEFT:].rstrip()
    return values


def greet(bench):
    bench.machine.run_until(lambda: state(bench) in (PRESS, AGAIN), 60)
    return bench


def finish(bench, frames=6000):
    """Run a test that has been started to its end. Returns the cycle it
    began at."""
    began = bench.machine.now
    bench.machine.run_until(lambda: state(bench) == TESTING, 30)
    bench.machine.run_until(lambda: state(bench) == AGAIN, frames)
    return began


def whole_test(rom, **options):
    """A whole test, started from the controller. Returns the bench and
    the cycle the test began at."""
    bench = greet(Bench(rom, **options))
    bench.press_start()
    return bench, finish(bench)


def runs(bench, since=0):
    """The runs the console asked for, in order: ("to" or "from", period)."""
    asked, _ = bench.requests(since)
    names = {p.NESP_RAW_SEND: "to", p.NESP_RAW_LISTEN: "from"}
    return [(names[op], payload[0]) for svc, op, payload in asked if svc == RAW and op in names]


def figures(period, to_nes, sent=BLOCK, failed="NONE"):
    """A half of the screen once its direction is done at a rate."""
    baud, cpu, fastest = (rates.to_nes_figures if to_nes else rates.from_nes_figures)(period)
    return {"STATUS": "DONE", "SPEED": "%d BPS" % baud, "SENT": "%d BYTES" % sent,
            "BAD": "0 BYTES", "CPU": "%d%%" % cpu, "FASTEST": "%d BYTES/S" % fastest,
            "FAILED": failed}


# --- before a test ---------------------------------------------------------------------


def test_the_screen_comes_up_waiting_for_a_nesp32(rom):
    bench = Bench(rom, attached=False)
    bench.machine.run(200)
    assert bench.machine.nametable() == gen_screen.build_screen().nametable()
    assert state(bench) == WAITING
    assert half(bench, RX) == half(bench, TX) == BLANK
    bench.attach()              # and it goes on saying hello until one answers
    assert state(greet(bench)) == PRESS


def test_the_header_is_the_jukeboxs(rom):
    bench = Bench(rom, attached=False)
    bench.machine.run(2)
    assert bytes(bench.machine.vram[0x3F00:0x3F10]) == gen_screen.palette_data()
    ours, theirs = gen_screen.build_screen(), gen_ui.build_screens()[0]

    def pixels(screen, column, row, columns, rows):
        """Part of a screen as its tiles' bytes, whatever their numbers."""
        return [screen.tiles[screen.names[32 * (row + y) + column + x]]
                for y in range(rows) for x in range(columns)]

    # "ES" is in both names, and the credit line is the same one.
    def letters(text, at):
        """The column of a big letter in a name set in the middle of a row."""
        return (gen_ui.SCREEN_COLUMNS - 2 * len(text)) // 2 + 2 * at

    assert (pixels(ours, letters(gen_screen.LOGO_TEXT, gen_screen.LOGO_TEXT.index("ES")),
                   gen_screen.LOGO_ROW, 4, 2)
            == pixels(theirs, letters(gen_ui.LOGO_TEXT, gen_ui.LOGO_TEXT.index("ES")),
                      gen_ui.LOGO_ROW, 4, 2))
    assert (pixels(ours, gen_ui.CREDIT_COLUMN, gen_screen.CREDIT_ROW, gen_ui.CREDIT_TILES, 1)
            == pixels(theirs, gen_ui.CREDIT_COLUMN, gen_ui.CREDIT_ROW, gen_ui.CREDIT_TILES, 1))
    # What the ROM is for, under the name, in the credit line's blue: color 2.
    subtitle = pixels(ours, 0, gen_screen.SUBTITLE_ROW, 32, gen_screen.SUBTITLE_ROWS)
    assert not any(any(tile[:8]) for tile in subtitle) and any(any(tile) for tile in subtitle)
    assert gen_screen.SUBTITLE_ROW == gen_screen.LOGO_ROW + 2
    for row in range(gen_screen.LOGO_LAST_ROW + 1):
        attribute = ours.attributes[(row // 4) * 8] >> ((row // 2) % 2) * 4
        assert attribute & 3 == gen_ui.PALETTE_LOGO


def test_the_hello_names_the_rom_and_asks_for_raw(rom):
    bench = greet(Bench(rom))
    assert bench.stick.app == (b"THRU", 1)
    assert bench.stick.active(RAW) and not bench.stick.active(p.NESP_SVC_JUKE)


def test_nothing_runs_until_it_is_started(rom):
    bench = greet(Bench(rom))
    bench.machine.pad = 0xFF & ~(PAD_START | PAD_SELECT)    # every button but those two
    bench.stick.event(p.NESP_EVENT_BUTTON_B)
    bench.stick.event(p.NESP_EVENT_BUTTON_POWER)
    bench.machine.run(120)
    assert state(bench) == PRESS and bench.port.rates == []
    assert half(bench, RX) == half(bench, TX) == BLANK
    bench.machine.pad = PAD_START | 0x01
    bench.machine.run_until(lambda: state(bench) == TESTING, 10)


def test_button_a_on_the_nesp32_starts_it_too(rom):
    bench = greet(Bench(rom))
    bench.press_a()
    bench.machine.run_until(lambda: state(bench) == TESTING, 10)
    assert half(bench, TX)["STATUS"] == "WAITING"


def test_a_press_from_before_the_hello_starts_nothing(rom):
    bench = Bench(rom)
    bench.press_a()
    greet(bench).machine.run(60)
    assert state(bench) == PRESS and bench.port.rates == []


def test_a_nesp32_without_raw_is_to_be_updated(rom):
    bench = Bench(rom, attached=False)
    port = bench.port

    heard = bytearray()

    def old_firmware():
        """Answers a hello as firmware with no RAW service would."""
        heard.extend(port.read() or b"")
        at = heard.find(bytes((p.NESP_REQUEST_MARKER, p.NESP_SVC_SYS, p.NESP_SYS_HELLO)))
        if at >= 0 and len(heard) >= at + p.NESP_OVERHEAD + 3 + p.NESP_APP_ID + 1:
            payload = bytes((p.NESP_PROTOCOL, 0, 1, 0, p.NESP_BOARD_HOST,
                             p.NESP_PAYLOAD_MAX, 1, RAW))
            port.write(nesp.reply_frame(p.NESP_SVC_SYS, p.NESP_ST_NO_SERVICE, heard[at + 3],
                                        payload))
            heard.clear()
    bench.machine.host = old_firmware
    bench.machine.run_until(lambda: state(bench) == "UPDATE THE NESP32", 60)
    bench.machine.pad = PAD_START
    bench.machine.run(30)
    assert state(bench) == "UPDATE THE NESP32" and port.rates == []


# --- a test ----------------------------------------------------------------------------


def test_a_clean_line_reaches_the_top_of_both_ladders(rom):
    bench, began = whole_test(rom, blocks=1)
    failed = half(bench, RX)["FAILED"]
    assert half(bench, RX) == figures(6, to_nes=True, failed=failed)
    assert half(bench, RX)["SPEED"] == "298296 BPS" and half(bench, RX)["CPU"] == "100%"
    # The one rate that fails is the one the console's CPU cannot do.
    assert failed.startswith(FAILED_AT_5) and failed.endswith(" BAD")
    assert int(failed[len(FAILED_AT_5):-4]) > 200
    assert half(bench, TX) == figures(6, to_nes=False)
    assert half(bench, TX)["FASTEST"] == "26713 BYTES/S"
    # Each rate once, from the slowest up, and one direction after the other.
    assert runs(bench) == [("to", period) for period in TO_NES] + [
        ("from", period) for period in FROM_NES]
    # The header is left alone, and the NMI was done with the PPU in vblank.
    header = 32 * (gen_screen.LOGO_LAST_ROW + 1)
    assert bench.machine.nametable()[:header] == gen_screen.build_screen().nametable()[:header]
    assert 0 < bench.machine.late_write < VBLANK_CYCLES


def test_every_exchange_of_a_test_is_made_once_and_the_line_is_else_silent(rom):
    bench, _ = whole_test(rom, blocks=1)
    port = bench.port
    changes = port.rates
    # From the request that agreed to the first run to the reply that said
    # how the last one went: a request for each of the two, a run after
    # another, and not a byte that is not part of one. The controller is
    # not read.
    began = max(cycle for cycle, _ in port.sent if cycle < changes[0][0]) - ms(5)
    ended = min(cycle for cycle, _ in port.sent if cycle > changes[-1][0])
    asked, stray = bench.requests(began, ended)
    assert stray == 0
    assert [(svc, op) for svc, op, _ in asked] == (
        [(RAW, p.NESP_RAW_SEND), (RAW, p.NESP_RAW_RESULT)] * len(TO_NES)
        + [(RAW, p.NESP_RAW_LISTEN), (RAW, p.NESP_RAW_RESULT)] * len(FROM_NES))
    assert bench.stick.repeats == 0

    assert [period for _, period in changes[0::2]] == list(TO_NES) + list(FROM_NES)
    assert {period for _, period in changes[1::2]} == {p.NESP_PERIOD}
    # At a run's rate the UART hears nothing of a run to the console, and of
    # one from it the block, which begins when the console may send.
    for index, ((changed, period), (back, _)) in enumerate(zip(changes[0::2], changes[1::2])):
        heard = b"".join(data for cycle, _, data in bench.heard if changed < cycle <= back + 300)
        edges = [time for time in port.tap.times if changed < time < back]
        agreed = changed - ms(p.NESP_RAW_LISTEN_MS)
        if index < len(TO_NES):
            assert heard == b"" and edges == []
        else:
            assert len(heard) == BLOCK
            assert ms(p.NESP_RAW_SETTLE_MS - 3) <= edges[0] - agreed <= ms(p.NESP_RAW_SETTLE_MS + 5)
        # And nothing is asked until the nesp32 has had its rest.
        after = min(cycle for cycle, _, _ in bench.heard if cycle > back + 300)
        assert after - back >= ms(p.NESP_RAW_REST_MS)


def test_each_direction_stops_at_its_own_line_s_limit(rom):
    # The line to the console rises 4 cycles late, the line back 9; trials
    # are the ROM's own four blocks.
    bench, began = whole_test(rom, to_nes_rise=4.0, from_nes_rise=9.0)
    rx, tx = half(bench, RX), half(bench, TX)
    assert rx == figures(14, to_nes=True, sent=4 * BLOCK, failed=rx["FAILED"])
    assert rx["FAILED"].startswith("137675 BPS, ")
    assert tx == figures(19, to_nes=False, sent=4 * BLOCK, failed=tx["FAILED"])
    assert tx["SPEED"] == "94199 BPS" and tx["FAILED"].startswith("105281 BPS, ")
    assert state(bench) == AGAIN
    # Four blocks at each rate that held, one at the rate that failed, and
    # none past it.
    asked = runs(bench)
    for way, ladder, last in (("to", TO_NES, 14), ("from", FROM_NES, 19)):
        tried = [period for name, period in asked if name == way]
        held = ladder[:ladder.index(last) + 1]
        assert tried == [period for period in held for _ in range(4)] + [
            ladder[len(held)]]


def test_the_screen_follows_the_trial_that_is_running(rom):
    bench = greet(Bench(rom, to_nes_rise=4.0, from_nes_rise=9.0))
    bench.press_start()
    seen = []
    while state(bench) != AGAIN:
        now = dict(half(bench, RX), lower=half(bench, TX)["STATUS"])
        if not seen or seen[-1] != now:
            seen.append(now)
        bench.machine.run(1)
        assert bench.machine.frames < 3000
    climbing = [now for now in seen if now["STATUS"] == "CLIMBING" and now["CPU"]]
    # As each block of the first trial comes in, and then the next rate.
    assert climbing[0] == {"STATUS": "CLIMBING", "SPEED": "9622 BPS", "SENT": "0 BYTES",
                           "BAD": "0 BYTES", "CPU": "3%", "FASTEST": "", "FAILED": "",
                           "lower": "WAITING"}
    # A trial's last block is on the screen with the next trial's first
    # figures, which are the ones that show.
    assert [now["SENT"] for now in climbing[:5]] == [
        "0 BYTES", "256 BYTES", "512 BYTES", "768 BYTES", "0 BYTES"]
    assert (climbing[4]["SPEED"], climbing[4]["CPU"]) == ("19245 BPS", "7%")
    # The trial that failed is up while it runs. The half then goes back to
    # the rate that held, and keeps what failed in a row of its own.
    failing = [now for now in seen if now["SPEED"] == "137675 BPS"]
    assert failing and failing[0]["SENT"] == "0 BYTES"
    assert seen[-1]["SPEED"] == "127841 BPS" and seen[-1]["lower"] == "DONE"
    assert seen[-1]["FAILED"].startswith("137675 BPS, ")


@pytest.mark.parametrize("clock_error", [-0.01, 0.01])
def test_a_nesp32_whose_clock_is_1_percent_off_passes_every_rate(rom, clock_error):
    bench, _ = whole_test(rom, blocks=1, clock_error=clock_error)
    assert half(bench, RX)["SPEED"] == half(bench, TX)["SPEED"] == "298296 BPS"
    assert half(bench, TX)["FAILED"] == "NONE"


def test_a_console_whose_port_reads_otherwise_runs_nothing_to_it(rom):
    bench = greet(Bench(rom, blocks=1, from_nes_rise=9.0))
    bench.machine.port_bits = 0x48
    bench.press_start()
    finish(bench)
    assert half(bench, RX) == dict(BLANK, STATUS="DONE", FASTEST="NONE",
                                   FAILED="$4017 READS $48")
    assert half(bench, TX)["SPEED"] == "94199 BPS"
    assert "to" not in [way for way, _ in runs(bench)]


def test_a_line_that_passes_nothing_says_so(rom):
    # Frames get through, and every run to the console has a bad byte.
    bench = greet(Bench(rom, blocks=1, from_nes_rise=9.0))
    send = bench.machine.wire.send

    def damage(data, at, bit, *rest):
        if bench.port.in_run:
            data = bytes((data[0] ^ 0x04,)) + data[1:]
        return send(data, at, bit, *rest)
    bench.machine.wire.send = damage
    bench.press_start()
    finish(bench)
    rx = half(bench, RX)
    assert rx == {"STATUS": "DONE", "SPEED": "9622 BPS", "SENT": "256 BYTES",
                  "BAD": rx["BAD"], "CPU": "3%", "FASTEST": "NONE",
                  "FAILED": "9622 BPS, %s BAD" % rx["BAD"].split()[0]}
    assert rx["BAD"] != "0 BYTES"
    assert runs(bench)[:2] == [("to", 186), ("from", 186)]


def test_a_run_that_loses_bytes_does_not_hang_the_console(rom):
    """The fast receiver waits for every byte, with no timeout. A run is
    twice a block, so there are bytes enough for it whatever it lost."""
    bench = greet(Bench(rom, blocks=1, from_nes_rise=9.0))
    send = bench.machine.wire.send
    lost = TO_NES[3]
    sent = {}

    def lose(data, at, bit, *rest):
        if bench.port.in_run and bench.port.period == lost:
            start = sent.get("count", 0)
            sent["count"] = start + len(data)
            data = bytes(byte for index, byte in enumerate(data, start)
                         if not 100 <= index < 140)
        return send(data, at, bit, *rest)
    bench.machine.wire.send = lose
    bench.press_start()
    finish(bench)
    rx = half(bench, RX)
    assert rx["SPEED"] == "%d BPS" % rates.baud(TO_NES[2])
    assert rx["FAILED"].startswith("%d BPS, " % rates.baud(lost))
    assert int(rx["FAILED"].split()[2]) > 100   # everything after the gap is out of step
    assert half(bench, TX)["STATUS"] == "DONE"


# --- a sweep --------------------------------------------------------------------------

SWEEP = TO_NES[-10:]            # the ROM's SWEEP_RATES, from 14 cycles a bit
SWEEPING = "SWEEPING"
SWEEP_TOP = gen_screen.HALVES[0][1] + 2


def sweep_rows(bench):
    """The sweep's table: (cycles, speed, what came wrong) a rate, as the
    screen has them."""
    left = gen_screen.LEFT
    rows = []
    for index in range(len(SWEEP)):
        text = bench.machine.text(SWEEP_TOP + index, left, gen_screen.WIDTH)
        rows.append((text[1:5].rstrip(), text[5:16].rstrip(), text[16:].rstrip()))
    return rows


def sweep(rom, **options):
    bench = greet(Bench(rom, **options))
    bench.press_select()
    began = bench.machine.now
    bench.machine.run_until(lambda: state(bench) == SWEEPING, 30)
    bench.machine.run_until(lambda: state(bench) == AGAIN, 6000)
    return bench, began


def checked(period, blocks):
    return (BLOCK - (rates.PREAMBLE if rates.tracked_receive(period) else 0)) * blocks


def test_select_sweeps_every_rate_to_the_console_from_14_cycles(rom):
    assert SWEEP[0] == 14 and SWEEP[-1] == 5
    bench, began = sweep(rom, blocks=1)
    assert runs(bench, began) == [("to", period) for period in SWEEP]
    left, width = gen_screen.LEFT, gen_screen.WIDTH
    assert bench.machine.text(SWEEP_TOP - 2, left, width).rstrip() == "NESP32 TO NES, EVERY RATE"
    assert bench.machine.text(SWEEP_TOP - 1, left, width).rstrip() == " CYC SPEED      BAD OF SENT"
    rows = sweep_rows(bench)
    for period, (cycles, speed, came) in zip(SWEEP, rows):
        assert cycles == str(period) and speed == "%d BPS" % rates.baud(period)
        bad, sent = came.split(" OF ")
        assert int(sent) == checked(period, 1)
        assert (int(bad) == 0) == (period != 5)     # 5 is the rate the CPU cannot do
    # Under the table, and in the rest of the halves' rows, nothing.
    for row in range(SWEEP_TOP + len(SWEEP), gen_screen.HALVES[1][1] + len(ROWS) + 1):
        assert bench.machine.text(row, left, width).strip() == ""


def test_a_sweep_does_not_stop_at_a_rate_that_fails(rom):
    # The line to the console rises 4 cycles late. 13 and 12 cycles a bit
    # do not take that, and 11, 10 and 9 do: how late a rising edge may be
    # is each rate's routine's, and does not shrink rate by rate. A climb
    # stops at 13; the sweep gives every rate its whole trial.
    bench, began = sweep(rom, blocks=2, to_nes_rise=4.0)
    assert runs(bench, began) == [("to", period) for period in SWEEP for _ in range(2)]
    passed = []
    for period, (_, _, came) in zip(SWEEP, sweep_rows(bench)):
        bad, sent = (int(n) for n in came.split(" OF "))
        assert sent == checked(period, 2)
        if bad == 0:
            passed.append(period)
    assert passed == [14, 11, 10, 9]


def test_a_sweep_on_a_console_whose_port_reads_otherwise_runs_nothing(rom):
    bench = greet(Bench(rom, blocks=1))
    bench.machine.port_bits = 0x48
    bench.press_select()
    bench.machine.run_until(lambda: state(bench) == AGAIN, 300)
    assert runs(bench) == []
    assert bench.machine.text(SWEEP_TOP, gen_screen.LEFT).startswith("$4017 READS $48")


def test_a_climb_after_a_sweep_has_the_halves_back(rom):
    bench, _ = sweep(rom, blocks=1)
    bench.press_start()
    bench.machine.run_until(lambda: state(bench) == TESTING, 30)
    bench.machine.run(10)
    assert half(bench, RX)["STATUS"] == "CLIMBING"
    assert half(bench, TX) == dict(BLANK, STATUS="WAITING")
    finish(bench)
    assert half(bench, RX) == figures(6, to_nes=True, failed=half(bench, RX)["FAILED"])
    assert half(bench, TX)["FAILED"] == "NONE"


# --- after a test, and when the nesp32 goes away ---------------------------------------


def test_a_second_test_waits_with_the_first_one_s_results_up(rom):
    bench, _ = whole_test(rom, blocks=1, to_nes_rise=4.0, from_nes_rise=9.0)
    first = half(bench, RX), half(bench, TX)
    done = len(bench.port.rates)
    bench.machine.run(120)
    assert state(bench) == AGAIN and (half(bench, RX), half(bench, TX)) == first
    assert len(bench.port.rates) == done
    bench.press_a()
    bench.machine.run_until(lambda: half(bench, RX)["STATUS"] == "CLIMBING", 30)
    assert half(bench, RX)["FAILED"] == "" and half(bench, TX) == dict(BLANK, STATUS="WAITING")
    finish(bench)
    # The same again, but for how many bytes of another block were bad.
    for now, before in zip((half(bench, RX), half(bench, TX)), first):
        assert dict(now, FAILED="") == dict(before, FAILED="")
        assert now["FAILED"].split(",")[0] == before["FAILED"].split(",")[0]


def test_a_press_during_a_test_does_not_start_another(rom):
    bench = greet(Bench(rom, blocks=1, to_nes_rise=4.0, from_nes_rise=9.0))
    bench.press_start()
    bench.machine.run_until(lambda: len(bench.port.rates) == 6, 600)
    bench.press_a()
    bench.machine.pad = PAD_START   # and Start is still down as it ends
    finish(bench)
    done = len(bench.port.rates)
    bench.machine.pad = 0
    bench.machine.run(120)
    assert state(bench) == AGAIN and len(bench.port.rates) == done


def test_a_nesp32_that_goes_away_is_waited_for(rom):
    bench = greet(Bench(rom))
    bench.detach()
    bench.machine.run_until(lambda: state(bench) == WAITING, 200)
    bench.attach()
    assert state(greet(bench)) == PRESS
    assert bench.stick.app == (b"THRU", 1)


def test_a_nesp32_switched_off_and_on_is_greeted_again(rom):
    bench = greet(Bench(rom))
    bench.attach()              # a new one, which knows of no hello
    assert bench.stick.app[0] != b"THRU"
    bench.machine.run_until(lambda: bench.stick.app == (b"THRU", 1), 30)
    assert state(greet(bench)) == PRESS


def test_a_nesp32_switched_off_and_on_between_blocks_ends_the_test(rom):
    bench = greet(Bench(rom, blocks=1, to_nes_rise=4.0, from_nes_rise=9.0))
    bench.press_start()
    bench.machine.run_until(lambda: len(bench.port.rates) == 10, 600)   # five runs are over
    bench.attach()
    bench.machine.run_until(lambda: state(bench) == PRESS, 200)
    assert half(bench, RX)["STATUS"] == "CLIMBING"      # as it was left
    bench.press_start()
    finish(bench)
    assert half(bench, RX)["SPEED"] == "127841 BPS" and half(bench, TX)["SPEED"] == "94199 BPS"
