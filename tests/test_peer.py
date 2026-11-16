"""PEER, two consoles playing one game, with no console: requests in,
replies out, and the test as the network between two nesp32s.

The connection is the hardware's, and here the stand-in's (host/nesp.py):
the test says when a call is answered (conn), takes what a nesp32 sent to
the other (conn_take) and gives it what came (conn_give).
"""

import nesp
import nesp_proto as p
import pytest
from nesp import (CONN_ANSWERED, CONN_CALLED, CONN_CALLING, CONN_FAILED, CONN_LISTENING,
                  CONN_LOST, CONN_NONE, Stick, frame, parse)

PEER = p.NESP_SVC_PEER
STATUS, HOST, JOIN, LEAVE, LAST, TICKS = (p.NESP_PEER_STATUS, p.NESP_PEER_HOST,
                                          p.NESP_PEER_JOIN, p.NESP_PEER_LEAVE,
                                          p.NESP_PEER_LAST, p.NESP_PEER_TICKS)
NO_WIFI, IDLE, HOSTING, CONNECTING = (p.NESP_LOBBY_NO_WIFI, p.NESP_LOBBY_IDLE,
                                      p.NESP_LOBBY_HOSTING, p.NESP_LOBBY_CONNECTING)
PLAYER_1, PLAYER_2, FAILED = p.NESP_LOBBY_HOST, p.NESP_LOBBY_GUEST, p.NESP_LOBBY_FAILED
HOME, AWAY = bytes((192, 168, 1, 23)), bytes((192, 168, 1, 42))
NOWHERE = bytes(4)


def greeting(app=b"TEST", version=1):
    """What a nesp32 says first to the other."""
    return b"NESP" + bytes((p.NESP_PEER_VERSION,)) + app + bytes((version,))


def online(stick, address=HOME, app=b"TEST", version=1):
    stick.set_wifi(p.NESP_WIFI_JOINED, rssi=-50, address=address)
    assert stick.hello(app=app, version=version, services=[PEER]).ok
    return stick


def lobby(stick, op=STATUS, payload=b""):
    """A lobby op: (state, the address the reply carries)."""
    reply = stick.ask(PEER, op, payload)
    assert reply.ok and len(reply.payload) == 6
    return reply.payload[0], reply.payload[1:5]


def first_delay(stick):
    """The delay a console about to start a session is advised."""
    return stick.ask(PEER, STATUS).payload[5]


def tune(stick, first, wanted, button, delay, late=0, margin=1):
    """A short exchange that carries the console's report: (the other's
    buttons, the delay advised)."""
    report = delay << 5 | min(late, 7) << 2 | min(margin, 3)
    count, data = stick.quick(p.NESP_PEER_TUNE,
                              bytes(((first & 15) << 4 | wanted & 15, button, report)))
    assert count in (0, 1) and len(data) == 2
    return data[:count], data[1]


def quick(stick, first, wanted, buttons=b""):
    """The same exchange as a short frame, with the two ticks as their low
    four bits: (lost, the other's buttons, one tick's at the most), or
    None if the nesp32 made no reply."""
    reply = stick.quick(len(buttons), bytes(((first & 15) << 4 | wanted & 15,)) + bytes(buttons))
    if reply is None:
        return None
    count, data = reply
    assert len(data) == 1
    return (1, b"") if count == p.NESP_SHORT_NONE else (0, data[:count])


def ticks(stick, first, wanted, buttons=b""):
    """A session's exchange: (next, from, lost, the other's buttons)."""
    reply = stick.ask(PEER, TICKS, bytes((first & 0xFF, wanted & 0xFF)) + bytes(buttons))
    assert reply.ok and len(reply.payload) >= 3
    return reply.payload[0], reply.payload[1], reply.payload[2], reply.payload[3:]


def carry(one, other):
    """The network: what each has sent reaches the other."""
    other.conn_give(one.conn_take())
    one.conn_give(other.conn_take())


def connect(host, guest, now=0):
    """HOST on one, JOIN on the other, and the network answers. Both are
    past their greetings."""
    assert lobby(host, HOST)[0] == HOSTING
    assert lobby(guest, JOIN, HOME)[0] == CONNECTING
    host.conn, guest.conn = CONN_ANSWERED, CONN_CALLED
    for _ in range(2):
        host.tick(now)
        guest.tick(now)
        carry(host, guest)
    assert lobby(host)[0] == PLAYER_1 and lobby(guest)[0] == PLAYER_2


@pytest.fixture
def peer(stick):
    return online(stick)


@pytest.fixture
def pair():
    return online(Stick(), HOME), online(Stick(), AWAY)


def test_it_answers_only_after_a_hello_asks_for_it(stick):
    stick.set_wifi(p.NESP_WIFI_JOINED, address=HOME)
    assert stick.ask(PEER, STATUS).status == p.NESP_ST_INACTIVE
    assert stick.hello(services=[PEER]).ok
    assert lobby(stick) == (IDLE, HOME)


def test_off_the_network_nothing_can_be_begun(stick):
    assert stick.hello(services=[PEER]).ok
    assert lobby(stick) == (NO_WIFI, NOWHERE)
    assert lobby(stick, HOST)[0] == NO_WIFI
    assert lobby(stick, JOIN, AWAY)[0] == NO_WIFI
    assert (stick.listens, stick.calls) == (0, 0)


