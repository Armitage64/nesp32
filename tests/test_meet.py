"""PEER's meeting at the rendezvous (peer.c), with no console and no
Internet: the test answers the nesp32's fetches as the rendezvous would
(server/rendezvous), and is the network that finds the socket's addresses.
What two nesp32s do once they are introduced is test_peer.py's, and on
real sockets test_peer_net.py's."""

import nesp_proto as p
import pytest
from nesp import (CONN_ANSWERED, CONN_CALLED, CONN_FAILED, CONN_MEETING, CONN_MET, CONN_NONE,
                  Stick)
from test_peer import (AWAY, CONNECTING, FAILED, HOME, HOSTING, IDLE, LEAVE, PEER, PLAYER_1,
                       PLAYER_2, STATUS, carry, greeting, lobby, online)

HOST_ROOM, JOIN_ROOM, ROOM = p.NESP_PEER_HOST_ROOM, p.NESP_PEER_JOIN_ROOM, p.NESP_PEER_ROOM
MEETING = p.NESP_LOBBY_MEETING
URL = "https://rendezvous.test"
OUT_THERE = bytes((96, 231, 60, 51))
THEIRS = bytes((172, 56, 33, 198))
HOME_CANDIDATES = [(HOME, 6502), (OUT_THERE, 6502)]
AWAY_CANDIDATES = [(AWAY, 6502), (THEIRS, 41747)]


def room(stick, op=ROOM, payload=b""):
    """A room's op: (state, code, why it failed)."""
    reply = stick.ask(PEER, op, payload)
    assert reply.ok and len(reply.payload) == 11, reply
    return reply.payload[0], reply.payload[6:10], reply.payload[10]


def met(stick, candidates):
    """The socket is open, and its addresses found."""
    assert stick.conn == CONN_MEETING
    stick.candidates = candidates
    stick.conn = CONN_MET


def answer(stick, line, now=0, ok=True):
    """The rendezvous's answer to the fetch that is out."""
    assert stick.fetching, "nothing was asked"
    if line is not None:
        stick.fetch_body(line.encode() + b"\n")
    stick.fetch_done(ok=ok, why=b"" if ok else b"no network")
    stick.tick(now)


@pytest.fixture
def host():
    stick = online(Stick(), HOME)
    stick.set_rendezvous(URL)
    return stick


@pytest.fixture
def guest():
    stick = online(Stick(), AWAY)
    stick.set_rendezvous(URL)
    return stick


def opened(host, code="K7QF", session="1A2B3C4D"):
    assert room(host, HOST_ROOM)[0] == MEETING
    met(host, HOME_CANDIDATES)
    host.tick(0)
    answer(host, f"ROOM {code} {session}")
    assert room(host)[:2] == (HOSTING, code.encode())


def joined(guest, code=b"K7QF", line="HOST 1A2B3C4D 192.168.1.23:6502,96.231.60.51:6502"):
    assert room(guest, JOIN_ROOM, code)[0] == MEETING
    met(guest, AWAY_CANDIDATES)
    guest.tick(0)
    answer(guest, line)


def test_a_host_asks_for_a_room_once_its_addresses_are_found(host):
    assert room(host, HOST_ROOM) == (MEETING, b"    ", p.NESP_MEET_NONE)
    assert host.meets == 1 and host.conn_port == p.NESP_PEER_PORT
    host.tick(0)
    assert host.fetches == 0
    met(host, HOME_CANDIDATES)
    host.tick(0)
    assert host.fetch_url == URL + "/v1/host?app=TEST&ver=1&c=192.168.1.23:6502,96.231.60.51:6502"
    assert host.fetch_agent.startswith("nesp32-peer/")
    assert host.shown(0) == "Opening a room"
    answer(host, "ROOM K7QF 1A2B3C4D")
    assert room(host) == (HOSTING, b"K7QF", p.NESP_MEET_NONE)
    host.tick(1000)
    assert (host.shown(0), host.shown(1)) == ("Room K7QF", "Waiting for player 2")


def test_the_lobbys_other_replies_are_as_they_were(host):
    opened(host)
    assert lobby(host)[0] == HOSTING     # six bytes, as before rooms


