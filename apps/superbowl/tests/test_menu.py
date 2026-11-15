"""The netplay ROM's menu: what it shows, what it tells the nesp32, and that
HOST GAME on one console and JOIN GAME on the other end in one game on
both, whether they meet by a room's code or, with Select on either screen,
by an address. River City Ransom's tests (apps/rcr/tests/test_menu.py), on
Tecmo Super Bowl, whose menu is opened by Select at the title."""

import nesp
import nesp_proto as p

from drive import INTRO_FRAMES, PAD_A, PAD_B, PAD_DOWN, PAD_RIGHT, PAD_SELECT, PAD_START
from drive import PAD_UP, TITLE_FRAMES, marker_row, screen_row, screen_text, sram
from netplay import APP, Table
from test_lockstep import moves
from wire import ms

OWN_ROW, HOST_ROW, DIGITS_ROW, MARK_ROW, STATUS_ROW = 20, 14, 12, 13, 16
TIP_ROW = 26                    # what Select does
HOST_GAME_ROW, LOCAL_GAME_ROW = 9, 13
LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
STATUS_POLL = 16                # frames between the menu's questions
MENU_ON = 0x80                  # net_menu
IN_SESSION = 0x80               # net_mode
MAIN_MENU_FIRST_Y = 0x50        # the game's main menu's arrow, at PRESEASON (MAIN_MENU_OPTIONS_DATA)
SKIP_FRAMES = 60                # from a reset of the netplay's own to the title or main menu


def tap(table, side, pad, rest=6):
    pads = [0, 0]
    pads[side] = pad
    table.run(3, pads=tuple(pads))
    table.run(rest)


def to_title(table):
    """Both consoles from the power on to the title: Start at the intro.
    The second console's presses are its own controller 1's."""
    table.run(INTRO_FRAMES)
    table.run(3, pads=(PAD_START, PAD_START))
    table.run(TITLE_FRAMES)


def open_menu(table, side):
    """Select at the title is the menu."""
    console = table.consoles[side]
    assert console.byte("net_menu") == 0
    tap(table, side, PAD_SELECT, rest=3 * STATUS_POLL)
    assert console.byte("net_menu") == MENU_ON
    assert "NETWORK GAME" in screen_text(console)


def test_start_at_the_title_is_the_game(net_console):
    table = Table(net_console)
    to_title(table)
    console = table.consoles[0]
    tap(table, 0, PAD_START, rest=200)
    # The main menu's arrow, beside PRESEASON.
    assert console.byte("MENU_ARROW_SPR_Y") == MAIN_MENU_FIRST_Y
    assert console.byte("net_menu") == 0
    assert table.sticks[0].hellos == 0      # and the game itself says nothing


def host_by_address(table, side=0):
    """HOST GAME, and Select: by address."""
    open_menu(table, side)
    tap(table, side, PAD_A, rest=2 * STATUS_POLL)
    tap(table, side, PAD_SELECT, rest=2 * STATUS_POLL)
    assert "PLAYER 2 JOINS AT" in screen_text(table.consoles[side])


def test_local_game_with_no_nesp32(net_console):
    """Nothing on port 2 answers. The menu says so, and LOCAL GAME starts
    the console again."""
    table = Table(net_console)
    table.ports[0].deaf = True
    to_title(table)
    open_menu(table, 0)
    console = table.consoles[0]
    table.run(10 * STATUS_POLL)
    assert screen_row(console, HOST_GAME_ROW).strip() == "HOST GAME"
    assert marker_row(console) == HOST_GAME_ROW
    assert screen_row(console, OWN_ROW).strip() == "NO NESP32"
    # HOST GAME does nothing without a nesp32.
    tap(table, 0, PAD_A, rest=10)
    assert "WAITING" not in screen_text(console)
    for _ in range(2):
        tap(table, 0, PAD_DOWN)
    assert screen_row(console, LOCAL_GAME_ROW).strip() == "LOCAL GAME"
    assert marker_row(console) == LOCAL_GAME_ROW
    console.count_calls("net_reset")
    tap(table, 0, PAD_A, rest=2)
    assert console.calls_of("net_reset") == 1
    assert console.byte("net_menu") == 0 and console.byte("net_mode") == 0
    assert at_title_soon(table, console)


def at_title_soon(table, console, frames=SKIP_FRAMES):
    """The title, past the intro: its test for Start is made every frame,
    and the intro, which would be first, waits for a press."""
    console.count_calls("net_title_press")
    table.run(frames)
    return console.calls_of("net_title_press") > 0