def test_host_waits_for_a_call_and_leave_stops_waiting(peer):
    assert lobby(peer, HOST) == (HOSTING, HOME)
    assert (peer.conn, peer.conn_port) == (CONN_LISTENING, p.NESP_PEER_PORT)
    # Asked again, it is already doing so.
    assert lobby(peer, HOST)[0] == HOSTING
    assert peer.listens == 1
    assert lobby(peer, LEAVE) == (IDLE, HOME)
    assert peer.conn == CONN_NONE


def test_join_calls_the_address_once(peer):
    assert lobby(peer, JOIN, AWAY) == (CONNECTING, HOME)
    assert (peer.conn, peer.conn_target, peer.conn_port) == (CONN_CALLING, AWAY,
                                                           p.NESP_PEER_PORT)
    assert lobby(peer, JOIN, AWAY)[0] == CONNECTING
    assert peer.calls == 1
    # Another address is another call.
    other = bytes((10, 0, 0, 7))
    assert lobby(peer, JOIN, other)[0] == CONNECTING
    assert (peer.calls, peer.conn_target) == (2, other)


def test_join_wants_an_address(peer):
    assert peer.ask(PEER, JOIN, b"\x01\x02\x03").status == p.NESP_ST_BAD_ARG
    assert peer.ask(PEER, HOST, b"\x01").status == p.NESP_ST_BAD_ARG
    assert peer.ask(PEER, 0x20).status == p.NESP_ST_NO_OP
    assert peer.calls == 0


def test_a_call_nobody_answers_fails(peer):
    lobby(peer, JOIN, AWAY)
    peer.conn = CONN_FAILED
    peer.tick(10)
    assert lobby(peer)[0] == FAILED
    assert peer.last is None
    # And it can be tried again.
    assert lobby(peer, JOIN, AWAY)[0] == CONNECTING
    assert peer.calls == 2


def test_a_nesp32_that_cannot_listen_says_so(peer):
    peer.refuse_conns()
    assert lobby(peer, HOST)[0] == FAILED
    assert lobby(peer, JOIN, AWAY)[0] == FAILED


def test_a_wait_that_breaks_is_not_begun_again_by_itself(peer):
    lobby(peer, HOST)
    peer.conn = CONN_FAILED
    peer.tick(10)
    peer.tick(20)
    assert lobby(peer)[0] == FAILED
    assert (peer.conn, peer.listens) == (CONN_NONE, 1)


def test_it_is_a_game_only_once_both_have_said_what_they_are(peer):
    lobby(peer, HOST)
    peer.conn = CONN_ANSWERED
    peer.tick(0)
    assert peer.conn_take() == greeting()
    assert lobby(peer)[0] == HOSTING        # the caller has said nothing yet
    peer.conn_give(greeting()[:6])
    peer.tick(5)
    assert lobby(peer)[0] == HOSTING
    peer.conn_give(greeting()[6:])
    peer.tick(10)
    assert lobby(peer)[0] == PLAYER_1
    assert peer.conn_take() == b""          # its greeting went once


def test_the_one_that_called_is_player_2_and_keeps_the_address(pair):
    host, guest = pair
    assert lobby(guest, LAST) == (IDLE, NOWHERE)
    connect(host, guest)
    assert guest.last == HOME and guest.keeps == 1
    assert host.last is None
    assert lobby(guest, LAST) == (PLAYER_2, HOME)
    # Asked again for what they are already doing, neither begins again.
    assert lobby(host, HOST)[0] == PLAYER_1
    assert lobby(guest, JOIN, HOME)[0] == PLAYER_2
    assert (host.listens, guest.calls) == (1, 1)


def test_the_address_kept_is_there_after_power_off(stick):
    stick.last = AWAY
    online(stick)
    assert lobby(stick, LAST) == (IDLE, AWAY)


@pytest.mark.parametrize("theirs", [b"GET / HTTP", greeting(app=b"TETR"),
                                    greeting(version=2)])
def test_something_else_on_the_port_is_no_game(peer, theirs):
    """Not a nesp32, or another game, or another version of this one. The
    one that hosts goes on waiting for the right caller."""
    lobby(peer, HOST)
    peer.conn = CONN_ANSWERED
    peer.tick(0)
    peer.conn_give(theirs)
    peer.tick(1)
    assert lobby(peer)[0] == HOSTING
    assert (peer.conn, peer.listens) == (CONN_LISTENING, 2)


def test_a_host_that_is_another_game_fails_the_join(pair):
    host, guest = online(Stick(), HOME, app=b"TETR"), pair[1]
    lobby(host, HOST)
    lobby(guest, JOIN, HOME)
    host.conn, guest.conn = CONN_ANSWERED, CONN_CALLED
    for now in range(3):
        host.tick(now)
        guest.tick(now)
        carry(host, guest)
    assert lobby(guest)[0] == FAILED
    assert guest.conn == CONN_NONE and guest.last is None
    assert lobby(host)[0] == HOSTING


def test_a_caller_that_says_nothing_is_given_up(peer):
    lobby(peer, JOIN, AWAY)
    peer.conn = CONN_CALLED
    peer.tick(1000)
    peer.tick(1000 + p.NESP_PEER_GREET_MS - 1)
    assert lobby(peer)[0] == CONNECTING
    peer.tick(1000 + p.NESP_PEER_GREET_MS)
    assert lobby(peer)[0] == FAILED
    assert peer.conn == CONN_NONE