def test_a_host_asks_every_little_while_whether_player_2_has_come(host):
    opened(host)
    host.tick(p.NESP_PEER_POLL_MS - 1)
    assert host.fetches == 1
    host.candidates = [(HOME, 6502), (OUT_THERE, 7000)]   # its router's way in moved
    host.tick(p.NESP_PEER_POLL_MS)
    assert host.fetch_url == URL + "/v1/room/K7QF?s=1A2B3C4D&c=192.168.1.23:6502,96.231.60.51:7000"
    answer(host, "WAIT", p.NESP_PEER_POLL_MS)
    host.tick(2 * p.NESP_PEER_POLL_MS)
    assert host.fetches == 3
    answer(host, "GUEST 192.168.1.42:6502,172.56.33.198:41747", 2 * p.NESP_PEER_POLL_MS)
    assert host.punch == (True, 0x1A2B3C4D, AWAY_CANDIDATES)
    assert room(host)[0] == HOSTING


def test_player_2_is_told_the_hosts_addresses_and_calls_them(guest):
    assert room(guest, JOIN_ROOM, b"K7QF") == (MEETING, b"K7QF", p.NESP_MEET_NONE)
    met(guest, AWAY_CANDIDATES)
    guest.tick(0)
    assert guest.fetch_url == (URL + "/v1/join/K7QF?app=TEST&ver=1"
                               "&c=192.168.1.42:6502,172.56.33.198:41747")
    assert (guest.shown(0), guest.shown(1)) == ("Room K7QF", "Joining the game")
    answer(guest, "HOST 1A2B3C4D 192.168.1.23:6502,96.231.60.51:6502")
    assert guest.punch == (False, 0x1A2B3C4D, HOME_CANDIDATES)
    assert room(guest)[0] == CONNECTING


def test_the_two_play_once_introduced(host, guest):
    opened(host)
    joined(guest)
    host.tick(p.NESP_PEER_POLL_MS)
    answer(host, "GUEST 192.168.1.42:6502,172.56.33.198:41747")
    host.conn, guest.conn = CONN_ANSWERED, CONN_CALLED
    for _ in range(2):
        host.tick(0)
        guest.tick(0)
        carry(host, guest)
    assert lobby(host)[0] == PLAYER_1 and lobby(guest)[0] == PLAYER_2
    # A room's code is not an address to keep for LAST.
    assert guest.keeps == 0


@pytest.mark.parametrize("line, reason", [
    ("NOROOM", p.NESP_MEET_NO_ROOM),
    ("MISMATCH", p.NESP_MEET_MISMATCH),
    ("FULL", p.NESP_MEET_FULL),
    ("BAD", p.NESP_MEET_NO_SERVER),
    ("HOST 1A2B3C4D", p.NESP_MEET_NO_SERVER),
    ("HOST nothexes 192.168.1.23:6502", p.NESP_MEET_NO_SERVER),
    ("", p.NESP_MEET_NO_SERVER),
])
def test_a_join_that_is_refused_says_why(guest, line, reason):
    joined(guest, line=line)
    assert room(guest) == (FAILED, b"    ", reason)
    assert guest.conn == CONN_NONE      # the socket is given up


def test_a_rendezvous_that_cannot_be_reached_is_said(guest):
    assert room(guest, JOIN_ROOM, b"K7QF")[0] == MEETING
    met(guest, AWAY_CANDIDATES)
    guest.tick(0)
    answer(guest, None, ok=False)
    assert room(guest)[::2] == (FAILED, p.NESP_MEET_NO_SERVER)
    guest.tick(1000)
    assert guest.shown(0) == "No rendezvous"


@pytest.mark.parametrize("line", ["ROOM K7Q0 1A2B3C4D", "ROOM K7QF 1A2B", "WAIT", "BUSY"])
def test_a_room_that_makes_no_sense_is_none(host, line):
    room(host, HOST_ROOM)
    met(host, HOME_CANDIDATES)
    host.tick(0)
    answer(host, line)
    assert room(host)[::2] == (FAILED, p.NESP_MEET_NO_SERVER)


def test_a_code_is_four_of_the_rooms_letters(guest):
    for code in (b"K7Q0", b"K7QI", b"k7qf", b"K7Q"):
        assert guest.ask(PEER, JOIN_ROOM, code).status == p.NESP_ST_BAD_ARG
    assert guest.meets == 0


