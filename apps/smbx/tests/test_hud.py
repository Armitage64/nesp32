"""The HUD build's readout of a session's lag (`make hud`): what it shows,
and that the game under it is the same game."""

from drive import moves, screen_row
from netplay import Table
from test_lockstep import to_game
from wire import ms

HUD_ROW = 1


def readout(console):
    """D, S and L from the readout: the delay, and the stalls and the lag
    frames, in hexadecimal."""
    fields = screen_row(console, HUD_ROW).split()
    assert [field[0] for field in fields] == ["D", "S", "L"]
    return tuple(int(field[1:], 16) for field in fields)


def test_the_readout_counts_what_the_session_does(hud_console):
    """On a network slower than the delay covers, the consoles stall: the
    readout says the delay each keeps, and as many stalls as the session
    counted, on both consoles, and the game is the same on both."""
    table = Table(hud_console, delay=ms(150))
    table.start()
    to_game(table)
    table.play(300, moves(seed=3))
    assert table.same_game() > 100
    for console in table.consoles:
        delay, stalls, lags = readout(console)
        assert delay == console.byte("net_delay")
        assert stalls > 20
        assert stalls == console.calls_of("net_stall")


def test_with_no_stalls_the_readout_says_so(hud_console):
    """On a fast network 1-1 neither stalls nor overruns once it is under
    way, and the status bar under the readout is as the game draws it,
    whatever way the game's drawing left the PPU stepping. (Its first frames do: the screen of lives and the level's drawing
    run long in the hack too, a few frames.)"""
    table = Table(hud_console, delay=ms(5))
    table.start()
    to_game(table)
    table.run(60)
    before = [readout(console) for console in table.consoles]
    for _ in range(300):
        table.play(1, moves(seed=3))
        for console in table.consoles:     # drawn across, and on its own line
            assert screen_row(console, 2)[1:3] == "M-" and screen_row(console, 3)[1:3] == "L-"
    for console, (_, stalls_before, lags_before) in zip(table.consoles, before):
        delay, stalls, lags = readout(console)
        assert delay == 1
        assert stalls - stalls_before <= 2
        assert lags == lags_before
