"""The netplay ROM's menu, in its own bank: what it shows, what it tells the
Stick, and that HOST GAME on one console and JOIN GAME on the other end in
one game on both."""

from console import PAD_A, PAD_B, PAD_DOWN, PAD_LEFT, PAD_RIGHT, PAD_START, PAD_UP
from drive import (
    GAME_SCRIPT,
    PLAYERS,
    SCRIPT_LOGO,
    SCRIPT_OPTIONS,
    moves,
    screen_row,
    screen_text,
    to_title,
)
from drnet.linkrate import STATE_HOSTING, STATE_IDLE
from netplay import Table
from test_lockstep import to_game

MENU_BANK = 2                   # the MMC1's PRG register with the menu in place
OWN_ROW, HOST_ROW, DIGITS_ROW, MARK_ROW, STATUS_ROW = 20, 14, 12, 13, 16
STATUS_POLL = 16                # frames between the menu's questions


def tap(table, side, pad, rest=6):
    pads = [0, 0]
    pads[side] = pad
    table.run(3, pads=tuple(pads))
    table.run(rest)


def open_menu(table, side):
    tap(table, side, PAD_DOWN)
    tap(table, side, PAD_START, rest=3 * STATUS_POLL)
    console = table.consoles[side]
    assert console.mapper[3] == MENU_BANK
    assert "NETWORK GAME" in screen_text(console)


def test_local_game_with_no_stick(net_console):
    """Nothing on port 2 answers. The menu says so, and LOCAL GAME goes on
    to the game's options for two players."""
    nes = net_console()
    to_title(nes)
    nes.run(3, pads=(PAD_DOWN, 0))
    nes.run(6, pads=(0, 0))
    nes.run(3, pads=(PAD_START, 0))
    nes.run(10 * STATUS_POLL, pads=(0, 0))
    assert nes.mapper[3] == MENU_BANK
    assert screen_row(nes, 9).strip() == "> HOST GAME"
    assert screen_row(nes, OWN_ROW).strip() == "NO STICK"
    # HOST GAME does nothing without a Stick.
    nes.run(3, pads=(PAD_A, 0))
    nes.run(10, pads=(0, 0))
    assert "WAITING" not in screen_text(nes)
    for _ in range(2):
        nes.run(3, pads=(PAD_DOWN, 0))
        nes.run(6, pads=(0, 0))
    assert screen_row(nes, 13).strip() == "> LOCAL GAME"
    assert screen_row(nes, 9).strip() == "HOST GAME"
    nes.run(3, pads=(PAD_A, 0))
    nes.run(60, pads=(0, 0))
    assert nes.mapper[3] == 0
    assert nes.ram[GAME_SCRIPT] == SCRIPT_OPTIONS
    assert nes.ram[PLAYERS] == 2
    assert nes.byte("net_mode") == 0


def test_the_menu_shows_the_sticks_address(net_console):
    table = Table(net_console)
    table.boot()
    open_menu(table, 0)
    assert screen_row(table.consoles[0], OWN_ROW).strip() == "192.168.001.023"


def test_a_stick_with_no_wifi(net_console):
    table = Table(net_console, addresses=(None, None))
    table.boot()
    open_menu(table, 0)
    assert screen_row(table.consoles[0], OWN_ROW).strip() == "NO WIFI"
    tap(table, 0, PAD_A)
    assert "WAITING" not in screen_text(table.consoles[0])


def test_host_and_back(net_console):
    table = Table(net_console)
    table.boot()
    open_menu(table, 0)
    tap(table, 0, PAD_A, rest=2 * STATUS_POLL)
    console = table.consoles[0]
    assert "WAITING FOR PLAYER 2" in screen_text(console)
    assert screen_row(console, HOST_ROW).strip() == "192.168.001.023"
    assert table.nets[0].state == STATE_HOSTING
    tap(table, 0, PAD_B, rest=2 * STATUS_POLL)
    assert "HOST GAME" in screen_text(console)
    assert table.nets[0].state == STATE_IDLE


def edit_last_octet_to_23(table, side):
    """The address starts as this Stick's own, 192.168.001.042."""
    console = table.consoles[side]
    assert screen_row(console, DIGITS_ROW).strip() == "192.168.001.042"
    for _ in range(10):
        tap(table, side, PAD_RIGHT)
    assert screen_row(console, MARK_ROW).index("-") == screen_row(console, DIGITS_ROW).index("42")
    tap(table, side, PAD_DOWN)
    tap(table, side, PAD_DOWN)
    tap(table, side, PAD_RIGHT)
    tap(table, side, PAD_UP)
    assert screen_row(console, DIGITS_ROW).strip() == "192.168.001.023"


def open_join(table, side):
    open_menu(table, side)
    tap(table, side, PAD_DOWN)
    tap(table, side, PAD_A, rest=3 * STATUS_POLL)
    assert "JOIN THE GAME AT" in screen_text(table.consoles[side])


def test_join_with_nobody_hosting(net_console):
    table = Table(net_console)
    table.boot()
    open_join(table, 1)
    edit_last_octet_to_23(table, 1)
    tap(table, 1, PAD_START, rest=2)
    console = table.consoles[1]
    assert screen_row(console, STATUS_ROW).strip() == "CONNECTING"
    table.run(4 * STATUS_POLL)
    assert screen_row(console, STATUS_ROW).strip() == "COULD NOT JOIN"
    # And the address can be edited again.
    tap(table, 1, PAD_LEFT)
    assert screen_row(console, MARK_ROW).index("-") == screen_row(console, DIGITS_ROW).index("23")


def test_host_and_join_start_one_game(net_console):
    table = Table(net_console)
    table.boot()
    open_menu(table, 0)
    tap(table, 0, PAD_A, rest=2 * STATUS_POLL)
    open_join(table, 1)
    edit_last_octet_to_23(table, 1)
    tap(table, 1, PAD_START, rest=6 * STATUS_POLL)
    for side, console in enumerate(table.consoles):
        assert console.mapper[3] == 0
        assert console.byte("net_mode") == 1
        assert console.byte("net_role") == side
    to_game(table)
    table.play(200, moves(seed=3))
    assert table.same_game() > 200
    # The second Stick remembers where it joined, for next time.
    assert table.nets[1].last == bytes((192, 168, 1, 23))


def test_the_title_comes_back_after_a_session_is_lost(net_console):
    table = Table(net_console)
    table.start()
    table.run(60)
    table.nets[1].close()
    table.run(200)
    console = table.consoles[0]
    assert console.byte("net_mode") == 0
    assert console.ram[GAME_SCRIPT] == SCRIPT_LOGO
    assert console.mapper[3] == 0
