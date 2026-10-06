"""RAW, the line with framing off, with no console: requests in, replies
out, and the test as the clock and the UART.

A run is agreed by a request and from there goes by the clock, so every
test here says what time it is (tick) and looks at what the nesp32 did with
its line (stick.line, host/nesp.py's Line).
"""

import nesp_proto as p
import pytest
from nesp import pattern

RAW = p.NESP_SVC_RAW
LINK = p.NESP_PERIOD
LISTEN, START, QUIET = p.NESP_RAW_LISTEN_MS, p.NESP_RAW_START_MS, p.NESP_RAW_QUIET_MS
IDLE, ARMED, RUNNING, DONE, DROPPED = (p.NESP_RUN_IDLE, p.NESP_RUN_ARMED, p.NESP_RUN_RUNNING,
                                       p.NESP_RUN_DONE, p.NESP_RUN_DROPPED)
JUNK = 20               # ms after a change of rate in which what is heard is not the console's


def word(value):
    return bytes((value & 0xFF, value >> 8))


def send(stick, period=8, lead=0, seed=0x1234, count=300):
    return stick.ask(RAW, p.NESP_RAW_SEND, bytes((period, lead)) + word(seed) + word(count))


def listen(stick, period=8, seed=0x1234, count=300):
    return stick.ask(RAW, p.NESP_RAW_LISTEN, bytes((period,)) + word(seed) + word(count))


def result(stick):
    """(state, period, bytes sent or heard, how many of those heard were
    wrong)."""
    reply = stick.ask(RAW, p.NESP_RAW_RESULT)
    assert reply.ok and len(reply.payload) == 6
    data = reply.payload
    return data[0], data[1], data[2] | data[3] << 8, data[4] | data[5] << 8


def run(stick, start, until, step=1):
    """Tick every `step` ms from start up to and including until."""
    for now in range(start, until + 1, step):
        stick.tick(now)


@pytest.fixture
def raw(stick):
    assert stick.hello(services=[RAW]).ok
    return stick


def test_it_answers_only_after_a_hello_asks_for_it(stick):
    assert send(stick).status == p.NESP_ST_INACTIVE
    assert stick.hello(services=[RAW]).ok
    assert result(stick) == (IDLE, 0, 0, 0)


def test_a_run_to_the_console_is_the_pattern_at_its_own_rate(raw):
    assert send(raw, period=8, seed=0x1234, count=300).ok
    line = raw.line
    raw.tick(1000)                              # the clock starts at the first tick
    run(raw, 1001, 1000 + LISTEN - 1)
    assert line.rates == [] and not line.sent   # still listening, at the link's rate
    raw.tick(1000 + LISTEN)
    assert line.rates == [8]
    run(raw, 1000 + LISTEN + 1, 1000 + START - 1)
    assert not line.sent                        # the console is not listening yet
    raw.tick(1000 + START)
    assert bytes(line.sent) == pattern(0x1234, 300)
    assert line.rates == [8, LINK]              # and the line is the link's again
    assert result(raw) == (DONE, 8, 300, 0)


def test_a_lead_of_ff_goes_ahead_of_the_pattern(raw):
    assert send(raw, period=6, lead=8, seed=7, count=248).ok
    run(raw, 0, START)
    assert bytes(raw.line.sent) == b"\xff" * 8 + pattern(7, 248)
    assert result(raw)[2] == 256                # every byte that left


def test_the_same_request_again_starts_the_wait_again(raw):
    """A console that did not hear the reply asks again, a frame later. The
    nesp32 must not change its rate under it."""
    send(raw)
    run(raw, 0, LISTEN - 10)
    send(raw)                                   # the reply is not held for a repeat
    run(raw, LISTEN - 9, 2 * LISTEN - 15)
    assert raw.line.rates == [] and result(raw)[0] == ARMED
    send(raw)
    run(raw, 2 * LISTEN - 14, 2 * LISTEN - 14 + START)
    assert bytes(raw.line.sent) == pattern(0x1234, 300)
    assert raw.repeats == 0


def test_any_other_request_calls_the_run_off(raw):
    send(raw)
    run(raw, 0, 50)
    assert raw.ask(p.NESP_SVC_SYS, p.NESP_SYS_STATUS).ok
    run(raw, 51, 400)
    assert raw.line.rates == [] and not raw.line.sent
    assert result(raw)[0] == DROPPED


def test_a_hello_calls_a_run_off(raw):
    send(raw)
    run(raw, 0, 50)
    assert raw.hello(services=[RAW]).ok
    run(raw, 51, 400)
    assert raw.line.rates == [] and result(raw) == (IDLE, 0, 0, 0)


def test_the_uart_sets_the_pace(raw):
    """The UART takes what it has room for and no more. Nothing is lost,
    and the rate does not go back until the last byte has left."""
    line = raw.line
    line.room = 7
    line.busy = True
    send(raw, count=100)
    run(raw, 0, START)
    assert len(line.sent) == 7
    run(raw, START + 1, START + 30)
    assert bytes(line.sent) == pattern(0x1234, 100)
    assert result_state(raw) == RUNNING and line.rates == [8]
    line.busy = False
    raw.tick(START + 31)
    assert line.rates == [8, LINK] and result(raw) == (DONE, 8, 100, 0)


