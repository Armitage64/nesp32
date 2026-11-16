"""The rest of the game in a session: a preseason game played to its end and
the screens after it, the play-call screen's menu and its timeouts, the
preseason's other ways to play, the Pro Bowl, and TEAM DATA. Each from a session's start at the main
menu, with the two consoles' games compared tick by tick, their saves at the
end, and every bank the game picks one of its own."""

import random

import pytest

from drive import PAD_A, PAD_B, PAD_DOWN, PAD_LEFT, PAD_RIGHT, PAD_UP, screen_text
from netplay import Table
from test_lockstep import moves
from test_menu import MAIN_MENU_FIRST_Y, save_of
from wire import ms

GAME_BANKS = 30                 # the game's switchable banks; 30 and 31 are the netplay's
MMC3_DATA = 0x8001
FIXED_HOOKS = 0xFF80            # the netplay's hooks in the fixed bank (net/cart.inc)
# And its quicker routines' banks (net/flicker.inc, net/coll.inc), which
# their ways in and out, in bank 22's empty bytes, put in at $A000, and the
# game's own NMI puts back from the game's shadow if it comes meanwhile.
FAST_BANKS = (33, 34)
END_OF_GAME_STATS = 0x4E        # DRAW_SCOREBOARD_SCENE's scene: the blue screen after a game
GAME_FRAMES = 12000             # a game of short quarters is some 5500, with overtime 9800
SHORT_QUARTER = 0x10            # seconds, in BCD
TEAM_TAPS = 12                  # presses enough to pick the teams in any of the preseason's ways
TIMEOUT_TRIES = 20
MENU_ARROWS = ((0x200,), (0x204,))  # each player's menu arrow's sprite Y
CANCEL_Y = 0x38                 # the arrow beside the play-call menu's CANCEL
MENU_FRAMES = 60
CLOCK_STOPPED, CLOCK_RUNNING = 0x00, 0x80


def tap(table, side, pad, rest):
    pads = [0, 0]
    pads[side] = pad
    table.run(3, tuple(pads))
    table.run(rest)


def game_banks(table):
    """Every bank the game picks for $8000 or $A000 on either console. The
    netplay's own picks (its hooks in the fixed bank, its code in its
    banks, and its quicker routines' banks) are left out."""
    picked = set()
    for console in table.consoles:
        write = console.write_mapper

        def write_mapper(address, value, console=console, write=write):
            if address & 0xE001 == MMC3_DATA and console.bank_select & 7 in (6, 7):
                # py65 has taken the opcode, not yet the operand.
                at = console.mpu.pc - 1
                ours = at >= FIXED_HOOKS or value in FAST_BANKS or (
                    at < 0xC000 and GAME_BANKS <= console.bus.bank_at(at) < GAME_BANKS + 2)
                if not ours:
                    picked.add(value)
            write(address, value)
        console.write_mapper = write_mapper
    return picked


def short_quarters(console):
    """Each quarter's clock is 0:10 once it starts, and player 1 has a
    touchdown, so that the game ends at the fourth quarter's whistle (a
    tie goes on to overtime). Both consoles alike, at a tick."""
    minutes = console.labels["CLOCK_MINUTES"]
    if 0 < console.ram[minutes] < 0x80:
        console.ram[minutes] = 0
        console.ram[console.labels["CLOCK_SECONDS"]] = SHORT_QUARTER
    if console.ram[console.labels["P1_TOTAL_SCORE"]] == 0:
        console.ram[console.labels["P1_QTR_SCORES"]] = 7
        console.ram[console.labels["P1_TOTAL_SCORE"]] = 7


def scenes(table):
    """The scoreboard's scenes each console draws (DRAW_SCOREBOARD_SCENE)."""
    drawn = ([], [])
    for side, console in enumerate(table.consoles):
        console.watch("DRAW_SCOREBOARD_SCENE",
                      lambda console, side=side: drawn[side].append(console.mpu.a))
    return drawn


def in_session(table):
    for console in table.consoles:
        assert console.byte("net_mode") == 0x80


def test_a_preseason_game_to_its_end(net_console):
    """MAN VS MAN, from the kickoff to the fourth quarter's whistle, the
    game's statistics, and A back to the main menu."""
    table = Table(net_console, delay=ms(5))
    table.start()
    picked = game_banks(table)      # from here: start() puts the netplay's bank in itself
    table.to_game()
    table.every_tick(short_quarters)
    drawn = scenes(table)
    play = moves(3)
    while not all(END_OF_GAME_STATS in side for side in drawn):
        assert table.frames() < GAME_FRAMES
        table.play(50, play)
    table.run(300)
    for console in table.consoles:
        assert "TEAM STATISTICS" in screen_text(console)
        assert console.byte("P1_TOTAL_SCORE") > console.byte("P2_TOTAL_SCORE")
    tap(table, 0, PAD_A, 100)
    for console in table.consoles:
        assert console.byte("MENU_ARROW_SPR_Y") == MAIN_MENU_FIRST_Y
    in_session(table)
    assert table.same_game() > 4000
    assert save_of(table.consoles[0]) == save_of(table.consoles[1])
    assert picked and max(picked) < GAME_BANKS


def menu_at_cancel(console, side):
    """The play-call menu up, its arrow beside CANCEL."""
    return any(console.ram[arrow] == CANCEL_Y for arrow in MENU_ARROWS[side])


