"""A session between two simulated consoles: the game is the same on both,
whatever the network and the nesp32s do to the timing."""

import random

import pytest

from console import PAD_START
from drive import BOOT_FRAMES, GAME_SCRIPT, PLAYERS, SCRIPT_LOGO, SCRIPT_OPTIONS, moves
from netplay import Table
from wire import ms

PLAY_FRAMES = 400
SOUND_ENGINE = "loc_D470"


def hold(table, pad, until, limit=600):
    """Hold a button on player 1's controller until the game shows it was
    taken. In a stall no controller is read, so how long that takes
    depends on the network."""
    console = table.consoles[0]
    for _ in range(limit):
        if until(console):
            break
        table.run(1, pads=(pad, 0))
    else:
        raise AssertionError("the game did not take the button")
    table.run(12)


def to_game(table):
    """A session starts at the options of a two-player game. Player 1
    starts the game from there."""
    table.run(60)
    for console in table.consoles:
        assert console.ram[PLAYERS] == 2
    hold(table, PAD_START, lambda console: console.ram[GAME_SCRIPT] != SCRIPT_OPTIONS)
    table.run(120)


def play(table, frames=PLAY_FRAMES, seed=3):
    """Start a session and play. Returns the ticks both consoles took."""
    table.start()
    to_game(table)
    for console in table.consoles:
        assert console.ram[PLAYERS] == 2
        assert console.ram[GAME_SCRIPT] not in (0, 1)
    table.play(frames, moves(seed))
    return table.same_game()


def frames(table):
    """Frames the first console has had since its session began."""
    return len(table.consoles[0].frames) - BOOT_FRAMES


def test_two_consoles_play_the_same_game(net_console):
    table = Table(net_console)
    ticks = play(table)
    # On a network this quick nearly every frame is a tick.
    assert ticks > 0.97 * frames(table)
    # And it is a game: the bottles are not the same as each other.
    ram = table.consoles[0].ram
    assert bytes(ram[0x400:0x480]) != bytes(ram[0x500:0x580])


def test_both_players_buttons_reach_both_games(net_console):
    """The same session with other buttons on player 2's console alone is
    another game, on both."""
    def final(seed):
        table = Table(net_console)
        table.start()
        to_game(table)
        mine, theirs = moves(seed=3), moves(seed)
        for _ in range(200):
            table.run(1, pads=(next(mine)[0], next(theirs)[1]))
        ticks = table.same_game()
        return table.traces[0][min(ticks, 300)]
    assert final(4) != final(5)


@pytest.mark.parametrize("delay_ms, drift", [(40, 0.0005), (90, -0.0005)])
def test_a_slow_network_slows_the_game_and_does_not_change_it(net_console, delay_ms, drift):
    """The buttons take longer to cross than INPUT_DELAY allows, and one
    console's clock is fast. Both stall for what is missing."""
    table = Table(net_console, delay=ms(delay_ms), drift=drift)
    ticks = play(table)
    assert 100 < ticks < 0.9 * frames(table)


def test_the_music_keeps_time_when_the_game_does_not(net_console):
    """On a slow network half the frames are stalls. The sound engine still
    runs once in every frame, on both consoles, and the game is still the
    same on both."""
    table = Table(net_console, delay=ms(90))
    table.start()
    to_game(table)
    before = []
    for side, console in enumerate(table.consoles):
        console.count_calls(SOUND_ENGINE)
        before.append((len(console.frames), table.ticks(side)))
    table.play(300, moves(seed=3))
    for side, console in enumerate(table.consoles):
        frames_run = len(console.frames) - before[side][0]
        assert table.ticks(side) - before[side][1] < 0.7 * frames_run
        assert abs(console.calls_of(SOUND_ENGINE) - frames_run) <= 1
    assert table.same_game() > 100


def test_a_network_that_comes_and_goes(net_console):
    rng = random.Random(7)
    table = Table(net_console, delay=lambda: ms(rng.choice((3, 8, 20, 60, 150))))
    assert play(table) > 100


def test_a_nesp32_that_is_sometimes_too_slow_to_answer(net_console):
    """The console waits about 4.1 ms for a reply. Later ones are missed,
    or fall across the next exchange, and are asked for again."""
    rng = random.Random(11)
    table = Table(net_console, turnaround=lambda: ms(rng.choice((0.5, 1, 2, 4, 7, 12, 19))))
    assert play(table) > 100
    assert any(stick.peer_repeats for stick in table.sticks)


def test_replies_lost_and_damaged_on_the_line(net_console):
    rng = random.Random(5)

    def spoil(data):
        roll = rng.random()
        if roll < 0.1:
            return None                 # lost
        if roll < 0.2:
            data = bytearray(data)      # a bit turned
            data[rng.randrange(len(data))] ^= 1 << rng.randrange(8)
        elif roll < 0.25:
            data = data[:rng.randrange(1, len(data))]   # cut short
        return bytes(data)

    table = Table(net_console, port_options=({"to_console": spoil}, {"to_console": spoil}))
    assert play(table) > 100


@pytest.mark.parametrize("clock_error", [-0.02, 0.02])
def test_a_nesp32_whose_baud_rate_is_off(net_console, clock_error):
    table = Table(net_console, port_options=({"clock_error": clock_error}, {}))
    assert play(table, frames=200) > 0.97 * frames(table)


def test_the_other_console_goes_away(net_console):
    """Its nesp32 says so, and this console starts again from the title,
    out of the session."""
    table = Table(net_console)
    play(table, frames=60)
    table.lan.cut()
    table.run(30)
    console = table.consoles[0]
    assert console.byte("net_mode") == 0
    table.run(120)
    assert console.ram[GAME_SCRIPT] == SCRIPT_LOGO


def test_the_nesp32_goes_quiet(net_console):
    """With no answer at all the console gives up after SILENT_FRAMES."""
    table = Table(net_console)
    play(table, frames=60)
    table.ports[0].deaf = True
    table.run(table.consoles[0].labels["SILENT_FRAMES"] - 30)
    assert table.consoles[0].byte("net_mode") == 1
    table.run(60)
    assert table.consoles[0].byte("net_mode") == 0