def result_state(stick):
    return stick.raw_state


def test_while_a_run_has_the_line_what_is_heard_is_not_a_request(raw):
    line = raw.line
    line.busy = True
    send(raw)
    run(raw, 0, START)
    requests = raw.requests
    # The console's bytes at another rate, or a good request by some chance.
    from nesp import frame
    assert raw.feed(frame(p.NESP_SVC_SYS, p.NESP_SYS_STATUS, 99)) == b""
    assert raw.requests == requests and raw.noise == 0


@pytest.mark.parametrize("bad_at", [(), (0,), (5, 6, 299)])
def test_a_run_from_the_console_is_checked_against_the_pattern(raw, bad_at):
    assert listen(raw, period=8, seed=0x4321, count=300).ok
    run(raw, 0, LISTEN + JUNK)
    assert raw.line.rates == [8]
    data = bytearray(pattern(0x4321, 300))
    for index in bad_at:
        data[index] ^= 0x10
    for start in range(0, 300, 37):             # as a UART hands them over
        assert raw.feed(bytes(data[start:start + 37])) == b""
    raw.tick(LISTEN + JUNK + 1)
    assert raw.line.rates == [8, LINK]          # it has them all: no waiting about
    assert result(raw) == (DONE, 8, 300, len(bad_at))


def test_what_is_heard_just_after_the_rate_changes_is_dropped(raw):
    """An ESP32's UART leaves a byte of junk in its receiver when its rate
    changes. Counted, it would put every byte after it out of place."""
    listen(raw, count=10)
    run(raw, 0, LISTEN + 5)
    raw.feed(b"\x00")
    run(raw, LISTEN + 6, LISTEN + JUNK)
    raw.feed(pattern(0x1234, 10))
    raw.tick(LISTEN + JUNK + 1)
    assert result(raw) == (DONE, 8, 10, 0)


def test_a_run_from_the_console_that_stops_short_ends_after_a_quiet_time(raw):
    listen(raw, count=300)
    run(raw, 0, LISTEN + JUNK)
    raw.feed(pattern(0x1234, 120))
    run(raw, LISTEN + JUNK + 1, LISTEN + JUNK + QUIET)
    assert raw.line.rates == [8]
    run(raw, LISTEN + JUNK + QUIET + 1, LISTEN + JUNK + QUIET + 3)
    assert raw.line.rates == [8, LINK]
    assert result(raw) == (DONE, 8, 120, 0)


def test_more_than_was_asked_for_is_not_counted(raw):
    listen(raw, count=10)
    run(raw, 0, LISTEN + JUNK)
    raw.feed(pattern(0x1234, 10) + b"junk")
    raw.tick(LISTEN + JUNK + 1)
    assert result(raw) == (DONE, 8, 10, 0)


def test_a_run_from_the_console_that_never_comes_is_given_up(raw):
    listen(raw)
    run(raw, 0, LISTEN + p.NESP_RAW_GIVE_UP_MS - 1)
    assert raw.line.rates == [8]
    run(raw, LISTEN + p.NESP_RAW_GIVE_UP_MS, LISTEN + p.NESP_RAW_GIVE_UP_MS + 1)
    assert raw.line.rates == [8, LINK]
    assert result(raw) == (DONE, 8, 0, 0)


@pytest.mark.parametrize("payload", [
    bytes((p.NESP_RAW_PERIOD_MIN - 1, 0)) + word(1) + word(1),     # faster than any routine
    bytes((8, 0)) + word(0) + word(1),                              # the pattern has no seed 0
    bytes((8, 0)) + word(1) + word(0),                              # a run of nothing
    bytes((8, 0)) + word(1),                                        # too short
])
def test_a_run_that_cannot_be_is_refused(raw, payload):
    assert raw.ask(RAW, p.NESP_RAW_SEND, payload).status == p.NESP_ST_BAD_ARG
    assert raw.ask(RAW, p.NESP_RAW_LISTEN, payload[:1] + payload[2:]).status == p.NESP_ST_BAD_ARG
    run(raw, 0, 400)
    assert raw.line.rates == [] and result(raw)[0] == IDLE


def test_the_clock_may_wrap(raw):
    send(raw, count=20)
    start = 0xFFFFFFFF - 60
    for now in range(start, start + START + 1):
        raw.tick(now & 0xFFFFFFFF)
    assert bytes(raw.line.sent) == pattern(0x1234, 20)


def test_a_tick_says_whether_another_is_wanted_soon(raw):
    assert raw.tick(0) is False
    send(raw, count=20)
    assert raw.tick(1) is True
    run(raw, 2, 1 + START)
    assert raw.tick(2 + START) is False


