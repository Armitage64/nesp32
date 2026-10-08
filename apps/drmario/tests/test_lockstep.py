"""A session between two simulated consoles: the game is the same on both,
whatever the network and the nesp32s do to the timing."""

import random

import pytest

from console import PAD_A, PAD_B, PAD_LEFT, PAD_RIGHT, PAD_START
from drive import GAME_SCRIPT, PLAYERS, SCRIPT_LOGO, SCRIPT_OPTIONS, moves
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


@pytest.mark.parametrize("apart", [0.1, 0.5, 0.9])
def test_two_consoles_play_the_same_game(net_console, apart):
    """A press is used one tick after it was read, and on a network that
    takes 5 ms to cross no frame waits for one, wherever the one
    console's frames fall in the other's. The delay is the nesp32s' advice
    from the first, and stays."""
    table = Table(net_console, delay=ms(5))
    table.start(apart)
    to_game(table)
    table.play(PLAY_FRAMES, moves(seed=3))
    assert table.same_game() > 0.97 * table.frames()
    assert table.stalls() <= 2
    assert table.delays() == (1, 1)
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
        first = table.ticks(0)
        mine, theirs = moves(seed=3), moves(seed)
        for _ in range(200):
            table.run(1, pads=(next(mine)[0], next(theirs)[1]))
        assert table.same_game() > first + 150
        return table.traces[0][first + 150]
    assert final(4) != final(5)


def test_a_press_is_used_a_tick_after_it_is_read(net_console):
    """With the delay at 1, a button held on player 1's controller is the
    game's on both consoles within two frames, where a delay of 3 took
    four."""
    table = Table(net_console, delay=ms(5))
    table.start()
    to_game(table)
    assert table.delays() == (1, 1)
    hold = table.consoles[0].labels["ram_btn_hold"]
    table.run(2, pads=(PAD_LEFT, 0))
    for console in table.consoles:
        assert console.ram[hold] == PAD_LEFT


@pytest.mark.parametrize("delay_ms, ticks", [(20, 2), (35, 3)])
def test_a_slower_network_begins_with_a_longer_delay(net_console, delay_ms, ticks):
    """The nesp32s know how long the network takes before the session
    starts, and say what delay covers it: no frame waits."""
    table = Table(net_console, delay=ms(delay_ms))
    assert play(table) > 0.97 * table.frames()
    assert table.stalls() <= 2
    assert table.delays() == (ticks, ticks)


def test_a_delay_too_short_is_made_longer_as_the_game_goes(net_console):
    """Both consoles begin with a delay of 1 on a network that needs 2.
    Each nesp32 finds the network slower than that covers, and advises a
    tick more. The game is the same on both throughout, and stops
    waiting."""
    table = Table(net_console, delay=ms(20), input_delay=1)
    table.start()
    to_game(table)
    table.play(500, moves(seed=3))
    assert table.delays() == (2, 2)
    before = table.stalls(), table.frames()
    table.play(300, moves(seed=4))
    assert table.stalls() - before[0] <= 3
    assert table.same_game() > 400


def test_a_delay_longer_than_it_need_be_is_made_shorter(net_console):
    """Both begin with 2 where 1 will do. After a while of a network that
    1 covers each is advised a tick less, and no frame waits for it."""
    table = Table(net_console, delay=ms(3), input_delay=2)
    table.start()
    to_game(table)
    table.play(1300, moves(seed=3))
    assert table.delays() == (1, 1)
    before = table.stalls()
    table.play(200, moves(seed=4))
    assert table.stalls() - before <= 2
    assert table.same_game() > 1200


def test_the_two_consoles_need_not_keep_the_same_delay(net_console):
    """One is started with 1 and the other with 3. The game is the same
    on both, through the tick that carries the digests too; and the one
    that began too long is told so in its first report."""
    table = Table(net_console, delay=ms(3))
    table.start()
    for console, delay in zip(table.consoles, (1, 3)):
        console.mpu.x = delay
    table.run(4)
    assert table.delays() == (1, 3)
    to_game(table)
    table.play(350, moves(seed=3))
    assert table.delays() == (1, 1)
    assert table.same_game() > 300
    assert all(console.byte("net_mode") == 1 for console in table.consoles)


@pytest.mark.parametrize("delay_ms, drift", [(150, 0.0005), (250, -0.0005)])
def test_a_network_slower_than_any_delay_slows_the_game_and_does_not_change_it(
        net_console, delay_ms, drift):
    """The buttons take longer to cross than the longest delay allows, and
    one console's clock is fast. Both stall for what is missing."""
    table = Table(net_console, delay=ms(delay_ms), drift=drift)
    ticks = play(table)
    assert 100 < ticks < 0.9 * table.frames()
    assert table.delays() == (5, 5)


def test_the_music_keeps_time_when_the_game_does_not(net_console):
    """On a network that slow most frames are stalls. The sound engine
    still runs once in every frame, on both consoles, and the game is
    still the same on both."""
    table = Table(net_console, delay=ms(250))
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
    assert play(table, frames=200) > 0.97 * table.frames()


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


def test_two_games_that_differ_end_the_session(net_console):
    """One tick in 256 carries a digest of each console's game in place of
    its buttons. Here one console's count of frames is changed under it:
    the digests differ at the next such tick, and both give the session
    up."""
    table = Table(net_console)
    assert play(table, frames=300) > 256        # past one check, the games alike
    for console in table.consoles:
        assert console.byte("net_mode") == 1
    console = table.consoles[0]
    console.ram[console.labels["ram_frm_cnt"]] ^= 0x55
    # A digest is taken a few ticks before it is compared, so the next one
    # that sees this may be the one after next.
    table.play(560, moves(seed=4))
    for console in table.consoles:
        assert console.byte("net_mode") == 0


def test_a_check_tick_takes_the_buttons_of_the_tick_before(net_console):
    """The games stay alike through it, with both players' buttons held."""
    table = Table(net_console)
    table.start()
    to_game(table)
    first = table.ticks(0)
    held = (PAD_RIGHT | PAD_B, PAD_RIGHT | PAD_A)
    for _ in range(300):
        table.run(1, pads=held)
    assert table.same_game() > first + 256
    assert all(console.byte("net_mode") == 1 for console in table.consoles)


def test_a_network_with_spikes_does_not_drag_the_delay_up(net_console):
    """One packet in twelve takes 150 ms or more, which no delay covers.
    The delay stays where it covers the rest, and the game waits out the
    spikes."""
    rng = random.Random(21)
    table = Table(net_console, delay=lambda: ms(rng.choice((4,) * 11 + (150,))))
    table.start()
    to_game(table)
    table.play(700, moves(seed=3))
    assert max(table.delays()) <= 2
    assert table.same_game() > 300
