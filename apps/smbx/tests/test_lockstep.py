"""A session between two simulated consoles: the game is the same on both,
whatever the network and the nesp32s do to the timing. TMNT II's tests
(apps/tmnt2/tests/test_lockstep.py), on SMBX, with what this game has of
its own: a sound engine that keeps the ticks' time, and one split, under
the status bar, by the VRC6's IRQ."""

import collections
import random

import pytest

from drive import KEEP_LIVES, MODE_TITLE, PAD_A, PAD_B, PAD_RIGHT, moves, playing
from netplay import Table
from wire import ms

PLAY_FRAMES = 400
CHECK_AT = 0xF7                 # the tick whose NMI takes the digest (net/net_ram.inc)
STATUS_BAR_LINE = 31            # the split's: the last line of the status bar


def to_game(table):
    """A session starts at the title, which takes Start as pressed with two
    players chosen, and the level begins."""
    for _ in range(600):
        if all(playing(console) for console in table.consoles):
            break
        table.run(1)
    for console in table.consoles:
        assert playing(console)
        assert console.byte("TWO_PLAYERS") == 1
        assert console.byte("net_go") == 0


def play(table, frames=PLAY_FRAMES, seed=3):
    """Start a session and play. Returns the ticks both consoles took."""
    table.start()
    to_game(table)
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
    assert table.same_game() > 0.9 * table.frames()
    assert table.stalls() <= 2
    assert table.delays() == (1, 1)


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


def test_a_session_begins_with_both_players_in_the_game(net_console):
    """Mario and Luigi both have their lives when the level begins, on both
    consoles: the title gives player 2 none unless 2 PLAYERS GAME was
    chosen before its first frame, and Luigi was never seen (as on
    hardware, before net_reset chose it). Nothing tops the lives up here."""
    table = Table(net_console, immortal=False)
    table.start()
    to_game(table)
    for console in table.consoles:
        lives = console.labels["LIVES"]
        assert (console.ram[lives], console.ram[lives + 1]) == (KEEP_LIVES, KEEP_LIVES)


def test_each_player_is_their_own_console(net_console):
    """Player 1 is the console that hosted, and player 2 the other: what
    each pressed is given to its own player in both games."""
    table = Table(net_console)
    table.start()
    to_game(table)
    table.run(30, pads=(PAD_RIGHT, PAD_A))
    for console in table.consoles:
        pads = console.labels["net_pads"]
        assert (console.bus[pads], console.bus[pads + 1]) == (PAD_RIGHT, PAD_A)


@pytest.mark.parametrize("delay_ms, ticks", [(20, 2), (35, 3)])
def test_a_slower_network_begins_with_a_longer_delay(net_console, delay_ms, ticks):
    """The nesp32s know how long the network takes before the session
    starts, and say what delay covers it: no frame waits."""
    table = Table(net_console, delay=ms(delay_ms))
    assert play(table) > 0.9 * table.frames()
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
    before = table.stalls()
    table.play(300, moves(seed=4))
    assert table.stalls() - before <= 3
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


def test_the_sound_keeps_the_ticks_time(net_console):
    """On a network that slow most frames are stalls. The sound engine
    runs once a tick and in no stall, on both consoles, so what it keeps
    is the same on both at every tick: the game reads back from it
    whether a level's closing music has ended."""
    table = Table(net_console, delay=ms(250))
    table.start()
    to_game(table)
    before = []
    for side, console in enumerate(table.consoles):
        console.count_calls("net_tick_sound")
        before.append((len(console.frames), table.ticks(side)))
    table.play(300, moves(seed=3))
    for side, console in enumerate(table.consoles):
        frames_run = len(console.frames) - before[side][0]
        ticks = table.ticks(side) - before[side][1]
        assert ticks < 0.7 * frames_run
        assert abs(console.calls_of("net_tick_sound") - ticks) <= 1
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


@pytest.mark.parametrize("clock_error", [-0.015, 0.015])
def test_a_nesp32_whose_baud_rate_is_off(net_console, clock_error):
    table = Table(net_console, port_options=({"clock_error": clock_error}, {}))
    assert play(table, frames=200) > 0.85 * table.frames()


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
    assert console.byte("OPER_MODE") == MODE_TITLE


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
    its buttons. Here player 1 is moved on one console only: the digests
    differ at the next such tick, and both give the session up."""
    table = Table(net_console)
    assert play(table, frames=300) > 256        # past one check, the games alike
    for console in table.consoles:
        assert console.byte("net_mode") == 1
    console = table.consoles[0]
    console.ram[0x86] ^= 0x10                   # player 1's place across the screen
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


def test_a_reply_misheard_is_asked_for_again_in_the_same_frame(net_console):
    """One reply in ten is spoiled on the line. The console asks again at
    once, and next to no frame waits for it."""
    rng = random.Random(8)

    def spoil(data):
        if rng.random() < 0.1:
            data = bytearray(data)
            data[rng.randrange(len(data))] ^= 1 << rng.randrange(8)
        return bytes(data)

    table = Table(net_console, delay=ms(3),
                  port_options=({"to_console": spoil}, {"to_console": spoil}))
    assert play(table) > 0.9 * table.frames()
    assert table.stalls() <= 0.03 * table.frames()
    assert sum(stick.peer_repeats for stick in table.sticks) > 40


def test_the_split_stays_on_its_line_in_a_session(net_console):
    """The exchange is made with the IRQs held off, and is over before the
    split under the status bar: every IRQ is taken on the line it was
    raised on, on both consoles, ticks and stalls alike, and the tick that
    takes the digest (CHECK_AT, once in 256) among them."""
    table = Table(net_console, delay=ms(20), input_delay=1)
    table.start()
    to_game(table)
    marks = [len(console.frames) for console in table.consoles]
    buttons = moves(seed=3)
    seen = set()
    for _ in range(1000):
        if len(seen) >= 256 and CHECK_AT in seen:
            break
        seen.update(console.byte("net_tick") for console in table.consoles)
        table.play(1, buttons)
    assert CHECK_AT in seen
    assert table.stalls() > 0                   # stalls among them
    for console, mark in zip(table.consoles, marks):
        frames = console.frames[mark:]
        assert all(len(frame.irqs) == 1 for frame in frames)
        late = collections.Counter(console.scanline(taken) - console.scanline(raised)
                                   for frame in frames for raised, taken in frame.irqs)
        assert set(late) == {0}
        lines = {console.scanline(raised) for frame in frames for raised, _ in frame.irqs}
        assert lines == {STATUS_BAR_LINE}
