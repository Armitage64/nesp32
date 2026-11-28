"""A session between two simulated consoles: the game is the same on both,
whatever the network and the nesp32s do to the timing. Bubble Bobble's
tests (apps/bubblebobble/tests/test_lockstep.py), on Rescue Rangers."""

import random

import pytest

from drive import PAD_A, PAD_B, PAD_RIGHT, PAD_START, moves, screen_row, screen_text
from netplay import NOT_GAME, Table
from wire import ms



def _net_rate():
    """NET_RATE, the Makefile's: the session's line the netplay ROM asks for."""
    import os
    import re
    with open(os.path.join(os.path.dirname(__file__), "..", "Makefile")) as handle:
        return int(re.search(r"^NET_RATE \?= (\d+)", handle.read(), re.M).group(1))


RATE = _net_rate()
PLAY_FRAMES = 400
SOUND_ENGINE = "NMI_SOUND"
STORY = "ASSIGNMENT"            # a word of the story's screen, before the first level
TITLE_ROW = 17                  # 1 PLAYER  2 PLAYERS


def to_game(table):
    """A session starts from the reset and goes past the title by itself,
    into a game for two: the story's screen, which waits for Start, here
    on player 1's console, held until the story has gone on both (on a
    network that stalls, a press of a few frames may be a tick or two),
    and the first level. A press held on is no new press: no pause."""
    for _ in range(600):
        if all(STORY in screen_text(console) for console in table.consoles):
            break
        table.run(1)
    for console in table.consoles:
        assert STORY in screen_text(console)
        assert console.byte("TITLE_PLAYERS") == 1
        assert console.byte("net_autostart") == 0
    for _ in range(3000):
        table.run(1, (PAD_START, 0))
        if not any(STORY in screen_text(console) for console in table.consoles):
            break
    table.run(200)
    for console in table.consoles:
        assert STORY not in screen_text(console)


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
    table.run(8)                # past the reset's two waits for a vblank
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


def test_the_internet_loses_doubles_and_reorders_datagrams(net_console):
    """The connection as the firmware has it: each nesp32's arq.c, and
    datagrams that cross on their own, some lost, some twice, some the wrong
    way round, and now and then none at all for 300 ms. The same game on
    both, and the session goes on. (Longer runs of this, past round 2 and
    with the delay moving from 2 to 5, found nothing either.)"""
    rng = random.Random(5)

    def delay():
        return ms(rng.uniform(45, 95) if rng.random() < 0.1 else rng.uniform(33, 38))

    def outage(at_ms):
        return at_ms > 4000 and at_ms % 4000 < 300

    table = Table(net_console, delay=delay,
                  network=dict(datagrams=True, loss=0.05, duplicate=0.02, outage=outage))
    assert play(table, frames=600) > 400
    for console in table.consoles:
        assert console.byte("net_mode") == 1
    assert table.lan.lost > 100 and table.lan.doubled > 10
    assert table.stalls() > 10


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
    """With the samples taking their cycles besides: a reply that one
    spoils is asked for again."""
    table = Table(net_console, port_options=({"clock_error": clock_error}, {}))
    assert play(table, frames=200) > 0.85 * table.frames()


def test_the_other_console_goes_away(net_console):
    """Its nesp32 says so, and this console starts again from the reset,
    out of the session, to the title."""
    table = Table(net_console)
    play(table, frames=60)
    table.lan.cut()
    table.run(30)
    console = table.consoles[0]
    assert console.byte("net_mode") == 0
    table.run(300)
    assert screen_row(console, TITLE_ROW).split() == ["1", "PLAYER", "2", "PLAYERS"]


def test_the_nesp32_goes_quiet(net_console):
    """With no answer at all the console gives up after SILENT_FRAMES."""
    table = Table(net_console)
    play(table, frames=60)
    table.ports[0].deaf = True
    table.run(table.consoles[0].labels["SILENT_FRAMES"] - 30)
    assert table.consoles[0].byte("net_mode") == 1
    table.run(60)
    assert table.consoles[0].byte("net_mode") == 0


def test_what_a_console_did_before_a_session_is_not_in_it(net_console):
    """The reset clears most of the game's RAM, not all: the sprites' tiles,
    colours and places stay, and the stack, and a few bytes of the zero
    page. Each console's own leftovers, from its last game or its power-on,
    are no part of the session's: the games are alike past several checks."""
    table = Table(net_console)
    table.start()
    for seed, console in enumerate(table.consoles):
        rng = random.Random(seed)
        for address in range(0x800):
            console.ram[address] = rng.randrange(256)
    to_game(table)
    table.play(800, moves(seed=3))
    assert table.same_game() > 0.9 * table.frames()
    assert all(console.byte("net_mode") == 1 for console in table.consoles)


def test_two_games_that_differ_end_the_session(net_console):
    """One tick in 256 carries a digest of each console's game in place of
    its buttons. Here one console's random number is changed under it: the
    digests differ at the next such tick, and both give the session up."""
    table = Table(net_console)
    assert play(table, frames=300) > 256        # past one check, the games alike
    for console in table.consoles:
        assert console.byte("net_mode") == 1
    console = table.consoles[0]
    console.ram[console.labels["RANDOM"]] ^= 0x55
    # A digest is taken a few ticks before it is compared, so the next one
    # that sees this may be the one after next.
    table.play(560, moves(seed=4))
    for console in table.consoles:
        assert console.byte("net_mode") == 0