def call_timeout(table, side, name, play):
    """Play until a timeout is taken: on the play-call screen, A alone is
    a menu of CANCEL and TIMEOUT (and the offense's kicks), whose TIMEOUT
    is taken only while the clock runs. The menu may be up already, opened
    by the play at random, where A would cancel it."""
    console = table.consoles[side]
    # Plays at random seldom end with the clock running (in bounds, after
    # a run): it runs between plays here, the same on both consoles.
    table.every_tick(clock_runs)
    try:
        for _ in range(TIMEOUT_TRIES):
            table.play(150, play)
            table.run(30)
            left = console.byte(name)       # the play at random may take one too
            if not left:
                continue                    # before the coin toss gives each three
            if not menu_at_cancel(console, side):
                tap(table, side, PAD_A, 0)
                for _ in range(MENU_FRAMES):
                    if menu_at_cancel(console, side):
                        break
                    table.run(1)
                else:
                    continue
            table.run(10)
            tap(table, side, PAD_DOWN, 20)
            tap(table, side, PAD_A, 200)
            if console.byte(name) < left:
                return
    finally:
        table.every_tick(None)
    raise AssertionError("player %d took no timeout: %s is %d" % (side + 1, name, console.byte(name)))


def clock_runs(console):
    """The clock running, as after a tackle in bounds (CLOCK_RUN_TYPE)."""
    run = console.labels["CLOCK_RUN_TYPE"]
    if console.ram[run] == CLOCK_STOPPED:
        console.ram[run] = CLOCK_RUNNING


def test_timeouts(net_console):
    """Each player's timeout from the play-call screen's menu, and the menu
    cancelled otherwise, by either player."""
    table = Table(net_console, delay=ms(20))
    table.start()
    table.to_game()
    play = moves(4)
    for side, name in ((0, "P1_TIMEOUTS"), (1, "P2_TIMEOUTS")):
        call_timeout(table, side, name, play)
    table.play(300, play)
    in_session(table)
    assert table.same_game() > 1500


@pytest.mark.parametrize("choice", [0, 2, 3, 4, 5])
def test_preseason_ways_to_play(net_console, choice):
    """MAN VS COM, MAN VS COA, COA VS COM, COA VS COA and COM VS COM, each
    from the preseason's menu (MAN VS MAN is to_game's): its teams picked,
    then a while of play with both players' buttons at random."""
    table = Table(net_console, delay=ms(10))
    table.start()
    table.run(90)
    tap(table, 0, PAD_A, 100)               # PRESEASON
    for _ in range(choice):
        tap(table, 0, PAD_DOWN, 20)
    tap(table, 0, PAD_A, 150)
    # The teams, by player 1 or by both, then the screen of the two and the
    # kickoff, whose clock is the quarter's.
    host = table.consoles[0]
    for press in range(TEAM_TAPS):
        if host.byte("CLOCK_MINUTES") == 5:
            break
        tap(table, press % 2, PAD_A, 120)
    assert host.byte("CLOCK_MINUTES") == 5
    table.play(600, moves(choice))
    in_session(table)
    assert table.same_game() > 1000


def main_menu_choice(table, downs):
    """From a session's start: the main menu's PRESEASON, SEASON GAME, PRO
    BOWL or TEAM DATA."""
    table.run(90)
    for _ in range(downs):
        tap(table, 0, PAD_DOWN, 20)
    tap(table, 0, PAD_A, 150)


PRESEASON, SEASON_GAME, PRO_BOWL, TEAM_DATA = 0, 1, 2, 3


def test_the_pro_bowl(net_console):
    """PRO BOWL: player 1's conference, the coin toss, and a while of play."""
    table = Table(net_console, delay=ms(10))
    table.start()
    main_menu_choice(table, PRO_BOWL)
    host = table.consoles[0]
    for press in range(TEAM_TAPS):
        if host.byte("CLOCK_MINUTES") == 5:
            break
        tap(table, press % 2, PAD_A, 120)
    assert host.byte("CLOCK_MINUTES") == 5
    table.play(600, moves(12))
    in_session(table)
    assert table.same_game() > 1000


def menu_moves(seed):
    """Presses for a menu at random: a direction or A, now and then."""
    rng = random.Random(seed)
    while True:
        pad = rng.choice([PAD_A, PAD_UP, PAD_DOWN, PAD_LEFT, PAD_RIGHT, 0, 0, 0])
        for _ in range(3):
            yield (pad, 0)
        for _ in range(rng.randint(10, 40)):
            yield (0, 0)


def test_team_data_changes(net_console):
    """TEAM DATA, the AFC's all stars, PLAY BOOKS: plays changed at random,
    which the game writes to the save, alike on both."""
    table = Table(net_console, delay=ms(10))
    table.start()
    before = save_of(table.consoles[0])
    main_menu_choice(table, TEAM_DATA)
    tap(table, 0, PAD_A, 150)               # AFC ALL STARS
    for pad in (PAD_RIGHT, PAD_DOWN, PAD_DOWN, PAD_A):
        tap(table, 0, pad, 40)              # PLAY BOOKS
    table.play(1500, menu_moves(13))
    for _ in range(4):
        tap(table, 0, PAD_B, 100)
    in_session(table)
    assert table.same_game() > 1500
    after = save_of(table.consoles[0])
    assert after != before
    assert after == save_of(table.consoles[1])