def test_the_greetings_are_wanted_soon_and_a_session_by_its_requests(pair):
    host, guest = pair
    lobby(host, HOST)
    assert not host.tick(0)
    host.conn = CONN_ANSWERED
    assert host.tick(1)                     # until the greetings are over
    host.conn_give(greeting())
    assert not host.tick(2)


def test_buttons_cross_a_byte_a_tick(pair):
    host, guest = pair
    connect(host, guest)
    # Tick 0's buttons from each; neither has the other's yet.
    assert ticks(host, 0, 0, b"\x80") == (1, 0, 0, b"")
    assert ticks(guest, 0, 0, b"\x01") == (1, 0, 0, b"")
    carry(host, guest)
    assert ticks(host, 1, 0, b"\x40") == (2, 0, 0, b"\x01")
    assert ticks(guest, 1, 0, b"\x02") == (2, 0, 0, b"\x80")
    carry(host, guest)
    # Each has taken tick 0 and wants tick 1.
    assert ticks(host, 2, 1) == (2, 1, 0, b"\x02")
    assert ticks(guest, 2, 1) == (2, 1, 0, b"\x40")


def test_buttons_sent_again_are_passed_over(pair):
    host, guest = pair
    connect(host, guest)
    assert ticks(host, 0, 0, b"\x11")[0] == 1
    # The reply was lost: the console sends tick 0 again, with tick 1.
    assert ticks(host, 0, 0, b"\x11\x22")[0] == 2
    assert ticks(host, 0, 0, b"\x11\x22")[0] == 2
    assert ticks(host, 1, 0, b"\x22\x33")[0] == 3
    assert host.conn_take() == b"\x11\x22\x33"
    assert (host.peer_requests, host.peer_repeats) == (4, 1)
    # None of it was a repeat to the link: every one was answered afresh.
    assert host.repeats == 0


def test_the_same_request_again_is_answered_anew(pair):
    host, guest = pair
    connect(host, guest)
    request = frame(PEER, TICKS, 9, b"\x00\x00")
    assert parse(host.feed(request)).payload == b"\x00\x00\x00"
    host.conn_give(b"\x55")
    assert parse(host.feed(request)).payload == b"\x00\x00\x00\x55"


def test_a_frame_carries_two_ticks_at_most(pair):
    host, guest = pair
    connect(host, guest)
    host.conn_give(bytes(range(1, 8)))
    assert ticks(host, 0, 0) == (0, 0, 0, b"\x01\x02")
    assert ticks(host, 0, 2) == (0, 2, 0, b"\x03\x04")
    # Asked for the same tick again, it has the same answer.
    assert ticks(host, 0, 2) == (0, 2, 0, b"\x03\x04")
    assert ticks(host, 0, 3) == (0, 3, 0, b"\x04\x05")
    assert host.ask(PEER, TICKS, b"\x00\x03\x01\x02\x03").status == p.NESP_ST_BAD_ARG
    assert host.ask(PEER, TICKS, b"\x00").status == p.NESP_ST_BAD_ARG


def test_ticks_are_named_by_their_low_byte(pair):
    host, guest = pair
    connect(host, guest)
    for tick in range(600):
        assert ticks(host, tick, tick, bytes((tick & 0xFF,))) == (
            (tick + 1) & 0xFF, tick & 0xFF, 0, b"")
        assert host.conn_take() == bytes((tick & 0xFF,))
        host.conn_give(bytes((0xFF - (tick & 0xFF),)))
        assert ticks(host, tick + 1, tick)[3] == bytes((0xFF - (tick & 0xFF),))


def test_a_connection_with_no_room_takes_what_it_can(pair):
    host, guest = pair
    connect(host, guest)
    host.conn_room(1)
    assert ticks(host, 0, 0, b"\x11\x22")[0] == 1
    assert ticks(host, 1, 0, b"\x22")[0] == 2
    assert host.conn_take() == b"\x11\x22"


def test_the_other_console_goes_away(pair):
    """What it sent before it went is still handed over, and then the
    console is told."""
    host, guest = pair
    connect(host, guest)
    host.conn_give(b"\x01\x02\x03")
    host.conn = CONN_LOST
    host.tick(50)
    assert ticks(host, 0, 0) == (0, 0, 0, b"\x01\x02")
    assert ticks(host, 0, 2) == (0, 2, 0, b"\x03")
    assert ticks(host, 0, 3) == (0, 3, 1, b"")
    assert lobby(host)[0] == FAILED
    # Nothing more goes out, and the console can host again.
    assert ticks(host, 0, 3, b"\x80")[0] == 0
    assert lobby(host, HOST)[0] == HOSTING


def test_with_no_session_the_other_console_is_gone(peer):
    assert ticks(peer, 7, 9, b"\x80") == (7, 9, 1, b"")
    lobby(peer, HOST)
    assert ticks(peer, 7, 9) == (7, 9, 1, b"")


def test_a_hello_ends_the_game(pair):
    host, guest = pair
    connect(host, guest)
    assert host.hello(services=[PEER]).ok   # the console was reset
    assert host.conn == CONN_NONE
    assert lobby(host)[0] == IDLE
    assert host.shown(0) == ""


def test_the_network_going_ends_the_game(pair):
    host, guest = pair
    connect(host, guest)
    host.set_wifi(p.NESP_WIFI_IDLE)
    assert lobby(host) == (NO_WIFI, NOWHERE)
    assert host.conn == CONN_NONE
    assert ticks(host, 0, 0)[2] == 1


