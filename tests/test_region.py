"""The console's clock: an NTSC console's or a PAL one's, as the nesp32
hears it from the rate its requests come at (docs/PAL.md).

The same ROM sends at 21 of its CPU's cycles a bit on either console, and
that is 85227 baud on an NTSC one and 79172 on a PAL one. Here the test is
the wire between them: what a UART at one clock's rate makes of bytes sent
at the other's (heard_at), fed to the nesp32 as its link task would.
"""

import bisect

import nesp_proto as p
from nesp import Stick, frame, pattern
from test_peer import HOME, AWAY, FAILED, HOSTING, PLAYER_1, PLAYER_2, carry, connect, lobby, online
from test_peer import HOST, JOIN, CONN_ANSWERED, CONN_CALLED, FAST, rate

SYS, RAW = p.NESP_SVC_SYS, p.NESP_SVC_RAW
NTSC, PAL = p.NESP_REGION_NTSC, p.NESP_REGION_PAL
HZ = {NTSC: p.NESP_CPU_HZ, PAL: p.NESP_PAL_CPU_HZ}
CONTROLLER_READ = b"\xfe"       # what the console's controller read looks like
HUNT_MISSES = 8                 # nesp_core.h's NESP_HUNT_MISSES


def heard_at(data, sent_hz, heard_hz, period=p.NESP_PERIOD, heard_period=None, rest_bits=2):
    """What a UART at heard_period (or `period`) cycles a bit of heard_hz
    hears of bytes sent 8N1 at `period` cycles a bit of sent_hz, with
    rest_bits of mark after
    each: a byte for each start bit it finds, sampled in the middle of each
    of its own bits, kept whatever its stop bit was (the UART hands on a
    byte with a framing error too). It looks for the next start bit from
    the middle of the stop bit, as a UART does."""
    sent_bit, heard_bit = period / sent_hz, (heard_period or period) / heard_hz
    starts, levels = [], []
    for byte in data:
        for level in [0] + [byte >> bit & 1 for bit in range(8)] + [1] * (1 + rest_bits):
            starts.append(len(starts) * sent_bit)
            levels.append(level)
    falls = [starts[at] for at in range(len(starts))
             if levels[at] == 0 and (at == 0 or levels[at - 1] == 1)]

    def level(time):
        at = bisect.bisect_right(starts, time) - 1
        return 1 if at < 0 or at >= len(levels) else levels[at]

    out, at = bytearray(), 0
    while at < len(falls):
        start = falls[at]
        out.append(sum(level(start + (1.5 + bit) * heard_bit) << bit for bit in range(8)))
        at = bisect.bisect_left(falls, start + 9.5 * heard_bit)
    return bytes(out)


def hello(seq=1):
    payload = bytes((p.NESP_PROTOCOL,)) + b"TEST" + bytes((1, p.NESP_PAYLOAD_MAX))
    return frame(SYS, p.NESP_SYS_HELLO, seq, payload)


def says(stick, console, request):
    """A request from a console of that region, heard at the nesp32's clock
    as it is; then the line goes quiet, and the link task says so. The
    reply, b"" for none."""
    reply = stick.feed(heard_at(request, HZ[console], HZ[stick.region]))
    stick.gap()
    return reply


def settled_at(region):
    stick = Stick()
    stick.region = region
    assert says(stick, region, hello())
    assert stick.settled and stick.region == region
    return stick


def test_a_uart_hears_its_own_clock_and_never_the_other():
    requests = [hello(), frame(SYS, p.NESP_SYS_ECHO, 7, bytes(range(40))),
                frame(SYS, p.NESP_SYS_STATUS, 200)]
    for request in requests:
        assert heard_at(request, HZ[NTSC], HZ[NTSC]) == request
        assert heard_at(request, HZ[PAL], HZ[PAL]) == request
    for sent, heard in ((NTSC, PAL), (PAL, NTSC)):
        stick = Stick()
        for request in requests:
            garbled = heard_at(request, HZ[sent], HZ[heard])
            assert garbled != request
            assert stick.feed(garbled) == b""
        assert stick.requests == 0


def test_an_ntsc_console_is_heard_at_once():
    stick = Stick()
    assert (stick.region, stick.settled) == (NTSC, False)
    assert says(stick, NTSC, hello())
    assert (stick.region, stick.settled, stick.hunts) == (NTSC, True, 0)


def test_a_pal_console_is_heard_at_its_second_try():
    stick = Stick()
    assert says(stick, PAL, hello(1)) == b""
    assert (stick.region, stick.settled, stick.hunts) == (PAL, False, 1)
    assert says(stick, PAL, hello(2))
    assert (stick.region, stick.settled) == (PAL, True)


