"""The netplay ROM's menu: what it shows, what it tells the nesp32, and that
HOST GAME on one console and JOIN GAME on the other end in one game on
both, whether they meet by a room's code or, with Select on either screen,
by an address. TMNT II's tests (apps/tmnt2/tests/test_menu.py), on SMBX:
the cursor is the title's mushroom, a tile beside the line picked."""

import nesp
import nesp_proto as p

from drive import MODE_GAME, MODE_TITLE, PAD_A, PAD_B, PAD_DOWN, PAD_LEFT, PAD_RIGHT
from drive import PAD_SELECT, PAD_START, PAD_UP, moves, screen_row, screen_text
from netplay import APP, Table
from test_lockstep import to_game
from wire import ms

OWN_ROW, HOST_ROW, DIGITS_ROW, MARK_ROW, STATUS_ROW = 20, 14, 12, 13, 16
TIP_ROW = 26                    # what Select does
HOST_GAME_ROW, LOCAL_GAME_ROW = 9, 13
ITEMS_COLUMN = 11               # where the first screen's lines begin
CURSOR_COLUMN = ITEMS_COLUMN - 2    # the mushroom, two before them
LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
STATUS_POLL = 16                # frames between the menu's questions
# What the menu may change of the game's memory: the stack.
NOT_THE_GAMES = ((0x100, 0x200),)


def games_memory(console):
    ram = bytearray(console.ram)
    for start, end in NOT_THE_GAMES:
        ram[start:end] = bytes(end - start)
    return bytes(ram)


def cursor_row(console):
    """The row the mushroom is on, beside the first screen's lines; None
    with none shown."""
    rows = [row for row in range(30) if screen_row(console, row)[CURSOR_COLUMN] == "*"]
    assert len(rows) <= 1
    return rows[0] if rows else None


def tap(table, side, pad, rest=6):
    pads = [0, 0]
    pads[side] = pad
    table.run(3, pads=tuple(pads))
    table.run(rest)


def open_menu(table, side):
    """Select moves to 2 PLAYERS GAME, and Start there is the menu."""
    tap(table, side, PAD_SELECT)
    console = table.consoles[side]
    assert console.byte("TWO_PLAYERS") == 1
    tap(table, side, PAD_START, rest=3 * STATUS_POLL)
    assert console.byte("net_menu") == 2
    assert "NETWORK GAME" in screen_text(console)


def test_one_player_goes_straight_to_the_game(net_console):
    table = Table(net_console)
    table.boot()
    tap(table, 0, PAD_START, rest=200)
    console = table.consoles[0]
    assert console.byte("net_menu") == 0
    assert console.byte("OPER_MODE") == MODE_GAME
    assert console.byte("TWO_PLAYERS") == 0
    assert table.sticks[0].hellos == 0      # and the game itself says nothing


def host_by_address(table, side=0):
    """HOST GAME, and Select: by address."""
    open_menu(table, side)
    tap(table, side, PAD_A, rest=2 * STATUS_POLL)
    tap(table, side, PAD_SELECT, rest=2 * STATUS_POLL)
    assert "PLAYER 2 JOINS AT" in screen_text(table.consoles[side])


def test_local_game_with_no_nesp32(net_console):
    """Nothing on port 2 answers. The menu says so, and LOCAL GAME goes on
    to the game for two players."""
    table = Table(net_console)
    table.ports[0].deaf = True
    table.boot()
    open_menu(table, 0)
    console = table.consoles[0]
    table.run(10 * STATUS_POLL)
    assert screen_row(console, HOST_GAME_ROW)[ITEMS_COLUMN:].strip() == "HOST GAME"
    assert cursor_row(console) == HOST_GAME_ROW
    assert screen_row(console, OWN_ROW).strip() == "NO NESP32"
    # HOST GAME does nothing without a nesp32.
    tap(table, 0, PAD_A, rest=10)
    assert "WAITING" not in screen_text(console)
    for _ in range(2):
        tap(table, 0, PAD_DOWN)
    assert screen_row(console, LOCAL_GAME_ROW)[ITEMS_COLUMN:].strip() == "LOCAL GAME"
    assert cursor_row(console) == LOCAL_GAME_ROW
    tap(table, 0, PAD_A, rest=2)
    assert console.byte("net_menu") == 0 and console.byte("net_mode") == 0
    table.run(120)
    assert console.byte("OPER_MODE") == MODE_GAME
    assert console.byte("TWO_PLAYERS") == 1


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


