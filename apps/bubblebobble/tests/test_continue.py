"""A session lasts past a game over: the game over's screen and the title
are ticks like any other, and the title's 2P CONTINUE goes on at the round
the two had reached, on both consoles. In a session the title's choices
for one are passed over."""

from drive import PAD_SELECT, PAD_START, TITLE_2P_CONTINUE, TITLE_2P_START, moves, screen_text
from netplay import Table
from test_lockstep import to_game
from wire import ms

PRESS = 3                       # frames a button is held, longer than a delay
REST = 30


def press(table, buttons, rest=REST):
    table.run(PRESS, pads=(buttons, 0))
    table.run(rest)


def to_game_over(table, ticks=12000):
    """Both players down to their last life, and play until it is lost. The
    lives are changed at a tick, which both consoles come to: not at a
    moment, which finds them at different ticks."""
    table.immortal = False
    table.lives_at[max(table.ticks(0), table.ticks(1)) + 10] = 1
    play = moves(seed=9)
    for _ in range(ticks // 8):
        table.play(8, play)
        if all("GAME OVER" in screen_text(console) for console in table.consoles):
            return
    raise AssertionError("no game over")


def cursors(table):
    return [console.byte("TITLE_CURSOR") for console in table.consoles]


def test_a_session_goes_on_past_a_game_over_into_a_continue(net_console):
    table = Table(net_console, delay=ms(10))
    table.start()
    to_game(table)
    table.play(300, moves(seed=3))
    to_game_over(table)
    reached = [console.byte("ROUND") for console in table.consoles]
    assert reached[0] == reached[1] >= 1
    for console in table.consoles:
        assert console.byte("net_mode") == 1
    # Start on player 1's console, the host's, as the game takes it: the
    # title's choices, with the cursor on 2P START.
    table.run(120)
    press(table, PAD_START, rest=200)
    for console in table.consoles:
        assert "2P CONTINUE" in screen_text(console)
    assert cursors(table) == [TITLE_2P_START] * 2
    # Select passes over 1P CONTINUE.
    press(table, PAD_SELECT)
    assert cursors(table) == [TITLE_2P_CONTINUE] * 2
    # Start shows the round, and Start again plays it.
    press(table, PAD_START)
    press(table, PAD_START, rest=500)
    for console in table.consoles:
        assert console.byte("net_mode") == 1
        assert console.byte("ROUND") == reached[0]
        assert console.byte("P1_LIVES") and console.byte("P2_LIVES")
    table.play(300, moves(seed=4))
    assert table.same_game() > 2000


def test_in_a_session_select_goes_round_the_choices_for_two(net_console):
    """From 2P START: 2P CONTINUE, PASSWORD, and 2P START again, never the
    choices for one; the marker beside each, three lines apart."""
    table = Table(net_console, delay=ms(10))
    table.start()
    to_game(table)
    to_game_over(table)
    table.run(120)
    press(table, PAD_START, rest=200)
    seen = []
    for _ in range(4):
        console = table.consoles[1]
        seen.append((console.byte("TITLE_CURSOR"), console.oam[0]))
        press(table, PAD_SELECT)
    assert [cursor for cursor, _ in seen] == [1, 3, 4, 1]
    top = seen[0][1] - 0x18
    assert [y for _, y in seen] == [top + 0x18, top + 0x48, top + 0x60, top + 0x18]
    assert table.same_game() > 1000