def reset_button(console):
    """The console's Reset: the CPU to the reset vector, and nothing else of
    it or the cartridge changed."""
    console.mpu.pc = console.bus[0xFFFC] | console.bus[0xFFFD] << 8
    console.interrupts = []


def test_b_goes_back_to_the_title_and_reset_to_the_intro(net_console):
    table = Table(net_console)
    to_title(table)
    open_menu(table, 0)
    console = table.consoles[0]
    tap(table, 0, PAD_B, rest=2)
    assert console.byte("net_menu") == 0
    assert at_title_soon(table, console)
    # The mark was the reset's alone: the console's own plays the intro.
    reset_button(console)
    assert not at_title_soon(table, console, frames=4 * SKIP_FRAMES)
    assert console.byte("net_skip") == 0


def test_the_menu_says_hello_and_shows_the_nesp32s_address(net_console):
    table = Table(net_console)
    to_title(table)
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
    to_title(table)
    open_menu(table, 0)
    console = table.consoles[0]
    assert screen_row(console, OWN_ROW).strip() == "UPDATE NESP32"
    tap(table, 0, PAD_A)
    assert "WAITING" not in screen_text(console)


def test_a_nesp32_with_no_wifi(net_console):
    table = Table(net_console, addresses=(None, None))
    to_title(table)
    open_menu(table, 0)
    assert screen_row(table.consoles[0], OWN_ROW).strip() == "NO WIFI"
    tap(table, 0, PAD_A)
    assert "WAITING" not in screen_text(table.consoles[0])


def test_host_and_back(net_console):
    table = Table(net_console)
    to_title(table)
    host_by_address(table, 0)
    console = table.consoles[0]
    assert "WAITING FOR PLAYER 2" in screen_text(console)
    assert screen_row(console, HOST_ROW).strip() == "192.168.001.023"
    assert table.sticks[0].lobby == p.NESP_LOBBY_HOSTING
    assert marker_row(console) is None
    tap(table, 0, PAD_B, rest=2 * STATUS_POLL)
    assert screen_row(console, HOST_GAME_ROW).strip() == "HOST GAME"
    assert marker_row(console) == HOST_GAME_ROW
    assert table.sticks[0].lobby == p.NESP_LOBBY_IDLE


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
    """JOIN GAME, and Select: by address."""
    open_menu(table, side)
    tap(table, side, PAD_DOWN)
    tap(table, side, PAD_A)
    tap(table, side, PAD_SELECT, rest=3 * STATUS_POLL)
    assert "JOIN THE GAME AT" in screen_text(table.consoles[side])


def test_join_with_nobody_hosting(net_console):
    table = Table(net_console)
    to_title(table)
    open_join(table, 1)
    edit_last_octet_to_23(table, 1)
    tap(table, 1, PAD_START, rest=2)
    console = table.consoles[1]
    assert screen_row(console, STATUS_ROW).strip() == "CONNECTING"
    table.run(4 * STATUS_POLL)
    assert screen_row(console, STATUS_ROW).strip() == "COULD NOT JOIN"


def in_session(table):
    """Both consoles in a session, the first player 1, each with its
    nesp32's advice for its delay."""
    for side, console in enumerate(table.consoles):
        assert console.byte("net_menu") == 0
        assert console.byte("net_mode") == IN_SESSION
        assert sram(console, "net_role") == side
        advice = table.sticks[side].ask(p.NESP_SVC_PEER, p.NESP_PEER_STATUS).payload[5]
        assert sram(console, "net_delay") == advice


def test_host_and_join_start_one_game(net_console):
    table = Table(net_console)
    to_title(table)
    host_by_address(table, 0)
    open_join(table, 1)
    edit_last_octet_to_23(table, 1)
    tap(table, 1, PAD_START, rest=6 * STATUS_POLL)
    in_session(table)
    table.begun()
    table.to_game()
    table.play(300, moves(3))
    assert table.same_game() > 600
    # The second nesp32 keeps where it joined, for next time.
    assert table.sticks[1].last == bytes((192, 168, 1, 23))


def test_a_lost_session_starts_the_console_again(net_console):
    table = Table(net_console)
    table.start()
    table.run(60)
    console = table.consoles[0]
    console.count_calls("net_reset")
    table.lan.cut()
    table.run(300)
    assert console.calls_of("net_reset") == 1
    assert console.byte("net_mode") == 0 and console.byte("net_menu") == 0
    assert at_title_soon(table, console, frames=200)


