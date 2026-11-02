"""Two consoles on the lobby sample, each with a nesp32, and a network
between the nesp32s: they meet in the lobby, by a room's code or by an
address, and then each shows both players' buttons, the same on both."""

import console
import nesp_proto as p
import pytest
from console import PAD_A, PAD_DOWN, PAD_LEFT, PAD_RIGHT, PAD_SELECT, PAD_START, PAD_UP
from nesp import CONN_ANSWERED, CONN_CALLED, CONN_CALLING, CONN_LISTENING, CONN_LOST
from nesp import CONN_MEETING, CONN_MET, CONN_UP, Stick
from rendezvous import Rooms
from wire import link

ADDRESSES = (bytes((192, 168, 1, 23)), bytes((192, 168, 1, 42)))
LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
MODE_SESSION = 1
OWN_ROW, CODE_ROW, ENDED_ROW = 20, 14, 15


class Console(console.Console):
    """nesp32's simulated console (tests/console.py), with the nesp32 polled
    while the NMI runs too: this ROM makes every exchange there."""

    def _vblank(self):
        mpu = self.mpu
        self.frame.pad = self.pad
        self.frames.append(self.frame)
        self.frame = console.Frame(self.next_vblank)
        self.next_vblank += console.FRAME_CYCLES
        self.vblank_unread = True
        if not self.ctrl & console.PPUCTRL_NMI:
            return
        started = mpu.processorCycles
        self.in_nmi = True
        mpu.nmi()
        while True:
            if self.host is not None and mpu.processorCycles >= self._host_at:
                self._host_at = mpu.processorCycles + self.host_every
                self.host()
            if self._skip():
                continue
            returning = self.memory[mpu.pc] == console.RTI
            mpu.step()
            if returning:
                break
        self.in_nmi = False
        self.frame.nmi_cycles = mpu.processorCycles - started


class Network:
    """What the nesp32s ask of the network, answered at once: a call is
    answered if the other is listening, a room's rendezvous is
    host/rendezvous.py's, and what one nesp32 sends reaches the other."""

    def __init__(self, sticks):
        self.sticks = sticks
        self.rooms = Rooms()
        self.meets = [stick.meets for stick in sticks]
        self.fetches = [stick.fetches for stick in sticks]
        self.punches = [stick.punches for stick in sticks]
        self.punched = [None, None]     # what each was told at the rendezvous
        self.up = False

    def poll(self):
        for side, stick in enumerate(self.sticks):
            if stick.meets != self.meets[side]:     # its socket's address is found
                self.meets[side] = stick.meets
                self.punched[side] = None
                if stick.conn == CONN_MEETING:
                    stick.candidates = [(ADDRESSES[side], p.NESP_PEER_PORT)]
                    stick.conn = CONN_MET
            if stick.fetches != self.fetches[side]:   # it asks the rendezvous
                self.fetches[side] = stick.fetches
                if stick.fetching:
                    _, line = self.rooms.answer("/v1/" + stick.fetch_url.split("/v1/", 1)[1])
                    stick.fetch_body(line.encode() + b"\n")
                    stick.fetch_done()
            if stick.punches != self.punches[side]:   # it was told of the other
                self.punches[side] = stick.punches
                self.punched[side] = stick.punch
        for side, caller in enumerate(self.sticks):
            host = self.sticks[1 - side]
            if caller.conn != CONN_CALLING or host.conn != CONN_LISTENING:
                continue
            ours, theirs = self.punched[side], self.punched[1 - side]
            if (ours and theirs and ours[1] == theirs[1]) or caller.conn_target == ADDRESSES[1 - side]:
                caller.conn, host.conn = CONN_CALLED, CONN_ANSWERED
                self.up = True
        if not self.up:
            return
        if any(stick.conn not in CONN_UP for stick in self.sticks):
            for stick in self.sticks:       # one hung up: the other hears it
                if stick.conn in CONN_UP:
                    stick.conn = CONN_LOST
            self.up = False
            return
        one, other = self.sticks
        other.conn_give(one.conn_take())
        one.conn_give(other.conn_take())


class Table:
    """Two consoles side by side, run a frame at a time."""

    def __init__(self, rom):
        self.consoles = []
        sticks = []
        for address in ADDRESSES:
            each = Console(*rom)
            stick, _ = link(each, Stick)
            stick.set_wifi(p.NESP_WIFI_JOINED, rssi=-50, address=address)
            self.consoles.append(each)
            sticks.append(stick)
        self.network = Network(sticks)
        self.run(10)

    def run(self, frames, pads=(0, 0)):
        for _ in range(frames):
            for each, pad in zip(self.consoles, pads):
                each.run(1, pad=pad)
            self.network.poll()

    def tap(self, side, buttons, times=1):
        pads = [0, 0]
        pads[side] = buttons
        for _ in range(times):
            self.run(2, pads)
            self.run(2)

    def until(self, condition, frames=600):
        for _ in range(frames):
            if condition():
                return
            self.run(1)
        raise AssertionError("still waiting:\n%s\n\n%s" % tuple(c.screen() for c in self.consoles))

    def in_session(self):
        return all(each.byte("mode") == MODE_SESSION for each in self.consoles)


