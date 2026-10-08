"""The netplay ROM's menu: what it shows, what it tells the nesp32, and that
HOST GAME on one console and JOIN GAME on the other end in one game on
both."""

import nesp
import nesp_proto as p

from console import PAD_A, PAD_B, PAD_DOWN, PAD_LEFT, PAD_RIGHT, PAD_SELECT, PAD_START, PAD_UP
from drive import LEVEL_PLAYING, ROUTINE_LEVEL, moves, screen_row, screen_text
from netplay import APP, Table
from test_lockstep import to_game

OWN_ROW, HOST_ROW, DIGITS_ROW, MARK_ROW, STATUS_ROW = 20, 14, 12, 13, 16
STATUS_POLL = 16                # frames between the menu's questions
MARKS = 0x1FE0                  # the two tiles the menu draws its marks in


def tap(table, side, pad, rest=6):
    pads = [0, 0]
    pads[side] = pad
    table.run(3, pads=tuple(pads))
    table.run(rest)


def open_menu(table, side):
    """Start ends the title's scroll, Select moves to 2 PLAYERS, and Start
    there is the menu."""
    tap(table, side, PAD_START, rest=20)
    tap(table, side, PAD_SELECT)
    console = table.consoles[side]
    assert console.byte("PLAYER_MODE") == 1
    tap(table, side, PAD_START, rest=3 * STATUS_POLL)
    assert console.byte("net_menu") == 2
    assert "NETWORK GAME" in screen_text(console)


def test_one_player_goes_straight_to_the_game(net_console):
    table = Table(net_console)
    table.boot()
    tap(table, 0, PAD_START, rest=20)
    tap(table, 0, PAD_START, rest=20)
    console = table.consoles[0]
    assert console.byte("net_menu") == 0
    assert console.byte("GAME_ROUTINE_INDEX") >= 3
    assert table.sticks[0].hellos == 0      # and the game itself says nothing


def test_local_game_with_no_nesp32(net_console):
    """Nothing on port 2 answers. The menu says so, and LOCAL GAME goes on
    to the game for two players."""
    table = Table(net_console)
    table.ports[0].deaf = True
    table.boot()
    open_menu(table, 0)
    console = table.consoles[0]
    table.run(10 * STATUS_POLL)
    assert screen_row(console, 9).strip() == "> HOST GAME"
    assert screen_row(console, OWN_ROW).strip() == "NO NESP32"
    # HOST GAME does nothing without a nesp32.
    tap(table, 0, PAD_A, rest=10)
    assert "WAITING" not in screen_text(console)
    for _ in range(2):
        tap(table, 0, PAD_DOWN)
    assert screen_row(console, 13).strip() == "> LOCAL GAME"
    assert screen_row(console, 9).strip() == "HOST GAME"
    tap(table, 0, PAD_A, rest=2)
    assert console.byte("net_menu") == 0 and console.byte("net_mode") == 0
    for _ in range(1000):
        if console.byte("LEVEL_ROUTINE_INDEX") == LEVEL_PLAYING:
            break
        table.run(1)
    assert console.byte("GAME_ROUTINE_INDEX") == ROUTINE_LEVEL
    assert console.byte("LEVEL_ROUTINE_INDEX") == LEVEL_PLAYING
    assert console.byte("PLAYER_MODE") == 1
    assert console.byte("P2_GAME_OVER_STATUS") == 0


def test_the_menu_says_hello_and_shows_the_nesp32s_address(net_console):
    table = Table(net_console)
    table.boot()
    open_menu(table, 0)
    console, stick = table.consoles[0], table.sticks[0]
    assert screen_row(console, 18).strip() == "THIS NESP32 IS AT"
    assert screen_row(console, OWN_ROW).strip() == "192.168.001.023"
    assert stick.app == (APP, 1) and stick.active(p.NESP_SVC_PEER)
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


def test_the_menu_puts_the_title_back_as_it_found_it(net_console):
    """The menu and the link keep their memory where the game keeps none,
    and the two tiles the menu drew its marks in are blank again: with a
    nesp32 answering throughout, LOCAL GAME goes on from the game's memory
    as the title left it."""
    table = Table(net_console)
    table.boot()
    console = table.consoles[0]
    tap(table, 0, PAD_START, rest=20)
    tap(table, 0, PAD_SELECT)
    tap(table, 0, PAD_START, rest=3 * STATUS_POLL)
    assert console.byte("net_menu") == 2
    before = bytes(console.ram[0x18:0x7E]), bytes(console.ram[0x200:0x700])
    assert any(console.vram[MARKS:MARKS + 32])
    table.run(4 * STATUS_POLL)
    for _ in range(2):
        tap(table, 0, PAD_DOWN)
    assert (bytes(console.ram[0x18:0x7E]), bytes(console.ram[0x200:0x700])) == before
    tap(table, 0, PAD_A, rest=2)
    assert console.byte("net_menu") == 0
    assert not any(console.vram[MARKS:MARKS + 32])
    assert console.byte("GAME_ROUTINE_INDEX") == 3


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
    assert table.sticks[0].shown(0) == "192.168.1.23"
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


def test_host_and_join_start_one_game(net_console):
    table = Table(net_console)
    table.boot()
    open_menu(table, 0)
    tap(table, 0, PAD_A, rest=2 * STATUS_POLL)
    open_join(table, 1)
    edit_last_octet_to_23(table, 1)
    tap(table, 1, PAD_START, rest=6 * STATUS_POLL)
    for side, console in enumerate(table.consoles):
        assert console.byte("net_menu") == 0
        assert console.byte("net_mode") == 1
        assert console.byte("net_role") == side
        assert console.byte("net_delay") == 2   # the nesp32's advice: 20 ms there and back
    table.begun()
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
    assert console.byte("net_mode") == 0 and console.byte("net_menu") == 0
    assert console.byte("GAME_ROUTINE_INDEX") <= 1