def test_the_menu_leaves_the_games_memory_as_it_found_it(net_console):
    """The menu and the link keep their memory in the PRG RAM, and the zero
    page the link borrows is given back: with a nesp32 answering
    throughout, LOCAL GAME goes on from the game's memory as the title
    left it."""
    table = Table(net_console)
    table.boot()
    console = table.consoles[0]
    tap(table, 0, PAD_SELECT)
    tap(table, 0, PAD_START, rest=3 * STATUS_POLL)
    assert console.byte("net_menu") == 2
    before = games_memory(console)
    table.run(4 * STATUS_POLL)
    for _ in range(2):
        tap(table, 0, PAD_DOWN)
    assert games_memory(console) == before
    tap(table, 0, PAD_A, rest=0)
    assert console.byte("net_menu") == 0
    table.run(60)
    assert console.byte("OPER_MODE") == MODE_GAME


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
    host_by_address(table, 0)
    console = table.consoles[0]
    assert "WAITING FOR PLAYER 2" in screen_text(console)
    assert screen_row(console, HOST_ROW).strip() == "192.168.001.023"
    assert table.sticks[0].lobby == p.NESP_LOBBY_HOSTING
    assert table.sticks[0].shown(0) == "192.168.1.23"
    assert cursor_row(console) is None
    tap(table, 0, PAD_B, rest=2 * STATUS_POLL)
    assert screen_row(console, HOST_GAME_ROW)[ITEMS_COLUMN:].strip() == "HOST GAME"
    assert cursor_row(console) == HOST_GAME_ROW
    assert table.sticks[0].lobby == p.NESP_LOBBY_IDLE


def test_a_nesp32_switched_off_and_on_while_it_hosts(net_console):
    """It knows of no hello, and says so. The menu says hello again and has
    it wait again."""
    table = Table(net_console)
    table.boot()
    host_by_address(table, 0)
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
    """JOIN GAME, and Select: by address."""
    open_menu(table, side)
    tap(table, side, PAD_DOWN)
    tap(table, side, PAD_A)
    tap(table, side, PAD_SELECT, rest=3 * STATUS_POLL)
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
    host_by_address(table, 0)
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
    assert console.byte("OPER_MODE") == MODE_TITLE


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
    """By room code first, and Select says it changes that: on the host's
    screen, not the first one."""
    table = Table(net_console)
    table.boot()
    open_menu(table, 0)
    console, stick = table.consoles[0], table.sticks[0]
    assert "SELECT" not in screen_text(console)
    tap(table, 0, PAD_A, rest=4 * STATUS_POLL)
    assert "THE ROOM CODE IS" in screen_text(console)
    assert screen_row(console, TIP_ROW).strip() == "SELECT - BY IP"
    tap(table, 0, PAD_SELECT, rest=2 * STATUS_POLL)
    assert "PLAYER 2 JOINS AT" in screen_text(console)
    assert screen_row(console, HOST_ROW).strip() == "192.168.001.023"
    assert screen_row(console, TIP_ROW).strip() == "SELECT - BY ROOM CODE"
    assert stick.lobby == p.NESP_LOBBY_HOSTING and stick.listens == 1
    tap(table, 0, PAD_SELECT, rest=4 * STATUS_POLL)
    assert "THE ROOM CODE IS" in screen_text(console)
    assert stick.meets == 2
    # And the way holds: back, and HOST GAME again, is by room code.
    tap(table, 0, PAD_SELECT, rest=2 * STATUS_POLL)
    tap(table, 0, PAD_B, rest=2 * STATUS_POLL)
    tap(table, 0, PAD_A, rest=2 * STATUS_POLL)
    assert "PLAYER 2 JOINS AT" in screen_text(console)


def test_select_changes_how_player_2_joins(net_console):
    table = Table(net_console)
    table.boot()
    open_menu(table, 1)
    tap(table, 1, PAD_DOWN)
    tap(table, 1, PAD_A, rest=2 * STATUS_POLL)
    console = table.consoles[1]
    assert "JOIN THE ROOM OF CODE" in screen_text(console)
    assert screen_row(console, TIP_ROW).strip() == "SELECT - BY IP"
    tap(table, 1, PAD_SELECT, rest=2 * STATUS_POLL)
    assert "JOIN THE GAME AT" in screen_text(console)
    assert screen_row(console, DIGITS_ROW).strip() == "192.168.001.042"
    assert screen_row(console, TIP_ROW).strip() == "SELECT - BY ROOM CODE"
    tap(table, 1, PAD_SELECT, rest=2 * STATUS_POLL)
    assert "JOIN THE ROOM OF CODE" in screen_text(console)
    assert screen_row(console, DIGITS_ROW).strip() == "AAAA"


