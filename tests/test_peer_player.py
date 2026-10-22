"""host/peer_player.py, the second player with no second console: against
a console of the test's in a session of PEER's, the test as the network
between the two nesp32s (test_peer.py)."""

import random

import pytest
from nesp import CONN_LOST, Stick
from peer_player import CHECK_TICK, COPY_LAG, LEAD, Player
from test_peer import AWAY, HOME, carry, connect, online, ticks

APP = b"TMN2"
DELAY = 3                       # the console's own
TICKS = 700


class Console:
    """A console in a session: its buttons sent DELAY ticks ahead of the
    tick it is at, a tick taken whenever it has the other's buttons for it,
    and a digest in place of its buttons at CHECK_TICK."""

    def __init__(self, seed=1):
        rng = random.Random(seed)
        self.mine = bytes(0xA5 ^ (tick >> 8) if tick % 256 == CHECK_TICK
                          else rng.randrange(256) for tick in range(TICKS + 16))
        self.theirs = bytearray()
        self.acked = 0

    def exchange(self, stick):
        tick = len(self.theirs)
        after, start, lost, data = ticks(stick, self.acked, tick,
                                         self.mine[self.acked:min(self.acked + 2, tick + DELAY)])
        assert not lost and start == tick & 0xFF
        self.acked += (after - self.acked) & 0xFF
        self.theirs += data


def session(play):
    console_stick, player_stick = online(Stick(), HOME, APP), online(Stick(), AWAY, APP)
    connect(console_stick, player_stick)
    console, player = Console(), Player(play, seed=2)
    while len(console.theirs) < TICKS:
        console.exchange(console_stick)
        player.exchange(player_stick)
        carry(console_stick, player_stick)
    return console, player


@pytest.mark.parametrize("play", ["copy", "still", "random"])
def test_the_digest_is_sent_back_and_the_session_goes_on(play):
    console, player = session(play)
    for check in range(CHECK_TICK, TICKS, 256):
        assert console.theirs[check] == console.mine[check]
    # Paced by the console's: never more than LEAD ahead of what it has.
    assert len(player.mine) <= len(player.theirs) + LEAD


def test_copy_is_the_consoles_buttons_half_a_second_later_without_start_or_select():
    console, _ = session("copy")
    for tick in range(COPY_LAG, TICKS):
        if tick % 256 == CHECK_TICK:
            continue
        back = tick - COPY_LAG
        if back % 256 == CHECK_TICK:
            back -= 1
        assert console.theirs[tick] == console.mine[back] & 0xCF


def test_still_taps_a_and_nothing_else():
    console, _ = session("still")
    pressed = {tick for tick in range(TICKS) if tick % 256 != CHECK_TICK and console.theirs[tick]}
    assert {console.theirs[tick] for tick in pressed} == {0x80}
    assert len(pressed) == 4 * len(range(0, TICKS, 120))


def test_the_player_stops_when_the_console_goes():
    console_stick, player_stick = online(Stick(), HOME, APP), online(Stick(), AWAY, APP)
    connect(console_stick, player_stick)
    player = Player("still")
    assert player.exchange(player_stick)
    player_stick.conn = CONN_LOST
    player_stick.tick(0)
    assert not player.exchange(player_stick)
