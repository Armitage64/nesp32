"""The original game on the simulated console: that it runs to a game for
two, what its IRQs do, and that it is not the same game on two consoles."""

from itertools import islice

from console import FRAME_CYCLES
from drive import STATE_LEVELS, moves, play, title_script

PLAY_TICKS = 600
# Level 1's splits: the status bar's foot, and three below the playfield.
LEVEL_1_SPLITS = (47, 188, 199, 202)


def game(seed, ticks=PLAY_TICKS):
    return title_script() + list(islice(moves(seed), ticks))


def first_difference(one, other):
    return next((tick for tick, pair in enumerate(zip(one, other)) if pair[0] != pair[1]), None)


def test_reaches_a_two_player_game(console):
    nes = console()
    play(nes, game(1, 300))
    assert nes.byte("STATE_SWITCH_INITIAL_MENUS") == STATE_LEVELS
    assert nes.byte("TWO_PLAYERS_FLAG") == 1
    assert nes.byte("LEVEL_SCREEN_ON") == 0


def test_level_one_splits_the_screen_four_times_on_time(console):
    """The counter is set up in the NMI and the IRQs come where the game
    means them, each taken on the line it was raised on."""
    nes = console()
    play(nes, game(1, 300))
    frames = nes.frames[-200:]
    splits = [tuple(nes.scanline(raised) for raised, _ in frame.irqs) for frame in frames]
    # Some frames, as the level comes in, have none.
    assert set(splits) == {LEVEL_1_SPLITS, ()}
    assert splits.count(LEVEL_1_SPLITS) > 150
    late = [nes.scanline(taken) - nes.scanline(raised)
            for frame in frames for raised, taken in frame.irqs]
    assert max(late) == 0


def test_original_is_not_the_same_on_two_consoles(console):
    """The original stirs its random number in the idle loop, so a few
    cycles' difference in a frame makes another game. Here one console's
    frames are a little short."""
    one = play(console(stir_idle=True), game(1))
    other = play(console(stir_idle=True, frame_cycles=FRAME_CYCLES - 2), game(1))
    assert first_difference(one, other) is not None
