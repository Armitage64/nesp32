"""Two consoles in a session play the same game, tick by tick: from the
session's start through the menus to a preseason game for two, MAN VS MAN,
and a while of play with both players' buttons at random."""

import random

import pytest

from netplay import Table
from wire import ms


def moves(seed):
    rng = random.Random(seed)
    while True:
        pads = [0, 0]
        for player in range(2):
            if rng.random() < 0.6:
                pads[player] |= rng.choice([1, 2, 4, 8, 9, 10, 5, 6])
            if rng.random() < 0.35:
                pads[player] |= rng.choice([0x80, 0x40])
        for _ in range(rng.randint(2, 10)):
            yield tuple(pads)


@pytest.mark.parametrize("seed,delay", [(1, 5), (2, 20)])
def test_same_game(net_console, seed, delay):
    table = Table(net_console, delay=ms(delay))
    table.start()
    table.to_game()
    table.play(1500, moves(seed))
    ticks = table.same_game()
    assert ticks > 1400          # some 2000 frames from the main menu on
    # Both in the game, and still in the session.
    for console in table.consoles:
        assert console.byte("net_mode") == 0x80