def test_the_nesp32s_screen_says_how_it_stands(pair):
    host, guest = pair
    host.tick(0)
    assert (host.shown(0), host.shown(1)) == ("", "")
    lobby(host, HOST)
    host.tick(1)
    assert (host.shown(0), host.shown(1)) == ("192.168.1.23", "Waiting for player 2")
    lobby(guest, JOIN, HOME)
    guest.tick(1)
    assert (guest.shown(0), guest.shown(1)) == ("192.168.1.23", "Joining the game")
    host.conn, guest.conn = CONN_ANSWERED, CONN_CALLED
    for now in (2, 3):
        host.tick(now)
        guest.tick(now)
        carry(host, guest)
    ticks(host, 0, 0, b"\x01")
    ticks(host, 1, 0)                   # nothing new to send: its game stood still
    ticks(host, 0, 0, b"\x01")          # the same again: it did not hear the reply
    host.tick(1000)
    guest.tick(1000)
    assert (host.shown(0), host.shown(1)) == ("Player 1", "late frames: 66.7%")
    assert guest.shown(0) == "Player 2"
    guest.conn = CONN_LOST
    guest.tick(1001)
    assert guest.shown(0) == "Player 2: peer disconnected"


# --- the end of a session, in the log -------------------------------------------------

FRAME_MS = 17
STOPPED_MS = 1000


def stream(seed, digests):
    """A console's bytes, a tick each: buttons, and at each tick whose low
    byte is FF a digest, from `digests` by the tick, else 0x5A."""
    return [digests.get(tick, 0x5A) if tick & 0xFF == 0xFF else (tick * seed) & 0x7F
            for tick in range(2000)]


def play(host, ours, theirs, first, last, came=None, at=0):
    """A frame at a time from `at` ms, for ticks `first` to before `last`:
    the other's buttons for the tick come over the network, up to before
    tick `came`, and the console makes its exchange with its own. Returns
    the clock."""
    came = last if came is None else came
    for tick in range(first, last):
        host.tick(at)
        if tick < came:
            host.conn_give(bytes((theirs[tick],)))
        ticks(host, tick, min(tick, came), bytes((ours[tick],)))
        host.conn_take()
        at += FRAME_MS
    return at


def test_digests_that_differ_are_logged_when_the_console_stops(pair):
    """Two alike, at ticks 255 and 511, and then not, at 767: both consoles
    give the session up, and go back to the title, where they make no more
    exchanges."""
    host, guest = pair
    connect(host, guest)
    ours = stream(3, {})
    theirs = stream(5, {767: 0x3C})
    at = play(host, ours, theirs, 0, 768)
    host.tick(at + STOPPED_MS - FRAME_MS - 1)
    assert host.watched.startswith("player 1,")       # the session's line, as it was
    host.tick(at + STOPPED_MS)
    assert host.watched == ("session over, the console stopped: ticks 768 sent, 768 came, "
                            "the last 0 ms before the end; digests alike 2, then differed at "
                            "tick 767: this 5a, the other 3c")
    # Said once, and nothing more of the session.
    host.tick(at + STOPPED_MS + 5000)
    assert host.watched.startswith("session over, the console stopped:")


def test_the_others_buttons_not_coming_are_logged(pair):
    """The other console's last came at tick 299, and this one went on for
    240 NMIs before it gave up: the line says when they stopped coming, and
    that tick 511's digest was this one's alone."""
    host, guest = pair
    connect(host, guest)
    ours, theirs = stream(3, {}), stream(5, {})
    at = play(host, ours, theirs, 0, 540, came=300)
    host.tick(at + STOPPED_MS)
    assert host.watched == ("session over, the console stopped: ticks 540 sent, 300 came, the "
                            "last %d ms before the end; digests alike 1, the other's at tick 511 "
                            "not come" % (240 * FRAME_MS))


def test_the_others_buttons_after_the_end_say_so(pair):
    """This console stopped first: the other's still came for a while."""
    host, guest = pair
    connect(host, guest)
    ours, theirs = stream(3, {}), stream(5, {})
    at = play(host, ours, theirs, 0, 50)
    host.conn_give(bytes(theirs[50:52]))
    host.tick(at + 30)
    host.tick(at + STOPPED_MS)
    assert host.watched.startswith("session over, the console stopped: ticks 50 sent, 52 came, "
                                   "the last %d ms after the end;" % (30 + FRAME_MS))


def test_a_lost_connection_is_logged(pair):
    host, guest = pair
    connect(host, guest)
    ours, theirs = stream(3, {}), stream(5, {})
    at = play(host, ours, theirs, 0, 100)
    host.conn = CONN_LOST
    at = play(host, ours, theirs, 100, 103, came=100, at=at)
    host.tick(at + STOPPED_MS)
    assert host.watched == ("session over, the console stopped: ticks 100 sent, 100 came, "
                            "the last %d ms before the end; digests alike 0; connection lost "
                            "%d ms before the end" % (3 * FRAME_MS, 2 * FRAME_MS))


def test_a_hello_mid_session_is_logged(pair):
    """The console reset by its player: no wait for it to stop."""
    host, guest = pair
    connect(host, guest)
    play(host, stream(3, {}), stream(5, {}), 0, 300)
    assert host.hello(services=[PEER]).ok
    assert host.watched == ("session over, a hello: ticks 300 sent, 300 came, the last %d ms "
                            "before the end; digests alike 1" % 0)


