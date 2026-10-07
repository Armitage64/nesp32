"""A computer's stand-in for a nesp32's connection to another
(host/peer_net.py), on real sockets on this machine, with the firmware's
own PEER at both ends."""

import time

import nesp_proto as p
import pytest
from nesp import Stick
from peer_net import IdleNetwork, SocketNetwork
from test_peer import HOME, HOST, JOIN, LEAVE, PLAYER_1, PLAYER_2, lobby, online, ticks

TCP_PORT = 46502
LOCALHOST = bytes((127, 0, 0, 1))


def until(condition, *ends, seconds=5.0):
    """Poll the networks, and give the nesp32s their clock, until something
    is so."""
    started = time.monotonic()
    while True:
        now = time.monotonic() - started
        for stick, network in ends:
            network.poll()
            stick.tick(int(now * 1000))
        if condition():
            return
        assert now < seconds, "it did not happen"
        time.sleep(0.002)


@pytest.fixture
def pair(tmp_path):
    ends = []
    for name in ("a", "b"):
        stick = online(Stick(), HOME)
        ends.append((stick, SocketNetwork(stick, port=TCP_PORT, last_path=str(tmp_path / name))))
    yield ends
    for _, network in ends:
        network.close()


def test_host_and_join_on_this_machine(pair, tmp_path):
    (host, _), (guest, _) = pair
    lobby(host, HOST)
    lobby(guest, JOIN, LOCALHOST)
    until(lambda: (lobby(host)[0], lobby(guest)[0]) == (PLAYER_1, PLAYER_2), *pair)
    # Buttons cross, a byte a tick.
    assert ticks(host, 0, 0, b"\x80\x40")[0] == 2
    assert ticks(guest, 0, 0, b"\x01")[0] == 1
    until(lambda: ticks(host, 2, 0)[3] == b"\x01" and ticks(guest, 1, 0)[3] == b"\x80\x40",
          *pair)
    # The one that joined keeps the address, over power-off.
    assert guest.last == LOCALHOST
    again = Stick()
    SocketNetwork(again, port=TCP_PORT, last_path=str(tmp_path / "b"))
    assert again.last == LOCALHOST
    # One side leaves, and the other finds out.
    lobby(guest, LEAVE)
    until(lambda: ticks(host, 2, 1)[2] == 1, *pair)
    assert lobby(host)[0] == p.NESP_LOBBY_FAILED


def test_join_with_nobody_hosting(pair):
    guest = pair[1]
    lobby(guest[0], JOIN, LOCALHOST)
    until(lambda: lobby(guest[0])[0] == p.NESP_LOBBY_FAILED, guest)
    assert guest[0].last is None


def test_the_idle_opponent_keeps_up_and_presses_nothing():
    stick = online(Stick(), HOME)
    end = (stick, IdleNetwork(stick))
    lobby(stick, HOST)
    until(lambda: lobby(stick)[0] == PLAYER_1, end)
    for tick in range(20):
        # This console's tick is taken; the opponent's for it comes back,
        # with no buttons.
        assert ticks(stick, tick, tick, b"\x80")[0] == tick + 1
        until(lambda: True, end)
        assert ticks(stick, tick + 1, tick)[1:] == (tick, 0, b"\x00")
    # And joining does as well as hosting.
    lobby(stick, JOIN, LOCALHOST)
    until(lambda: lobby(stick)[0] == PLAYER_2, end)
