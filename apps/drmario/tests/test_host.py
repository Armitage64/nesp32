"""The computer's stand-ins for a Stick's network (host/desktop.py), on
real sockets on this machine."""

import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "host"))

from desktop import DesktopNetwork, IdleNetwork  # noqa: E402
from drnet.linkrate import (  # noqa: E402
    INPUT_DELAY,
    REQUEST_GAME,
    STATE_FAILED,
    STATE_GUEST,
    STATE_HOST,
    STATE_HOSTING,
    STATE_IDLE,
)
from drnet.session import Session, frame  # noqa: E402

TCP_PORT = 46502
LOCALHOST = bytes((127, 0, 0, 1))


def until(condition, *networks, seconds=5.0):
    """Poll the networks until something is so. Each has a thread of its
    own, as each has a machine of its own: connecting blocks until the
    other end has answered."""
    done = threading.Event()

    def keep_polling(network):
        while not done.is_set():
            network.poll()
            time.sleep(0.005)
    threads = [threading.Thread(target=keep_polling, args=(network,)) for network in networks]
    for thread in threads:
        thread.start()
    try:
        deadline = time.monotonic() + seconds
        while not condition():
            assert time.monotonic() < deadline, "it did not happen"
            time.sleep(0.005)
    finally:
        done.set()
        for thread in threads:
            thread.join()


@pytest.fixture
def pair(tmp_path):
    networks = [DesktopNetwork(port=TCP_PORT, last_path=str(tmp_path / name))
                for name in ("a", "b")]
    if networks[0].address is None:
        pytest.skip("this machine has no network")
    yield networks
    for network in networks:
        network.close()


def test_host_and_join_on_this_machine(pair, tmp_path):
    host, guest = pair
    host.listen()
    assert host.state == STATE_HOSTING
    guest.connect(LOCALHOST)
    until(lambda: guest.state == STATE_GUEST and host.state == STATE_HOST, host, guest)
    guest.peer.send(b"\x01\x02")
    host.peer.send(b"\x80")
    received = [b"", b""]

    def both_arrived():
        received[0] += host.peer.recv()
        received[1] += guest.peer.recv()
        return received == [b"\x01\x02", b"\x80"]
    until(both_arrived)
    assert guest.last == LOCALHOST
    assert DesktopNetwork(port=TCP_PORT, last_path=str(tmp_path / "b")).last == LOCALHOST
    # One side leaves, and the other finds out.
    guest.close()
    assert guest.state == STATE_IDLE
    until(lambda: host.peer.recv() == b"" and host.peer.lost)
    host.poll()
    assert host.state == STATE_FAILED


def test_join_with_nobody_hosting(pair):
    guest = pair[1]
    guest.connect(LOCALHOST)
    until(lambda: guest.state == STATE_FAILED, guest)
    assert guest.peer is None


def test_the_idle_opponent_keeps_up_and_presses_nothing():
    network = IdleNetwork()
    network.listen()
    assert network.state == STATE_HOST
    session = Session(network.peer)
    for tick in range(INPUT_DELAY, INPUT_DELAY + 20):
        session.pump()
        reply = session.game(frame((REQUEST_GAME, tick, 1, 0x80, 0, tick)))
        # This console's tick is taken; the opponent's for it comes in the
        # next reply, with no buttons.
        assert reply[1] == tick + 1
        session.pump()
        reply = session.game(frame((REQUEST_GAME, tick + 1, 0, 0, 0, tick)))
        assert (reply[2], reply[3], reply[4]) == (tick, 1, 0)