def test_the_clock_kept_is_tried_first():
    stick = Stick()
    stick.region = PAL
    assert says(stick, PAL, hello())
    assert stick.hunts == 0


def test_a_console_of_the_other_region_is_heard_once_enough_tries_have_missed():
    stick = settled_at(PAL)
    for seq in range(HUNT_MISSES - 1):
        assert says(stick, NTSC, hello(seq)) == b""
        assert stick.region == PAL
    assert says(stick, NTSC, hello(9)) == b""
    assert (stick.region, stick.settled, stick.hunts) == (NTSC, False, 1)
    assert says(stick, NTSC, hello(10))


def test_a_request_lost_now_and_then_does_not_change_the_clock():
    stick = settled_at(NTSC)
    for round in range(5):
        for _ in range(HUNT_MISSES - 1):
            assert stick.feed(b"\x4e\x13\x77\x01\x02\x03") == b""
            for _ in range(3):              # quiet, and quiet again: one miss
                stick.gap()
        assert says(stick, NTSC, hello(round))
    assert (stick.region, stick.hunts) == (NTSC, 0)


def test_a_controller_read_is_never_a_miss():
    stick = Stick()
    for _ in range(100):
        stick.feed(CONTROLLER_READ)
        stick.gap()
        stick.feed(CONTROLLER_READ * 2)
        stick.gap()
    assert (stick.region, stick.hunts) == (NTSC, 0)


def test_what_came_at_the_old_clock_is_dropped_with_it():
    stick = Stick()
    stick.feed(heard_at(hello()[:6], HZ[PAL], HZ[NTSC]))
    stick.feed(b"\x4e\x00")                 # a request's start, partway in
    assert stick.gap()
    assert says(stick, PAL, hello())        # nothing held from before gets in its way


def test_a_pal_console_s_run_from_the_nesp32_starts_as_much_later_as_its_settle():
    # The console counts the 150 ms of its settle in cycles: on PAL they
    # are 7.6% longer, and the nesp32's first byte waits as much more.
    stick = settled_at(PAL)
    start = -(-p.NESP_RAW_START_MS * p.NESP_CPU_HZ // p.NESP_PAL_CPU_HZ)
    assert start == 189
    assert stick.hello(services=[RAW]).ok
    word = lambda value: bytes((value & 0xFF, value >> 8))
    assert stick.ask(RAW, p.NESP_RAW_SEND, bytes((8, 0)) + word(0x1234) + word(300)).ok
    stick.tick(1000)
    for now in range(1001, 1000 + start):
        stick.tick(now)
    assert not stick.line.sent
    stick.tick(1000 + start)
    assert bytes(stick.line.sent) == pattern(0x1234, 300)


def test_at_a_session_s_own_rate_what_is_not_heard_is_not_the_clock_s():
    # A console that has gone back to the link's rate before its nesp32
    # has: PEER puts the line back in its own time, and the clock stays.
    host, guest = online(Stick(), HOME), online(Stick(), AWAY)
    connect(host, guest)
    assert rate(host, FAST) == FAST
    host.tick(0)
    assert host.line.rates == [FAST]
    for seq in range(3 * HUNT_MISSES):
        assert host.feed(heard_at(hello(seq), HZ[NTSC], HZ[NTSC], heard_period=FAST)) == b""
        host.gap()
    assert (host.region, host.hunts) == (NTSC, 0)
    host.tick(p.NESP_PEER_RATE_QUIET_MS)
    assert host.line.rates == [FAST, p.NESP_PERIOD]
    assert says(host, NTSC, hello())


def pal(address):
    stick = Stick()
    stick.region = PAL
    return online(stick, address)


def test_two_pal_consoles_play():
    host, guest = pal(HOME), pal(AWAY)
    connect(host, guest)
    assert lobby(host)[0] == PLAYER_1 and lobby(guest)[0] == PLAYER_2


def test_a_pal_console_and_an_ntsc_one_do_not():
    for host, guest in ((pal(HOME), online(Stick(), AWAY)), (online(Stick(), HOME), pal(AWAY))):
        lobby(host, HOST)
        lobby(guest, JOIN, HOME)
        host.conn, guest.conn = CONN_ANSWERED, CONN_CALLED
        for now in range(3):
            host.tick(now)
            guest.tick(now)
            carry(host, guest)
        assert lobby(guest)[0] == FAILED
        assert lobby(host)[0] == HOSTING


def test_a_pal_nesp32_says_so_in_its_greeting():
    host = pal(HOME)
    lobby(host, HOST)
    host.conn = CONN_ANSWERED
    host.tick(0)
    said = host.conn_take()
    assert said[:5] == b"NESP" + bytes((p.NESP_PEER_VERSION | p.NESP_PEER_PAL,))