def test_a_room_given_up_while_its_host_waits(host):
    opened(host)
    host.tick(p.NESP_PEER_POLL_MS)
    answer(host, "GONE")
    assert room(host)[::2] == (FAILED, p.NESP_MEET_GONE)


def test_a_host_gives_up_after_asks_in_a_row_fail(host):
    opened(host)
    now = 0
    for _ in range(p.NESP_PEER_POLL_FAILS - 1):
        now += p.NESP_PEER_POLL_MS
        host.tick(now)
        answer(host, None, now, ok=False)
        assert room(host)[0] == HOSTING
    now += p.NESP_PEER_POLL_MS
    host.tick(now)
    answer(host, "WAIT", now)       # one that comes through starts the count again
    for _ in range(p.NESP_PEER_POLL_FAILS):
        now += p.NESP_PEER_POLL_MS
        host.tick(now)
        answer(host, None, now, ok=False)
    assert room(host)[::2] == (FAILED, p.NESP_MEET_NO_SERVER)


def test_an_order_already_under_way_changes_nothing(host, guest):
    opened(host)
    assert room(host, HOST_ROOM)[:2] == (HOSTING, b"K7QF")
    assert host.meets == 1
    assert room(guest, JOIN_ROOM, b"K7QF")[0] == MEETING
    assert room(guest, JOIN_ROOM, b"K7QF")[0] == MEETING
    assert guest.meets == 1
    assert room(guest, JOIN_ROOM, b"ABCD")[1] == b"ABCD"
    assert guest.meets == 2


def test_leaving_stops_the_meeting_and_what_was_asked(host):
    opened(host)
    host.tick(p.NESP_PEER_POLL_MS)
    stale = host.fetch_id
    assert lobby(host, LEAVE)[0] == IDLE
    assert host.fetch_stops >= 1
    assert not host.fetch_body(b"GUEST 192.168.1.42:6502\n", fetch=stale)
    host.fetch_done(fetch=stale)
    host.tick(p.NESP_PEER_POLL_MS)
    assert host.punches == 0 and room(host)[0] == IDLE


def test_its_own_address_is_not_called(guest):
    # Behind one carrier's router the host may have the same private
    # address as this nesp32, in another house.
    joined(guest, line="HOST 1A2B3C4D 192.168.1.42:6502,96.231.60.51:6502")
    assert guest.punch[2] == [(OUT_THERE, 6502)]
    online(guest, AWAY)
    joined(guest, line="HOST 1A2B3C4D 192.168.1.42:6502")
    assert room(guest)[::2] == (FAILED, p.NESP_MEET_UNREACHABLE)


def test_two_that_cannot_reach_each_other_are_told(guest):
    joined(guest)
    guest.conn = CONN_FAILED
    guest.tick(0)
    assert room(guest)[::2] == (FAILED, p.NESP_MEET_UNREACHABLE)
    guest.tick(1000)
    assert guest.shown(0) == "Could not reach player"


def test_a_socket_that_goes_while_meeting(guest):
    room(guest, JOIN_ROOM, b"K7QF")
    guest.conn = CONN_FAILED
    guest.tick(0)
    assert room(guest)[::2] == (FAILED, p.NESP_MEET_UNREACHABLE)


def test_another_game_on_the_line_is_not_waited_for_again(host):
    opened(host)
    host.tick(p.NESP_PEER_POLL_MS)
    answer(host, "GUEST 192.168.1.42:6502")
    host.conn = CONN_ANSWERED
    host.tick(0)
    host.conn_give(greeting(app=b"ELSE"))
    host.tick(0)
    assert room(host)[::2] == (FAILED, p.NESP_MEET_MISMATCH)
    assert host.listens == 0


def test_off_the_network_no_room_is_opened(stick):
    stick.set_rendezvous(URL)
    assert stick.hello(services=[PEER]).ok
    assert room(stick, HOST_ROOM)[0] == p.NESP_LOBBY_NO_WIFI
    assert stick.meets == 0


def test_status_says_nothing_of_rooms(host):
    room(host, HOST_ROOM)
    assert len(host.ask(PEER, STATUS).payload) == 6