def lit(each):
    """The buttons lit on a console's screen: (player 1's, player 2's)."""
    masks = each.data("pad_mask", each.labels["pad_x"] - each.labels["pad_mask"])
    players = [0, 0]
    for index in range(2 * len(masks)):
        if each.sprite(index) is not None:
            players[index // len(masks)] |= masks[index % len(masks)]
    return tuple(players)


@pytest.fixture
def table(rom):
    table = Table(rom)
    table.until(lambda: all(each.line(OWN_ROW).startswith("192") for each in table.consoles))
    return table


def test_the_lobby_says_where_this_nesp32_is(table):
    assert [each.line(OWN_ROW) for each in table.consoles] == [
        "192.168.001.023", "192.168.001.042"]
    assert table.consoles[0].line(9) == "> HOST GAME"
    assert table.consoles[0].line(ENDED_ROW) == ""


def test_by_a_rooms_code_both_show_both_players_buttons(table):
    host, guest = table.consoles
    table.tap(0, PAD_START)                         # HOST GAME
    table.until(lambda: host.line(CODE_ROW).strip() not in ("", "    "))
    code = host.text(CODE_ROW, 14, 4)
    assert all(letter in LETTERS for letter in code)
    table.tap(1, PAD_DOWN)                          # JOIN GAME
    table.tap(1, PAD_START)
    for place, letter in enumerate(code):
        table.tap(1, PAD_UP, LETTERS.index(letter))
        table.tap(1, PAD_RIGHT)
    assert guest.text(12, 14, 4) == code
    table.tap(1, PAD_START)
    table.until(table.in_session)
    assert "YOU" in host.line(5) and "YOU" in guest.line(17)

    table.run(30, pads=(PAD_A | PAD_UP, PAD_LEFT | PAD_SELECT))
    assert lit(host) == lit(guest) == (PAD_A | PAD_UP, PAD_LEFT | PAD_SELECT)
    table.run(30)
    assert lit(host) == lit(guest) == (0, 0)
    # In lockstep: both have taken as many ticks, give or take the one that
    # is under way.
    host_ticks, guest_ticks = ticks(host), ticks(guest)
    assert abs(host_ticks - guest_ticks) <= 1 and host_ticks > 40


def test_by_an_address_after_select(table):
    host, guest = table.consoles
    table.tap(0, PAD_START)
    table.tap(0, PAD_SELECT)                        # host by address
    table.until(lambda: host.line(14) == "192.168.001.023")
    table.tap(1, PAD_DOWN)
    table.tap(1, PAD_START)
    table.tap(1, PAD_SELECT)                        # join by address
    # Nothing joined before: the edit starts from this nesp32's own address.
    table.until(lambda: guest.line(12) == "192.168.001.042")
    table.tap(1, PAD_RIGHT, 10)
    table.tap(1, PAD_DOWN, 2)
    table.tap(1, PAD_RIGHT)
    table.tap(1, PAD_UP)
    assert guest.line(12) == "192.168.001.023"
    table.tap(1, PAD_START)
    table.until(table.in_session)
    table.run(30, pads=(PAD_RIGHT, PAD_A))
    assert lit(host) == lit(guest) == (PAD_RIGHT, PAD_A)


def ticks(each):
    low, high = each.data("game_ticks", 2)
    return low | high << 8


def test_a_long_session_carries_the_digest_and_the_delay_report(table):
    test_by_an_address_after_select(table)
    before = [ticks(each) for each in table.consoles]
    for frame in range(600):        # past tick 255's digest, and four reports
        table.run(1, pads=(frame & 0xFF, ~frame & 0xFF))
    assert table.in_session()
    assert all(ticks(each) - start > 550 for each, start in zip(table.consoles, before))
    table.run(10)
    assert lit(table.consoles[0]) == lit(table.consoles[1]) == (0, 0)


def test_games_that_come_apart_are_caught_by_the_digest(table):
    test_by_an_address_after_select(table)
    guest = table.consoles[1]
    guest.memory[guest.labels["game_ticks"] + 1] ^= 0x80    # a bug on one console
    table.until(lambda: not table.in_session(), frames=300)
    for each in table.consoles:
        table.until(lambda: each.line(ENDED_ROW) == "GAMES DIFFERED")


def test_when_the_other_console_is_reset_the_lobby_says_so(table):
    test_by_an_address_after_select(table)
    host, guest = table.consoles
    guest.reset()
    table.until(lambda: host.byte("mode") != MODE_SESSION)
    table.until(lambda: host.line(ENDED_ROW) == "THE OTHER LEFT")
    assert lit(host) == (0, 0)
