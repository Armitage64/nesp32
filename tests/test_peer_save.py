"""PEER's save: before a session's first tick, the host console's save is
copied to the other's, if the two differ (SAVE, SAVE_PUT, SAVE_GET,
SAVE_DONE). Two nesp32s with no console, and the test as the network, as
in test_peer.py."""

import random

import nesp_proto as p
import pytest
from nesp import CONN_LOST, Stick

from test_peer import AWAY, HOME, PEER, carry, connect, online, ticks

SAVE, PUT, GET, DONE = (p.NESP_PEER_SAVE, p.NESP_PEER_SAVE_PUT, p.NESP_PEER_SAVE_GET,
                        p.NESP_PEER_SAVE_DONE)
WAITING, SAME, DIFFERENT, COPIED, GONE = (p.NESP_SAVE_WAITING, p.NESP_SAVE_SAME,
                                          p.NESP_SAVE_DIFFERENT, p.NESP_SAVE_DONE,
                                          p.NESP_SAVE_GONE)
REPLY_MAX = 64                  # the netplay ROM's replies


@pytest.fixture
def pair():
    return (online(Stick(), HOME, app=b"TSBO"), online(Stick(), AWAY, app=b"TSBO"))


def save_state(stick, total, length):
    reply = stick.ask(PEER, SAVE, total.to_bytes(2, "little") + length.to_bytes(2, "little"))
    assert reply.ok and len(reply.payload) == 1
    return reply.payload[0]


def flow(host, guest, times=4):
    """The network, more than once: a save is more than one carry holds."""
    for _ in range(times):
        carry(host, guest)
        host.tick(0)
        guest.tick(0)


def put(stick, offset, data):
    reply = stick.ask(PEER, PUT, offset.to_bytes(2, "little") + data)
    assert reply.ok and len(reply.payload) == 2
    return int.from_bytes(reply.payload, "little")


def get(stick, offset):
    reply = stick.ask(PEER, GET, offset.to_bytes(2, "little"))
    assert reply.ok
    return reply.payload


def connected(pair):
    host, guest = pair
    for stick in pair:
        assert stick.hello(app=b"TSBO", reply_max=REPLY_MAX, services=[PEER]).ok
    connect(host, guest)
    return host, guest


def copy(host, guest, save, chunk=60):
    """The host puts its save, a request at a time as the console does,
    and the other gets it, as it comes."""
    put_at, got = 0, bytearray()
    for _ in range(10 * len(save) // chunk + 100):
        if put_at < len(save):
            put_at = put(host, put_at, save[put_at:put_at + chunk])
        flow(host, guest, 1)
        while len(got) < len(save):
            data = get(guest, len(got))
            if not data:
                break
            assert len(data) <= REPLY_MAX
            got += data
        if len(got) == len(save):
            return bytes(got)
    raise AssertionError("the save did not cross: %d of %d" % (len(got), len(save)))


def test_the_same_saves_cross_nothing_and_the_ticks_follow(pair):
    host, guest = connected(pair)
    assert save_state(host, 0x1234, 6763) == WAITING
    assert save_state(guest, 0x1234, 6763) == WAITING
    flow(host, guest)
    assert save_state(host, 0x1234, 6763) == SAME
    assert save_state(guest, 0x1234, 6763) == SAME
    # Tick 0 is the first byte past the sums.
    assert ticks(host, 0, 0, b"\x80")[0] == 1
    assert ticks(guest, 0, 0, b"\x01")[0] == 1
    flow(host, guest)
    assert ticks(host, 1, 0)[3] == b"\x01"
    assert ticks(guest, 1, 0)[3] == b"\x80"


def test_a_different_save_crosses_whole_and_then_the_ticks(pair):
    host, guest = connected(pair)
    save = bytes(random.Random(1).randrange(256) for _ in range(6763))
    assert save_state(host, 0x1111, len(save)) == WAITING
    flow(host, guest)
    # The host's sum is there already: the other knows at once.
    assert save_state(guest, 0x2222, len(save)) == DIFFERENT
    flow(host, guest)
    assert save_state(host, 0x1111, len(save)) == DIFFERENT
    assert copy(host, guest, save) == save
    # Nothing past the save is given.
    assert get(guest, len(save)) == b""
    assert save_state(host, 0x1111, len(save)) == DIFFERENT     # until the other has it
    reply = guest.ask(PEER, DONE)
    assert reply.ok and reply.payload[0] == COPIED
    flow(host, guest)
    assert save_state(host, 0x1111, len(save)) == COPIED
    assert ticks(host, 0, 0, b"\x80")[0] == 1
    assert ticks(guest, 0, 0, b"\x01")[0] == 1
    flow(host, guest)
    assert ticks(host, 1, 0)[3] == b"\x01"
    assert ticks(guest, 1, 0)[3] == b"\x80"


def test_a_put_again_is_passed_over_and_a_gap_is_not_taken(pair):
    host, guest = connected(pair)
    save_state(host, 1, 300)
    save_state(guest, 2, 300)
    flow(host, guest)
    assert save_state(host, 1, 300) == DIFFERENT
    assert put(host, 0, bytes(range(40))) == 40
    assert put(host, 0, bytes(range(50))) == 50         # the reply was lost: 10 more
    assert put(host, 60, bytes(10)) == 50               # not after what has gone
    flow(host, guest)
    assert get(guest, 0) == bytes(range(50))


def test_the_puts_wait_for_the_others_sum(pair):
    host, guest = connected(pair)
    save_state(host, 1, 300)
    assert put(host, 0, bytes(40)) == 0
    assert get(guest, 0) == b""


def test_a_save_the_other_says_no_to(pair):
    """Player 2 says no: its console hangs up, and the host is told."""
    host, guest = connected(pair)
    save_state(host, 1, 300)
    save_state(guest, 2, 300)
    flow(host, guest)
    assert save_state(host, 1, 300) == DIFFERENT
    host.conn = CONN_LOST
    host.tick(0)
    assert save_state(host, 1, 300) == GONE


def test_with_no_session_there_is_no_save(pair):
    host, _ = pair
    host.hello(app=b"TSBO", services=[PEER])
    assert save_state(host, 1, 300) == GONE


def test_a_save_too_long_is_refused(pair):
    host, guest = connected(pair)
    reply = host.ask(PEER, SAVE, bytes((1, 0)) + (p.NESP_PEER_SAVE_MAX + 1).to_bytes(2, "little"))
    assert reply.status == p.NESP_ST_BAD_ARG


def test_buttons_already_sent_begin_no_save(pair):
    """A game that never asks SAVE has its ticks from the stream's start;
    one that has sent buttons cannot begin a save."""
    host, guest = connected(pair)
    assert ticks(host, 0, 0, b"\x80")[0] == 1
    assert save_state(host, 1, 300) == GONE