def test_a_session_left_from_the_menu_is_logged(pair):
    host, guest = pair
    connect(host, guest)
    play(host, stream(3, {}), stream(5, {}), 0, 10)
    lobby(host, LEAVE)
    assert host.watched.startswith("session over, left: ticks 10 sent, 10 came")


def test_a_session_with_no_exchange_says_nothing_of_its_end(pair):
    host, guest = pair
    connect(host, guest)
    host.tick(0)
    host.tick(STOPPED_MS * 5)
    lobby(host, LEAVE)
    assert not host.watched.startswith("session over")


# --- a console's RAM, for the log (DUMP) ---------------------------------------------

DUMP = p.NESP_PEER_DUMP
RAM = bytes((index * 7 + (index >> 8)) & 0xFF for index in range(p.NESP_PEER_DUMP_BYTES))


def send_dump(stick, ram=RAM, piece=64, order=None):
    """The console's RAM in pieces, as a netplay ROM sends it."""
    starts = list(range(0, len(ram), piece)) if order is None else order
    for start in starts:
        payload = bytes((start & 0xFF, start >> 8)) + ram[start:start + piece]
        reply = stick.ask(PEER, DUMP, payload)
        assert reply.ok and reply.payload == b""


def dump_lines(stick, at, frames=60):
    """Every line the log is given, a tick each 20 ms from `at` ms."""
    lines = []
    count = stick.watch_count
    for now in range(at, at + frames * 20, 20):
        stick.tick(now)
        new = stick.watch_count - count
        count = stick.watch_count
        if new:
            lines += stick.watched_lines[-new:]
    return lines


def test_the_ram_of_a_console_whose_digest_differed_goes_to_the_log(pair):
    """A line every 100 ms, 64 bytes in hex each, after one that says what
    they are."""
    host, guest = pair
    connect(host, guest)
    theirs = stream(5, {767: 0x3C})
    at = play(host, stream(3, {}), theirs, 0, 768)
    send_dump(host)
    lines = dump_lines(host, at, frames=200)
    dumped = [line for line in lines if line.startswith("dump")]
    assert dumped[0] == ("dump of the console's RAM, as it stood at tick 767, whose digests "
                         "differed: 2048 bytes")
    assert len(dumped) == 1 + 2048 // 64
    assert dumped[1] == "dump 0000: " + RAM[:64].hex()
    assert dumped[-1] == "dump 07c0: " + RAM[0x7C0:].hex()
    assert bytes.fromhex("".join(line.split(": ")[1] for line in dumped[1:])) == RAM


def test_the_lines_go_no_faster_than_the_log_takes_them(pair):
    host, guest = pair
    connect(host, guest)
    send_dump(host)
    host.tick(0)
    for now in range(1, p.NESP_PEER_DUMP_EVERY_MS):
        host.tick(now)
    assert host.watched.startswith("dump of the console's RAM: 2048 bytes")
    host.tick(p.NESP_PEER_DUMP_EVERY_MS)
    assert host.watched.startswith("dump 0000: ")


def test_a_dump_goes_on_being_said_after_a_hello(pair):
    """The console gave the session up, and went to its menu at once."""
    host, guest = pair
    connect(host, guest)
    send_dump(host)
    host.tick(0)
    assert host.hello(services=[PEER]).ok
    lines = dump_lines(host, 20, frames=200)
    assert lines[-1] == "dump 07c0: " + RAM[0x7C0:].hex()


def test_pieces_in_any_order_and_again_end_at_the_last(pair):
    host, guest = pair
    connect(host, guest)
    send_dump(host, order=[64, 0, 0, 128] + list(range(192, 2048, 64)))
    lines = dump_lines(host, 0, frames=200)
    assert lines[1] == "dump 0000: " + RAM[:64].hex()
    assert lines[-1] == "dump 07c0: " + RAM[0x7C0:].hex()


def test_a_piece_past_the_end_is_refused(pair):
    host, guest = pair
    connect(host, guest)
    for payload in (b"", b"\x00", b"\xf0\x07" + bytes(17), b"\x00\x08\x01"):
        assert host.ask(PEER, DUMP, payload).status == p.NESP_ST_BAD_ARG
    assert host.ask(PEER, DUMP, b"\x00\x08").ok        # nothing, at the end: nothing to say
    host.tick(1000)
    assert not host.watched.startswith("dump")


# --- short frames ------------------------------------------------------------------


def test_a_short_frame_is_the_same_exchange(pair):
    host, guest = pair
    connect(host, guest)
    assert quick(host, 0, 0, b"\x81") == (0, b"")
    assert quick(guest, 0, 0, b"\x42\x43") == (0, b"")
    carry(host, guest)
    # One tick of the other's buttons to a reply: the rest wait their turn.
    assert quick(host, 1, 0, b"\x82") == (0, b"\x42")
    assert quick(host, 2, 1) == (0, b"\x43")
    assert quick(guest, 2, 0) == (0, b"\x81")
    carry(host, guest)
    assert quick(guest, 2, 1) == (0, b"\x82")
    # And it is the same session to an exchange made the long way.
    assert ticks(host, 2, 2) == (2, 2, 0, b"")