def test_a_session_begins_at_the_main_menu(net_console):
    table = Table(net_console)
    for console in table.consoles:
        console.count_calls("net_title_press")
    table.start()
    table.run(SKIP_FRAMES)
    for console in table.consoles:
        assert console.byte("MENU_ARROW_SPR_Y") == MAIN_MENU_FIRST_Y
        assert console.calls_of("net_title_press") == 0
        assert console.byte("net_mode") == IN_SESSION


# --- by a room's code ----------------------------------------------------------------

def host_room(table, side=0):
    """HOST GAME, by a room's code: the room's code, once it is shown."""
    open_menu(table, side)
    console = table.consoles[side]
    tap(table, side, PAD_A, rest=4 * STATUS_POLL)
    assert "THE ROOM CODE IS" in screen_text(console)
    code = screen_row(console, HOST_ROW).strip()
    assert len(code) == 4 and all(letter in LETTERS for letter in code)
    return code


def enter_code(table, side, code):
    """On the join screen, from the code it shows, to this one."""
    console = table.consoles[side]
    shown = screen_row(console, DIGITS_ROW).strip()
    for place, (now, wanted) in enumerate(zip(shown, code)):
        steps = (LETTERS.index(wanted) - LETTERS.index(now)) % len(LETTERS)
        pad = PAD_UP if steps <= len(LETTERS) // 2 else PAD_DOWN
        for _ in range(steps if pad == PAD_UP else len(LETTERS) - steps):
            tap(table, side, pad, rest=2)
        if place < 3:
            tap(table, side, PAD_RIGHT, rest=2)
    assert screen_row(console, DIGITS_ROW).strip() == code


def join_room(table, side, code):
    open_menu(table, side)
    tap(table, side, PAD_DOWN)
    tap(table, side, PAD_A, rest=2 * STATUS_POLL)
    console = table.consoles[side]
    assert "JOIN THE ROOM OF CODE" in screen_text(console)
    assert screen_row(console, DIGITS_ROW).strip() == "AAAA"
    enter_code(table, side, code)
    tap(table, side, PAD_START, rest=2)


def test_select_changes_how_the_host_waits(net_console):
    table = Table(net_console)
    to_title(table)
    open_menu(table, 0)
    console, stick = table.consoles[0], table.sticks[0]
    assert "SELECT" not in screen_text(console)
    tap(table, 0, PAD_A, rest=4 * STATUS_POLL)
    assert "THE ROOM CODE IS" in screen_text(console)
    assert screen_row(console, TIP_ROW).strip() == "SELECT - BY IP"
    tap(table, 0, PAD_SELECT, rest=2 * STATUS_POLL)
    assert "PLAYER 2 JOINS AT" in screen_text(console)
    assert screen_row(console, TIP_ROW).strip() == "SELECT - BY ROOM CODE"
    assert stick.lobby == p.NESP_LOBBY_HOSTING


def test_host_and_join_by_code_start_one_game(net_console):
    table = Table(net_console, delay=ms(5))
    to_title(table)
    code = host_room(table, 0)
    join_room(table, 1, code)
    assert screen_row(table.consoles[1], STATUS_ROW).strip() == "CONNECTING"
    # The host hears of player 2 when it next asks the rendezvous.
    table.run(p.NESP_PEER_POLL_MS * 60 // 1000 + 6 * STATUS_POLL)
    in_session(table)
    table.begun()
    table.to_game()
    table.play(300, moves(5))
    assert table.same_game() > 600
    assert table.sticks[1].last is None


def test_a_code_with_no_room(net_console):
    table = Table(net_console)
    to_title(table)
    join_room(table, 1, "K7QF")
    table.run(4 * STATUS_POLL)
    console = table.consoles[1]
    assert screen_row(console, STATUS_ROW).strip() == "NO SUCH ROOM"
    tap(table, 1, PAD_UP)
    assert screen_row(console, DIGITS_ROW).strip() == "K7QG"


def test_another_versions_room_is_not_joined(net_console):
    table = Table(net_console)
    to_title(table)
    status, line = table.lan.rooms.answer("/v1/host?app=BUBL&ver=1&c=192.168.1.23:6502")
    join_room(table, 1, line.split()[1])
    table.run(4 * STATUS_POLL)
    assert screen_row(table.consoles[1], STATUS_ROW).strip() == "NOT THIS GAME"
