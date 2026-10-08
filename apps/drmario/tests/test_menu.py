"""The netplay ROM's menu, in its own bank: what it shows, what it tells the
nesp32, and that HOST GAME on one console and JOIN GAME on the other end in
one game on both."""

import nesp
import nesp_proto as p
import pytest

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
from netplay import APP, Table
from test_lockstep import to_game
from wire import ms

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


def test_local_game_with_no_nesp32(net_console):
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
    assert screen_row(nes, OWN_ROW).strip() == "NO NESP32"
    # HOST GAME does nothing without a nesp32.
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


def test_the_menu_says_hello_and_shows_the_nesp32s_address(net_console):
    table = Table(net_console)
    table.boot()
    assert table.sticks[0].hellos == 0      # the game itself says nothing
    open_menu(table, 0)
    console, stick = table.consoles[0], table.sticks[0]
    assert screen_row(console, 18).strip() == "THIS NESP32 IS AT"
    assert screen_row(console, OWN_ROW).strip() == "192.168.001.023"
    assert stick.app == (APP, 2) and stick.active(p.NESP_SVC_PEER)
    assert stick.hellos == 1
    # It goes on asking, and nothing is asked twice or missed.
    table.run(4 * STATUS_POLL)
    assert stick.hellos == 1 and stick.repeats == 0
    assert console.byte("menu_misses") == 0


def test_a_nesp32_whose_firmware_has_no_peer(net_console):
    """An older firmware answers the hello: it lacks the service asked for.
    The menu says what to do about it, and offers the local game only."""
    def old(data):
        reply = nesp.parse(data)
        if reply.svc != p.NESP_SVC_SYS:
            return data
        return nesp.reply_frame(reply.svc, p.NESP_ST_NO_SERVICE, reply.seq,
                                reply.payload[:6] + bytes((1, p.NESP_SVC_PEER)))
    table = Table(net_console, port_options=({"to_console": old}, {}))
    table.boot()
    open_menu(table, 0)
    console = table.consoles[0]
    assert screen_row(console, OWN_ROW).strip() == "UPDATE NESP32"
    tap(table, 0, PAD_A)
    assert "WAITING" not in screen_text(console)


def test_local_game_leaves_the_games_memory_alone(net_console):
    """The menu and the link keep theirs where the game keeps none: with a
    nesp32 answering throughout, both players' options are as they were."""
    table = Table(net_console)
    table.boot()
    console = table.consoles[0]
    players = bytes(console.ram[0x300:0x330]), bytes(console.ram[0x380:0x3B0])
    open_menu(table, 0)
    table.run(4 * STATUS_POLL)
    for _ in range(2):
        tap(table, 0, PAD_DOWN)
    tap(table, 0, PAD_A, rest=30)
    assert console.mapper[3] == 0
    assert console.ram[PLAYERS] == 2
    assert (bytes(console.ram[0x300:0x330]), bytes(console.ram[0x380:0x3B0])) == players


def test_both_banks_keep_the_sessions_memory_in_the_same_place(banks):
    """The game's bank has the way into a session's frame and out of it,
    and the menu's has the frame, with the link's library."""
    game, menu = banks
    shared = [name for name in game if name.startswith("net_") and name in menu
              and game[name] < 0x800]
    assert {"net_tick", "net_delay", "net_stalled", "net_back", "net_vector"} <= set(shared)
    assert all(game[name] == menu[name] for name in shared)
    assert not any(name.startswith("nesp_") for name in game)
    assert menu["session_frame"] and menu["nesp_short"]
    # And the code that runs while the bank changes under it.
    assert game["net_far"] == menu["net_far"]


def test_a_nesp32_with_no_wifi(net_console):
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
    assert table.sticks[0].lobby == p.NESP_LOBBY_HOSTING
    assert table.sticks[0].shown(1) == "at 192.168.1.23"
    tap(table, 0, PAD_B, rest=2 * STATUS_POLL)
    assert "HOST GAME" in screen_text(console)
    assert table.sticks[0].lobby == p.NESP_LOBBY_IDLE


def test_a_nesp32_switched_off_and_on_while_it_hosts(net_console):
    """It knows of no hello, and says so. The menu says hello again and has
    it wait again."""
    table = Table(net_console)
    table.boot()
    open_menu(table, 0)
    tap(table, 0, PAD_A, rest=2 * STATUS_POLL)
    stick = table.restart(0)
    table.run(3 * STATUS_POLL)
    assert stick.hellos == 1 and stick.lobby == p.NESP_LOBBY_HOSTING
    assert "WAITING FOR PLAYER 2" in screen_text(table.consoles[0])


def edit_last_octet_to_23(table, side):
    """The address starts as this nesp32's own, 192.168.001.042."""
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


@pytest.mark.parametrize("delay_ms, ticks", [(5, 1), (20, 2)])
def test_host_and_join_start_one_game(net_console, delay_ms, ticks):
    """And each console begins with the delay its nesp32 advised, from how
    long the network took while the two connected."""
    table = Table(net_console, delay=ms(delay_ms))
    table.boot()
    open_menu(table, 0)
    tap(table, 0, PAD_A, rest=2 * STATUS_POLL)
    open_join(table, 1)
    edit_last_octet_to_23(table, 1)
    tap(table, 1, PAD_START, rest=6 * STATUS_POLL)
    for side, console in enumerate(table.consoles):
        assert console.mapper[3] == 0 or console.in_nmi    # a session's frame is in the menu's bank
        assert console.byte("net_mode") == 1
        assert console.byte("net_role") == side
    assert table.delays() == (ticks, ticks)
    to_game(table)
    table.play(200, moves(seed=3))
    assert table.same_game() > 200
    # The second nesp32 keeps where it joined, for next time.
    assert table.sticks[1].last == bytes((192, 168, 1, 23))


def test_the_address_last_joined_is_offered_next_time(net_console):
    table = Table(net_console)
    table.sticks[1].last = bytes((10, 0, 200, 7))
    table.boot()
    open_join(table, 1)
    assert screen_row(table.consoles[1], DIGITS_ROW).strip() == "010.000.200.007"


def test_the_title_comes_back_after_a_session_is_lost(net_console):
    table = Table(net_console)
    table.start()
    table.run(60)
    table.lan.cut()
    table.run(200)
    console = table.consoles[0]
    assert console.byte("net_mode") == 0
    assert console.ram[GAME_SCRIPT] == SCRIPT_LOGO
    assert console.mapper[3] == 0