def test_a_short_frame_sent_again_is_passed_over(pair):
    host, guest = pair
    connect(host, guest)
    assert quick(host, 0, 0, b"\x01") == (0, b"")
    assert quick(host, 0, 0, b"\x01\x02") == (0, b"")
    assert quick(host, 0, 0, b"\x01\x02") == (0, b"")
    assert host.conn_take() == b"\x01\x02"


def test_a_short_frame_names_ticks_by_four_bits(pair):
    host, guest = pair
    connect(host, guest)
    for tick in range(40):
        assert quick(host, tick, tick, bytes((tick,))) == (0, b"")
        assert quick(guest, tick, tick, bytes((tick ^ 0xFF,))) == (0, b"")
        carry(host, guest)
        assert quick(host, tick + 1, tick) == (0, bytes((tick ^ 0xFF,)))
        assert quick(guest, tick + 1, tick) == (0, bytes((tick,)))
        # What was taken is not handed over twice.
        assert quick(host, tick + 1, tick + 1) == (0, b"")
        assert quick(guest, tick + 1, tick + 1) == (0, b"")


def test_a_short_reply_says_the_buttons_are_held_or_is_not_made(pair):
    """A reply names no ticks: that it comes says the nesp32 holds what it
    was sent. With no room for all of it there is none, and the console
    asks again."""
    host, guest = pair
    connect(host, guest)
    host.conn_room(1)
    assert quick(host, 0, 0, b"\x01\x02") is None
    assert quick(host, 0, 0, b"\x01\x02") == (0, b"")      # the second went this time
    assert host.conn_take() == b"\x01\x02"


def test_a_short_reply_is_checked_against_its_request(pair):
    host, guest = pair
    connect(host, guest)
    request = nesp.short_frame(1, b"\x00\x55")
    reply = host.feed(request)
    assert len(reply) == 4 and nesp.parse_short(reply, request) == (0, b"\x00")
    other = nesp.short_frame(1, b"\x10\x55")               # another request's ticks
    with pytest.raises(ValueError):
        nesp.parse_short(reply, other)


def test_a_short_frame_with_no_session_says_so(peer):
    assert quick(peer, 0, 0, b"\x55") == (1, b"")
    assert peer.conn_take() == b""


def test_a_short_frame_says_when_the_other_console_is_gone(pair):
    host, guest = pair
    connect(host, guest)
    assert quick(guest, 0, 0, b"\x07") == (0, b"")
    carry(host, guest)
    host.conn = CONN_LOST
    # What it sent before it went is still handed over, and only then:
    # also to a console that has buttons of its own to send, which go
    # nowhere now.
    assert quick(host, 0, 0, b"\x31") == (0, b"\x07")
    assert quick(host, 0, 1, b"\x31") == (1, b"")


def test_a_short_frame_before_any_hello_is_answered_with_none(stick):
    assert stick.quick(0) == (p.NESP_SHORT_NONE, bytes(1))


def test_a_short_frame_behind_noise_and_a_bad_one(pair):
    host, guest = pair
    connect(host, guest)
    good = nesp.short_frame(1, b"\x00\x99")
    bad = bytearray(good)
    bad[2] ^= 0x10
    reply = host.feed(b"\xD1\x00" + bytes(bad) + good)
    assert nesp.parse_short(reply, good)[0] == 0
    assert host.conn_take() == b"\x99"


def test_short_requests_are_five_bytes_or_six(pair):
    host, guest = pair
    connect(host, guest)
    assert [len(nesp.short_frame(count, b"\x00")) for count in range(4)] == [5, 5, 6, 6]
    for count in range(3):
        assert len(host.feed(nesp.short_frame(count, b"\x00\x01\x02"))) == 4
    assert len(host.feed(nesp.short_frame(p.NESP_PEER_TUNE, b"\x30\x03\x40"))) == 5


# --- the delay ----------------------------------------------------------------------


def test_the_delay_to_begin_with_is_from_the_networks_time(pair):
    host, guest = pair
    assert first_delay(host) == 0               # no session: nothing to advise
    connect(host, guest)
    assert first_delay(host) == p.NESP_PEER_DELAY_UNKNOWN
    for rtt_ms, delay in ((4, 1), (14, 1), (16, 2), (40, 2), (60, 3), (100, 4), (400, 5)):
        host.rtt = rtt_ms * 1000
        assert first_delay(host) == delay, rtt_ms


def test_a_report_rides_a_short_frame_and_is_passed_on_as_a_note(pair):
    host, guest = pair
    connect(host, guest)
    assert quick(guest, 0, 0, b"\x42") == (0, b"")
    carry(host, guest)
    host.tick(5000)
    assert host.notes == 1                      # the one that cleared it for the session
    assert tune(host, 0, 0, 0x81, delay=2, late=4, margin=3) == (b"\x42", 2)
    assert host.conn_take() == b"\x81"          # the button went as any other
    # A session's first report is of its start, and says nothing either way.
    assert host.note_take() == bytes((1, 0, 1, 2))
    # The same report asked again, its reply not heard, is not a second one.
    tune(host, 0, 0, 0x81, delay=2, late=5, margin=1)
    assert host.notes == 2
    host.tick(6000)
    tune(host, 1, 1, 0x82, delay=2, late=4, margin=2)
    assert host.note_take() == bytes((2, 4, 2, 2))
    host.tick(1000)
    host.tick(1001)
    assert host.shown(0) == "Player 1"          # the screen says no more than it did