# --- on the line -----------------------------------------------------------------------
#
# The same, with the nesp32's UART on the simulated line (wire.py) and the
# test as the console's end of it: the bytes of a run are on the wire when
# and as fast as they should be, and a run from the console is heard at its
# rate.


class Clock:
    """What a Port asks of a console: the time, in CPU cycles."""

    def __init__(self):
        self.now = 0.0


def on_the_line(**options):
    from nesp import Stick
    from wire import Port
    clock = Clock()
    port = Port(clock, **options)
    stick = Stick(port)
    return clock, port, stick


def say(clock, port, stick, data, gap_ms=0.5):
    """Send a request's bytes from the console, at the link's rate, and let
    the nesp32 answer. Returns the reply's bytes."""
    from wire import ms
    bit = LINK
    at = clock.now + ms(gap_ms)
    port.tap.write(at - 1, 1)
    for byte in data:
        port.tap.write(at, 0)
        for index in range(8):
            port.tap.write(at + (1 + index) * bit, (byte >> index) & 1)
        port.tap.write(at + 9 * bit, 1)
        at += 10 * bit
    before = len(port.sent)
    pass_time(clock, stick, until=at + ms(1))
    return port.sent[-1][1] if len(port.sent) > before else b""


def pass_time(clock, stick, until, step=150):
    while clock.now < until:
        clock.now += step
        stick.poll()


def read_wire(port, start, period, count):
    """What a UART at this rate hears of the nesp32 from a cycle on."""
    wire = port.wire
    out = bytearray()
    index = next(i for i, at in enumerate(wire.starts) if at >= start)
    for at, bit, byte in list(zip(wire.starts, wire.bits, wire.bytes))[index:index + count]:
        assert abs(bit - period) < 1e-9
        out.append(byte)
    return bytes(out)


def test_a_run_is_on_the_wire_at_its_rate_from_the_time_it_should_be():
    from nesp import frame, parse
    from wire import ms
    clock, port, stick = on_the_line()
    hello = bytes((p.NESP_PROTOCOL,)) + b"TEST" + bytes((1, 63, RAW))
    assert parse(say(clock, port, stick, frame(p.NESP_SVC_SYS, p.NESP_SYS_HELLO, 1, hello))).ok
    request = frame(RAW, p.NESP_RAW_SEND, 2, bytes((8, 0)) + word(0x1234) + word(600))
    assert parse(say(clock, port, stick, request)).ok
    agreed = port.sent[-1][0]
    pass_time(clock, stick, until=agreed + ms(600))
    changed, back = port.rates
    assert changed[1] == 8 and back[1] == LINK
    # The nesp32's clock is in whole milliseconds, and starts when the request
    # has been answered, not when the reply is on the wire.
    assert ms(LISTEN - 2) <= changed[0] - agreed <= ms(LISTEN + 2)
    start, period, data = port.runs[0]
    assert period == 8 and bytes(data) == pattern(0x1234, 600)
    assert ms(START - 2) <= start - agreed <= ms(START + 2)
    assert read_wire(port, start, 8, 600) == pattern(0x1234, 600)
    # 600 bytes of 11 bits at 8 cycles a bit, and the rate went back when
    # the last had left: the UART held more than half of them at a time.
    assert 0 <= back[0] - (start + 600 * 11 * 8) <= ms(3)
    assert result_of(clock, port, stick) == (DONE, 8, 600, 0)


def result_of(clock, port, stick):
    from nesp import frame, parse
    reply = parse(say(clock, port, stick, frame(RAW, p.NESP_RAW_RESULT, 9)))
    data = reply.payload
    return data[0], data[1], data[2] | data[3] << 8, data[4] | data[5] << 8


@pytest.mark.parametrize("period", [6, 8, 16, 47])
def test_a_run_from_the_console_is_heard_at_its_rate(period):
    from nesp import frame, parse
    from wire import ms
    clock, port, stick = on_the_line()
    hello = bytes((p.NESP_PROTOCOL,)) + b"TEST" + bytes((1, 63, RAW))
    say(clock, port, stick, frame(p.NESP_SVC_SYS, p.NESP_SYS_HELLO, 1, hello))
    request = frame(RAW, p.NESP_RAW_LISTEN, 2, bytes((period,)) + word(0x0BAD) + word(256))
    assert parse(say(clock, port, stick, request)).ok
    agreed = port.sent[-1][0]
    data = bytearray(pattern(0x0BAD, 256))
    data[100] ^= 0xFF
    # The console's bytes, 8N1 at the run's rate, from when it may send.
    at = agreed + ms(p.NESP_RAW_SETTLE_MS)
    for byte in data:
        port.tap.write(at, 0)
        for index in range(8):
            port.tap.write(at + (1 + index) * period, (byte >> index) & 1)
        port.tap.write(at + 9 * period, 1)
        at += 10 * period
    pass_time(clock, stick, until=at + ms(p.NESP_RAW_REST_MS))
    assert [rate for _, rate in port.rates] == [period, LINK]
    assert result_of(clock, port, stick) == (DONE, period, 256, 1)
