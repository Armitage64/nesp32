"""A computer's stand-in for a nesp32's connection to another
(host/peer_net.py), on real sockets on this machine, with the firmware's
own PEER at both ends."""

import socket
import struct
import threading
import time

import nesp_proto as p
import pytest
from nesp import Stick
from peer_net import IdleNetwork, SocketNetwork
from rendezvous import FakeRendezvous
from test_meet import HOST_ROOM, JOIN_ROOM, room
from test_peer import AWAY, HOME, HOST, JOIN, LEAVE, PLAYER_1, PLAYER_2, lobby, online, ticks

TCP_PORT = 46502
MEET_PORTS = (46510, 46511)     # one machine, so the two meeting sockets need a port each
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


@pytest.fixture
def rendezvous():
    with FakeRendezvous() as server:
        yield server


@pytest.fixture
def met_pair(tmp_path, rendezvous):
    ends = []
    for name, address, port in (("a", HOME, MEET_PORTS[0]), ("b", AWAY, MEET_PORTS[1])):
        stick = online(Stick(), address)
        stick.set_rendezvous(rendezvous.url)
        ends.append((stick, SocketNetwork(stick, port=port, last_path=str(tmp_path / name),
                                          stun=())))
    yield ends
    for _, network in ends:
        network.close()


def test_two_meet_by_a_rooms_code(met_pair, rendezvous):
    (host, _), (guest, _) = met_pair
    room(host, HOST_ROOM)
    until(lambda: room(host)[0] == p.NESP_LOBBY_HOSTING, *met_pair)
    code = room(host)[1]
    room(guest, JOIN_ROOM, code)
    until(lambda: (lobby(host)[0], lobby(guest)[0]) == (PLAYER_1, PLAYER_2), *met_pair,
          seconds=p.NESP_PEER_POLL_MS / 1000 + 3)
    assert ticks(host, 0, 0, b"\x80")[0] == 1
    assert ticks(guest, 0, 0, b"\x01")[0] == 1
    until(lambda: ticks(host, 1, 0)[3] == b"\x01" and ticks(guest, 1, 0)[3] == b"\x80",
          *met_pair)
    # Each was asked for what it is, and told the other.
    asked = " ".join(rendezvous.requests)
    assert "/v1/host?app=TEST&ver=1" in asked and f"/v1/join/{code.decode()}" in asked


def test_a_host_that_never_answers_is_said_to_be_unreachable(met_pair, rendezvous):
    guest = met_pair[1]
    guest[1].meet_call_s = 0.5
    status, line = rendezvous.answer("/v1/host?app=TEST&ver=1&c=127.0.0.1:9")
    code = line.split()[1].encode()
    room(guest[0], JOIN_ROOM, code)
    until(lambda: room(guest[0])[0] == p.NESP_LOBBY_FAILED, guest)
    assert room(guest[0])[2] == p.NESP_MEET_UNREACHABLE


def test_no_rendezvous_is_said(met_pair):
    guest = met_pair[1]
    guest[0].set_rendezvous("http://127.0.0.1:9")
    room(guest[0], JOIN_ROOM, b"K7QF")
    until(lambda: room(guest[0])[0] == p.NESP_LOBBY_FAILED, guest)
    assert room(guest[0])[2] == p.NESP_MEET_NO_SERVER


def test_the_idle_opponent_meets_in_a_room_too():
    stick = online(Stick(), HOME)
    end = (stick, IdleNetwork(stick))
    room(stick, HOST_ROOM)
    until(lambda: lobby(stick)[0] == PLAYER_1, end)
    room(stick, JOIN_ROOM, b"K7QF")
    until(lambda: lobby(stick)[0] == PLAYER_2, end)


def test_a_computers_meeting_says_what_stun_saw(tmp_path, rendezvous):
    # A STUN server on this machine that sees every socket as 203.0.113.5,
    # port 40000.
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    server.settimeout(5)

    def answer():
        request, source = server.recvfrom(64)
        mixed = bytes(a ^ b for a, b in zip(bytes((203, 0, 113, 5)), bytes.fromhex("2112a442")))
        value = struct.pack(">BBH", 0, 1, 40000 ^ 0x2112) + mixed
        body = struct.pack(">HH", 0x0020, len(value)) + value
        server.sendto(struct.pack(">HH", 0x0101, len(body)) + request[4:20] + body, source)

    threading.Thread(target=answer, daemon=True).start()
    stick = online(Stick(), HOME)
    stick.set_rendezvous(rendezvous.url)
    network = SocketNetwork(stick, port=MEET_PORTS[0], last_path=str(tmp_path / "a"),
                            stun=[("127.0.0.1", server.getsockname()[1])])
    try:
        room(stick, HOST_ROOM)
        until(lambda: room(stick)[0] == p.NESP_LOBBY_HOSTING, (stick, network))
        assert "203.0.113.5:40000" in rendezvous.requests[0]
    finally:
        network.close()
        server.close()