def test_games_that_differ_send_their_ram_to_the_nesp32s_log(net_console):
    """Each console's RAM, as it stood at the tick whose digests differed,
    goes to its nesp32 before the session is given up (PEER's DUMP). The
    two dumps differ where the games do: here from the random number on."""
    table = Table(net_console)
    table.rams = ({}, {})
    assert play(table, frames=300) > 256
    # Nothing is sent while the games are alike, nor as a session starts.
    assert [stick.peer_dump for stick in table.sticks] == [bytes(0x800)] * 2
    console = table.consoles[0]
    rng = console.labels["RANDOM"]
    console.ram[rng] ^= 0x55
    table.play(560, moves(seed=4))
    dumps = [stick.peer_dump for stick in table.sticks]
    differ = [address for address in range(0x800)
              if dumps[0][address] != dumps[1][address] and not_game(address)]
    assert rng in differ or rng + 1 in differ
    # Each is its console's RAM at the start of that tick, the last that
    # both consoles came to: but for PPUCTRL_COPY, whose NMI bit the NMI
    # has cleared by then.
    tick = min(max(rams) for rams in table.rams)
    ppuctrl = console.labels["PPUCTRL_COPY"]
    for side, dump in enumerate(dumps):
        ram = table.rams[side][tick]
        assert [hex(address) for address in range(0x800) if dump[address] != ram[address]
                and not_game(address) and address != ppuctrl] == []


def not_game(address):
    """Not one of the bytes that keep each console's own time (NOT_GAME)."""
    return all(not start <= address < end for start, end in NOT_GAME)


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


def test_a_session_goes_straight_into_its_game(net_console):
    """From the reset past the title, as if Start had been pressed on 2
    PLAYERS, into the story's screen of a game for two, on both consoles
    alike."""
    table = Table(net_console)
    table.start()
    for frame in range(600):
        table.run(1)
        if all(STORY in screen_text(console) for console in table.consoles):
            break
    assert frame < 300
    for console in table.consoles:
        assert console.byte("TITLE_PLAYERS") == 1
    assert table.same_game() > 0


# --- a session's line at its own rate (PEER's RATE), as TMNT II's -------------------


def rates(table):
    return [[period for _, period in port.rates] for port in table.ports]


def test_a_session_runs_its_line_at_the_rate_it_asks_for(net_console):
    """In its first NMI each console asks its nesp32 for the session's own
    rate, at the link's; from then on both ends of each line are at it."""
    table = Table(net_console, delay=ms(5))
    table.start()
    to_game(table)
    table.play(200, moves(seed=3))
    assert rates(table) == [[RATE], [RATE]]
    assert all(console.byte("nesp_fast") == 0x80 for console in table.consoles)
    assert table.same_game() > 0.8 * table.frames()


def no_rate(data):
    """A nesp32 whose firmware has no RATE: it answers that it has no such op."""
    import nesp
    import nesp_proto as p
    try:
        reply = nesp.parse(data)
    except ValueError:
        return data                 # a short reply: a session's exchange
    if reply.svc == p.NESP_SVC_PEER and len(reply.payload) == 1:
        return nesp.reply_frame(reply.svc, p.NESP_ST_NO_OP, reply.seq, b"")
    return data


def test_with_a_nesp32_that_has_no_rate_the_line_stays_the_links(net_console):
    table = Table(net_console, delay=ms(5),
                  port_options=({"to_console": no_rate}, {"to_console": no_rate}))
    table.start()
    to_game(table)
    table.play(200, moves(seed=3))
    assert all(console.byte("nesp_fast") == 0 for console in table.consoles)
    assert table.same_game() > 0.8 * table.frames()


def test_a_line_no_good_at_its_rate_goes_back_to_the_links(net_console):
    """Every reply at the session's rate is lost. Each console goes back to
    the link's rate when it has heard none for a while, and its nesp32
    when it has heard nothing it could make out; the console asks again,
    and after a few times stays at the link's. The session goes on."""
    ports = []

    def lost_when_fast(side):
        def spoil(data):
            return None if len(ports) > side and ports[side].period == RATE else data
        return spoil

    table = Table(net_console, delay=ms(5),
                  port_options=({"to_console": lost_when_fast(0)},
                                {"to_console": lost_when_fast(1)}))
    ports += table.ports
    table.start()
    table.play(900, moves(seed=3))
    for console in table.consoles:
        assert console.byte("net_mode") == 1
        assert console.byte("nesp_fast") == 0
        assert console.byte("net_rate_tries") == console.labels["NET_RATE_TRIES"]
    assert rates(table)[0][-1] == 21 and rates(table)[1][-1] == 21
    assert table.same_game() > 300


def test_a_line_that_goes_bad_for_a_while_comes_back_to_its_rate(net_console):
    """The first 80 replies at the session's rate are lost (40 exchanges,
    each asked twice), and then none are. The console goes back to the
    link's rate, waits for its nesp32 to have gone back too, asks again,
    and is at the session's rate again."""
    lost = [0, 0]

    def spoiler(side):
        def spoil(data):
            if table.ports[side].period == RATE and lost[side] < 80:
                lost[side] += 1
                return None
            return data
        return spoil

    table = Table(net_console, delay=ms(5),
                  port_options=({"to_console": spoiler(0)}, {"to_console": spoiler(1)}))
    table.start()
    table.play(400, moves(seed=3))
    for console in table.consoles:
        assert console.byte("net_mode") == 1
        assert console.byte("nesp_fast") == 0x80
        assert console.byte("net_rate_tries") == 2
    assert rates(table) == [[RATE, 21, RATE], [RATE, 21, RATE]]
    assert table.same_game() > 250