def measured(stick, now, **times):
    """The network's times since the console's last report, as how many of
    them each delay covers (d1=, d2= ... and over= for those none does), and
    then the report: the delay the console keeps is 2. Returns the advice."""
    for name, count in times.items():
        ticks = 6 if name == "over" else int(name[1:])
        stick.took((ticks * 16667 - 9000 - 100) * 2, count)
    stick.tick(now)
    return tune(stick, 0, 0, 0, delay=2)[1]


def test_the_delay_covers_most_of_the_networks_times_and_not_the_worst(pair):
    host, guest = pair
    connect(host, guest)
    # Nine in ten within what 2 covers: it stays, whatever the rest are.
    assert measured(host, 2000, d1=50, d2=40, over=10) == 2
    assert measured(host, 4000, d1=50, d2=40, d5=10) == 2
    # Fewer than that, twice running, and it is what does cover them.
    assert measured(host, 6000, d1=50, d2=30, d3=15, over=5) == 2
    assert measured(host, 8000, d1=50, d2=30, d3=15, over=5) == 3
    # Once is not enough.
    assert measured(host, 10000, d2=50, d5=50) == 3
    assert measured(host, 12000, d1=20, d3=80) == 3
    assert measured(host, 14000, d2=50, d5=50) == 3
    assert measured(host, 16000, d2=50, d5=50) == 5
    # Nothing covers a network that is mostly worse than the longest delay.
    assert measured(host, 18000, over=100) == 5


def test_a_shorter_delay_is_advised_only_after_a_while(pair):
    host, guest = pair
    connect(host, guest)
    host.tick(1000)
    assert tune(host, 0, 0, 0, delay=2)[1] == 2
    now = 1000
    for _ in range(p.NESP_PEER_CALM - 1):
        now += 2000
        assert measured(host, now, d1=95, d3=5) == 2
    # A report that wants what it has, and the count begins again.
    now += 2000
    assert measured(host, now, d1=50, d2=50) == 2
    for _ in range(p.NESP_PEER_CALM - 1):
        now += 2000
        assert measured(host, now, d1=95, d3=5) == 2
    now += 2000
    assert measured(host, now, d1=95, d3=5) == 1
    for _ in range(3 * p.NESP_PEER_CALM):
        now += 2000
        assert measured(host, now, d1=100) == 1     # and never less than 1


def test_a_sessions_first_report_sets_the_delay_outright(pair):
    """The delay a session begins with is from the first packet or two, or
    is 2 with none. A second or so in, the first report has every time
    since the session's first exchange, and what covers them is advised at once:
    shorter with no wait of eight reports, or longer with none of two."""
    host, guest = pair
    connect(host, guest)
    assert quick(host, 0, 0) == (0, b"")            # the session's first exchange
    host.took((4 * 16667 - 9100) * 2)               # one slow packet
    host.took(4000, 60)
    host.tick(1000)
    assert tune(host, 0, 0, 0, delay=4)[1] == 1
    # And from there as ever: once is not enough.
    assert measured(host, 3000, d3=100) == 1
    assert measured(host, 5000, d3=100) == 3


def test_the_networks_times_from_before_the_game_are_not_counted(pair):
    """While the two wait for their consoles they say little, and that is
    not a game's traffic. A session's first report is of the times since
    its first exchange."""
    host, guest = pair
    connect(host, guest)
    host.took(60000, 80)                            # in the lobby
    assert quick(host, 0, 0) == (0, b"")            # the session's first exchange
    host.took(4000, 60)
    host.tick(1000)
    assert tune(host, 0, 0, 0, delay=1)[1] == 1


def test_a_sessions_first_report_may_make_the_delay_longer(pair):
    host, guest = pair
    connect(host, guest)
    assert quick(host, 0, 0) == (0, b"")
    host.took(60000, 60)
    host.tick(1000)
    assert tune(host, 0, 0, 0, delay=1)[1] == 3


def test_too_few_measurements_say_nothing(pair):
    host, guest = pair
    connect(host, guest)
    for now in (2000, 4000, 6000, 8000):
        assert measured(host, now, d5=p.NESP_PEER_FEW - 1) == 2


def test_a_report_asked_again_is_one_report(pair):
    """Its reply was not heard: the same measurements are not counted
    twice towards a longer delay."""
    host, guest = pair
    connect(host, guest)
    assert measured(host, 1000, d2=100) == 2        # the session's first
    assert measured(host, 2000, d4=100) == 2
    host.took(1000, 100)
    assert tune(host, 0, 0, 0, delay=2)[1] == 2     # at once: the same report
    assert measured(host, 4000, d4=100) == 4


def test_a_console_that_does_not_know_its_delay_is_told_one(pair):
    host, guest = pair
    connect(host, guest)
    host.rtt = 60000
    host.tick(1000)
    assert tune(host, 0, 0, 0, delay=0)[1] == 3
    assert host.notes == 1                      # and that is no report to pass on


# --- a session's line at a rate of its own (RATE) ---------------------------------

RATE = p.NESP_PEER_RATE
FAST = 14


def rate(stick, period):
    reply = stick.ask(PEER, RATE, bytes((period,)))
    assert reply.ok and len(reply.payload) == 1
    return reply.payload[0]