def test_a_host_by_room_shows_its_code_and_back(net_console):
    table = Table(net_console)
    table.boot()
    code = host_room(table)
    stick = table.sticks[0]
    assert stick.lobby == p.NESP_LOBBY_HOSTING
    assert code in table.lan.rooms.rooms
    table.run(STATUS_POLL)
    assert stick.shown(0) == "Room " + code
    tap(table, 0, PAD_B, rest=2 * STATUS_POLL)
    assert cursor_row(table.consoles[0]) == HOST_GAME_ROW
    assert stick.lobby == p.NESP_LOBBY_IDLE


def test_host_and_join_by_code_start_one_game(net_console):
    table = Table(net_console, delay=ms(5))
    table.boot()
    code = host_room(table, 0)
    join_room(table, 1, code)
    assert screen_row(table.consoles[1], STATUS_ROW).strip() == "CONNECTING"
    # The host hears of player 2 when it next asks the rendezvous.
    table.run(p.NESP_PEER_POLL_MS * 60 // 1000 + 6 * STATUS_POLL)
    for side, console in enumerate(table.consoles):
        assert console.byte("net_mode") == 1
        assert console.byte("net_role") == side
    table.begun()
    to_game(table)
    table.play(200, moves(seed=5))
    assert table.same_game() > 200
    # A code is not an address: nothing is kept for next time.
    assert table.sticks[1].last is None


def test_a_code_with_no_room(net_console):
    table = Table(net_console)
    table.boot()
    join_room(table, 1, "K7QF")
    table.run(4 * STATUS_POLL)
    console = table.consoles[1]
    assert screen_row(console, STATUS_ROW).strip() == "NO SUCH ROOM"
    # And the code can be edited again, from where it was.
    tap(table, 1, PAD_UP)
    assert screen_row(console, DIGITS_ROW).strip() == "K7QG"


def test_two_that_cannot_reach_each_other_are_told(net_console):
    table = Table(net_console)
    table.lan.reachable = False
    table.boot()
    code = host_room(table, 0)
    join_room(table, 1, code)
    table.run(p.NESP_PEER_POLL_MS * 60 // 1000 + 6 * STATUS_POLL)
    assert screen_row(table.consoles[1], STATUS_ROW).strip() == "CANNOT REACH IT"


def test_another_versions_room_is_not_joined(net_console):
    table = Table(net_console)
    table.boot()
    status, line = table.lan.rooms.answer("/v1/host?app=CNTR&ver=2&c=192.168.1.23:6502")
    join_room(table, 1, line.split()[1])
    table.run(4 * STATUS_POLL)
    assert screen_row(table.consoles[1], STATUS_ROW).strip() == "NOT THIS GAME"


def test_a_nesp32_whose_firmware_has_no_rooms(net_console):
    """It has PEER, but none of the room ops: the screen says what to do
    about it, and Select still finds the other by address."""
    def old(data):
        reply = nesp.parse(data)
        if reply.svc == p.NESP_SVC_PEER and len(reply.payload) == 11:
            return nesp.reply_frame(reply.svc, p.NESP_ST_NO_OP, reply.seq, b"")
        return data
    table = Table(net_console, port_options=({"to_console": old}, {}))
    table.boot()
    open_menu(table, 0)
    console = table.consoles[0]
    tap(table, 0, PAD_A, rest=4 * STATUS_POLL)
    assert screen_row(console, STATUS_ROW).strip() == "UPDATE NESP32"
    assert screen_row(console, TIP_ROW).strip() == "SELECT - BY IP"
    tap(table, 0, PAD_SELECT, rest=2 * STATUS_POLL)
    assert screen_row(console, HOST_ROW).strip() == "192.168.001.023"
    assert table.sticks[0].lobby == p.NESP_LOBBY_HOSTING


def test_a_nesp32_switched_off_and_on_while_it_hosts_a_room(net_console):
    """It is told to open a room again, which has a new code."""
    table = Table(net_console)
    table.boot()
    host_room(table, 0)
    stick = table.restart(0)
    table.run(4 * STATUS_POLL)
    assert stick.hellos == 1 and stick.lobby == p.NESP_LOBBY_HOSTING
    code = screen_row(table.consoles[0], HOST_ROW).strip()
    assert code in table.lan.rooms.rooms