def test_a_session_asks_for_a_faster_line_and_has_it_once_the_answer_has_gone(pair):
    host, guest = pair
    connect(host, guest)
    host.line.busy = True               # the answer still on its way out
    assert rate(host, FAST) == FAST
    host.tick(10)
    assert host.line.rates == []
    host.line.busy = False
    host.tick(11)
    assert host.line.rates == [FAST]
    assert guest.line.rates == []       # the other console's line is its own


def test_the_faster_line_holds_while_frames_come_and_goes_back_when_they_stop(pair):
    host, guest = pair
    connect(host, guest)
    assert rate(host, FAST) == FAST
    host.tick(0)
    for now in range(0, 3000, 17):      # an exchange a frame, the scene's loads between
        host.tick(now)
        if now % 340 < 170:
            quick(host, 0, 0)
    assert host.line.rates == [FAST]
    host.tick(3000 + p.NESP_PEER_RATE_QUIET_MS)    # the console was reset: nothing heard
    assert host.line.rates == [FAST, p.NESP_PERIOD]
    assert host.hello(services=[PEER]).ok          # at the link's rate, heard again


def test_with_no_session_the_line_stays_the_links(peer):
    assert rate(peer, FAST) == 0
    peer.tick(0)
    assert peer.line.rates == []


def test_a_rate_out_of_bounds_is_refused(pair):
    host, guest = pair
    connect(host, guest)
    for payload in (b"", bytes((p.NESP_PEER_RATE_MIN - 1,)), bytes((p.NESP_PERIOD + 1,)),
                    bytes((FAST, 0))):
        assert host.ask(PEER, RATE, payload).status == p.NESP_ST_BAD_ARG
    assert rate(host, p.NESP_PERIOD) == 0          # the link's own: no change
    host.tick(0)
    assert host.line.rates == []


def test_a_session_that_does_not_ask_is_never_at_another_rate(pair):
    """A netplay ROM built before RATE: its serial routines know one rate."""
    host, guest = pair
    connect(host, guest)
    for now in range(0, 2000, 17):
        host.tick(now)
        quick(host, 0, 0)
    assert host.line.rates == []


def test_a_new_hello_puts_the_line_back(pair):
    host, guest = pair
    connect(host, guest)
    assert rate(host, FAST) == FAST
    host.tick(0)
    assert host.hello(services=[]).ok              # another ROM, which wants no PEER
    assert host.line.rates == [FAST, p.NESP_PERIOD]


def test_the_log_says_what_rate_the_line_is_at(pair):
    host, guest = pair
    connect(host, guest)
    host.tick(0)
    assert rate(host, FAST) == FAST
    host.tick(10)
    assert host.watched == "line at %d cycles a bit: the session's, as its console asked" % FAST
    for now in range(10, 2100, 17):     # an exchange a frame, to the session's next log
        quick(host, 0, 0)
        host.tick(now)
    assert host.watched.startswith("player 1, line %d, delay" % FAST)
    host.tick(3000 + p.NESP_PEER_RATE_QUIET_MS)
    # And in the same tick, the console having stopped, the session's end.
    assert host.watched_lines[-2:] == [
        "line at %d cycles a bit: the link's again, nothing heard at the session's"
        % p.NESP_PERIOD,
        "session over, the console stopped: ticks 0 sent, 0 came; digests alike 0"]


# --- a short request that lost a byte (nesp_link_gap) --------------------------------

def damaged_then_whole(stick, gap):
    """This console's buttons for tick 15, nothing pressed, as a short
    request: its 0 lost on the line, and the request again once its wait
    for a reply ran out. What the bytes left of the first and the first of
    the second make passes the CRC."""
    request = nesp.short_frame(1, bytes((0xFD, 0x00)))
    assert request == bytes.fromhex("d1fd00fba5")
    assert bytes(nesp.checks(bytes.fromhex("d1fdfb"))) == bytes.fromhex("a5d1")
    stick.feed(request[:2] + request[3:])
    if gap:
        stick.gap()                     # the line quiet for the wait
    stick.feed(request)


def session_at_tick_15(pair):
    host, guest = pair
    connect(host, guest)
    for tick in range(15):
        quick(host, tick, 0, b"\x00")
        quick(guest, tick, 0, b"\x00")
        carry(host, guest)
        carry(guest, host)
    return host, guest


def test_a_request_that_lost_a_byte_is_not_made_whole_by_the_next(pair):
    host, guest = session_at_tick_15(pair)
    damaged_then_whole(host, gap=True)
    carry(host, guest)
    for tick in range(15):
        quick(guest, 15, tick, b"")
    assert quick(guest, 15, 15, b"") == (0, b"\x00")    # nothing pressed, as sent


def test_without_the_gap_the_damaged_request_passes(pair):
    """What the gap is for: the bytes alone, with no gap between them, give
    the other console a tick of buttons nobody pressed (the CRC's own first
    byte)."""
    host, guest = session_at_tick_15(pair)
    damaged_then_whole(host, gap=False)
    carry(host, guest)
    for tick in range(15):
        quick(guest, 15, tick, b"")
    assert quick(guest, 15, 15, b"") == (0, b"\xfb")


def test_a_gap_before_a_request_does_not_hide_it(pair):
    """Noise from the controller's read, the line quiet, and the request:
    the noise is passed over and the request answered."""
    host, guest = pair
    connect(host, guest)
    host.feed(b"\xfe")
    host.gap()
    count, data = host.quick(1, bytes((0x00, 0x05)))
    assert count == 0
