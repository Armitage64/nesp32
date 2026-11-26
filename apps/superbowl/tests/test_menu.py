"""The netplay ROM's menu: what it shows, what it tells the nesp32, and that
HOST GAME on one console and JOIN GAME on the other end in one game on
both, whether they meet by a room's code or, with Select on either screen,
by an address. River City Ransom's tests (apps/rcr/tests/test_menu.py), on
Tecmo Super Bowl, whose menu is NETWORK GAME at the title."""

import pytest

import nesp
import nesp_proto as p

from drive import INTRO_FRAMES, PAD_A, PAD_B, PAD_DOWN, PAD_LEFT, PAD_RIGHT, PAD_SELECT, PAD_START
from drive import PAD_UP, TITLE_FRAMES, marker_row, screen_row, screen_text, sram
from netplay import APP, Table
from test_lockstep import moves
from wire import ms

OWN_ROW, HOST_ROW, DIGITS_ROW, MARK_ROW, STATUS_ROW = 20, 14, 12, 13, 16
TIP_ROW = 26                    # what Select does
HOST_GAME_ROW, JOIN_GAME_ROW, BACK_ROW = 9, 11, 24
LOCAL_GAME_ROW, NETWORK_GAME_ROW = 18, 20     # the title's (net/title.inc)
STARS_COLUMN, TEXT_COLUMN = 8, 12
TITLE_STARS = bytes([0x1B, 0x1C, 0x19])
LEFT_AND_B = PAD_LEFT | PAD_B   # at the title: the game's sound mode
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
    """NETWORK GAME at the title is the menu: Down to it, and Start."""
    console = table.consoles[side]
    assert console.byte("net_menu") == 0
    tap(table, side, PAD_DOWN)
    assert title_stars_row(console) == NETWORK_GAME_ROW
    tap(table, side, PAD_START, rest=3 * STATUS_POLL)
    assert console.byte("net_menu") == MENU_ON
    assert "NETWORK GAME" in screen_text(console)


def title_stars_row(console):
    """The row the title's stars are beside: LOCAL GAME's or NETWORK GAME's."""
    rows = [row for row in (LOCAL_GAME_ROW, NETWORK_GAME_ROW)
            if console.tiles(0x2000 + 32 * row + STARS_COLUMN, 3) == TITLE_STARS]
    assert len(rows) == 1, rows
    return rows[0]


def test_the_title_has_local_game_and_network_game(net_console):
    """In place of START GAME: LOCAL GAME, chosen, and NETWORK GAME. Up,
    Down and Select move the stars between them; the title drawn again
    has LOCAL GAME chosen."""
    table = Table(net_console)
    to_title(table)
    console = table.consoles[0]
    assert screen_row(console, LOCAL_GAME_ROW)[TEXT_COLUMN:].strip() == "LOCAL GAME"
    assert screen_row(console, NETWORK_GAME_ROW)[TEXT_COLUMN:].strip() == "NETWORK GAME"
    assert "START GAME" not in screen_text(console)
    assert title_stars_row(console) == LOCAL_GAME_ROW
    for pad, row in ((PAD_DOWN, NETWORK_GAME_ROW), (PAD_UP, LOCAL_GAME_ROW),
                     (PAD_SELECT, NETWORK_GAME_ROW), (PAD_DOWN, LOCAL_GAME_ROW),
                     (PAD_UP, NETWORK_GAME_ROW)):
        tap(table, 0, pad)
        assert title_stars_row(console) == row
    assert console.byte("net_menu") == 0
    # The sound mode (Left and B held) and back: the title again, at LOCAL GAME.
    table.run(120, pads=(LEFT_AND_B, 0))
    tap(table, 0, PAD_START, rest=TITLE_FRAMES)
    assert title_stars_row(console) == LOCAL_GAME_ROW


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
    """Nothing on port 2 answers. The menu says so, and B starts the
    console again."""
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
    # Two items, and no LOCAL GAME: the arrow stops at JOIN GAME.
    for _ in range(2):
        tap(table, 0, PAD_DOWN)
    assert marker_row(console) == JOIN_GAME_ROW
    assert "LOCAL GAME" not in screen_text(console)
    assert screen_row(console, BACK_ROW).strip() == "B - BACK"
    console.count_calls("net_reset")
    tap(table, 0, PAD_B, rest=2)
    assert console.calls_of("net_reset") == 1
    assert console.byte("net_menu") == 0 and console.byte("net_mode") == 0
    assert at_title_soon(table, console)


def at_title_soon(table, console, frames=SKIP_FRAMES):
    """The title, past the intro: its test for Start is made every frame,
    and the intro, which would be first, waits for a press."""
    console.count_calls("net_title_pick")
    table.run(frames)
    return console.calls_of("net_title_pick") > 0


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
        console.count_calls("net_title_pick")
    table.start()
    table.run(SKIP_FRAMES)
    for console in table.consoles:
        assert console.byte("MENU_ARROW_SPR_Y") == MAIN_MENU_FIRST_Y
        assert console.calls_of("net_title_pick") == 0
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


# --- the save ----------------------------------------------------------------------

ASK_ROW, YES_ROW, NO_ROW = 12, 15, 17


def save_of(console):
    """The save a session's consoles must have alike."""
    labels, ram = console.labels, console.bus.prg_ram
    return (bytes(ram[labels["SAVE_START"] - 0x6000:labels["SAVE_GAP"] - 0x6000])
            + bytes(ram[labels["SAVE_GAP_END"] - 0x6000:labels["SAVE_END"] - 0x6000]))


def hosts_save(make_console):
    """Player 1's save: the one the game makes in an empty save RAM, which
    the other console's makes too, with one team's control changed. (A save
    the game finds no good it makes again, and the two would be alike.)"""
    console = make_console()
    console.run(400)
    sram = bytearray(console.bus.prg_ram)
    sram[console.labels["TEAM_TYPE_SEASON"] - 0x6000] ^= 0x01
    return bytes(sram)


def connect_with_saves(table):
    to_title(table)
    host_by_address(table, 0)
    open_join(table, 1)
    edit_last_octet_to_23(table, 1)
    tap(table, 1, PAD_START, rest=8 * STATUS_POLL)


def test_different_saves_player_2_says_yes(net_console):
    table = Table(net_console, console_options=({"sram": hosts_save(net_console)}, {}))
    connect_with_saves(table)
    host, guest = table.consoles
    assert "CONTINUE" in screen_text(guest)
    assert screen_row(guest, YES_ROW).strip() == "YES"
    assert marker_row(guest) == YES_ROW
    assert "WAITING FOR PLAYER 2" in screen_text(host)
    assert marker_row(host) is None
    assert save_of(guest) != save_of(host)
    tap(table, 1, PAD_A, rest=0)
    # Player 1's save goes a piece a frame, and the copy follows it: some
    # seconds, and then the session, whose ticks are counted from its start.
    for _ in range(80):
        if all(console.byte("net_mode") == IN_SESSION for console in table.consoles):
            break
        table.run(10)
    in_session(table)
    assert save_of(guest) == save_of(host)
    table.begun()
    table.to_game()
    table.play(300, moves(7))
    assert table.same_game() > 600


def test_different_saves_player_2_says_no(net_console):
    table = Table(net_console, console_options=({"sram": hosts_save(net_console)}, {}))
    connect_with_saves(table)
    host, guest = table.consoles
    before = save_of(guest)
    tap(table, 1, PAD_DOWN)
    assert marker_row(guest) == NO_ROW
    tap(table, 1, PAD_A, rest=8 * STATUS_POLL)
    for console in table.consoles:
        assert console.byte("net_mode") == 0
        assert screen_row(console, HOST_GAME_ROW).strip() == "HOST GAME"
    assert save_of(guest) == before


def test_the_same_saves_are_not_asked_about(net_console):
    """Both consoles' saves are empty: straight into the session."""
    table = Table(net_console)
    connect_with_saves(table)
    in_session(table)


# --- a session given up ----------------------------------------------------------------

CHECK_AT = 0xFF - 8             # the tick each console takes its digest at (net_ram.inc)
WHY_DIFFERED, WHY_CHECK = 1, 0x5A
WHY_ROW = 22


def test_a_session_given_up_says_why(net_console):
    """Their games made to differ, in play: at the next check of the
    digests both consoles give the session up and come to the title, and
    each keeps why, which NETWORK GAME's first screen shows. (On hardware,
    November 2026, one console went black at such a time and the other to
    the title: this is for telling, after, which stopped first.)"""
    table = Table(net_console)
    table.start()
    table.to_game()
    for console in table.consoles:
        assert sram(console, "net_why") == 0      # a session's start clears it
    at = (table.ticks(0) // 256 + 1) * 256 + CHECK_AT - 2
    table.at_tick(at, lambda console: console.ram.__setitem__(0x46, console.ram[0x46] ^ 1), sides=(0,))
    play = moves(5)
    for _ in range(60):
        table.play(25, play)
        if not any(console.byte("net_mode") for console in table.consoles):
            break
    for console in table.consoles:
        assert console.byte("net_mode") == 0
        assert sram(console, "net_why") == WHY_DIFFERED
        assert sram(console, "net_why", 1) == WHY_DIFFERED ^ WHY_CHECK
        assert at_title_soon(table, console, frames=300)
    # Before it gave up, each sent its RAM to its nesp32's log (PEER's
    # DUMP), as it stood in the session: and the two differ in the game.
    dumps = [stick.peer_dump for stick in table.sticks]
    for dump in dumps:
        assert dump[NET_MODE] == 0x80
    assert [address for address in DIGESTED if dumps[0][address] != dumps[1][address]]
    open_menu(table, 0)
    assert screen_row(table.consoles[0], WHY_ROW).strip() == "LAST: GAMES DIFFERED"


NET_MODE = 0x067D               # $80 in a session (net/net_ram.inc)
DIGESTED = [*range(0x46, 0x49), *range(0x4B, 0xF0), *range(0x200, 0x300)]   # what the digest covers


RESETS_ROW = 25                 # the last reset (net_resets), the last exchange's NMI (net_crumb), the NMIs since (net_beat)
NET_KEEP = 12


@pytest.mark.parametrize("debug, damaged", [(True, False), (True, True), (False, False)])
def test_a_reset_in_play_is_kept_for_the_menu(net_console, debug_console, debug, damaged):
    """A console reset in play by no drop of the session's (on hardware,
    November 2026, one went to the title so, and the other then hung): in
    the debug build (NET_DEBUG), what its RAM held is kept through the
    reset, and NETWORK GAME's first screen shows it, the stack pointer and
    the session's state first. Damaged: its save fails the game's check at
    the reset, which clears it (a console that stopped dead after a play,
    as its stats went into the save, did on hardware), and the netplay's
    memory is kept all the same. The build for players keeps none of it,
    and the rows are blank."""
    table = Table(debug_console if debug else net_console)
    table.start()
    table.to_game()
    table.play(100, moves(5))
    console = table.consoles[1]
    if not debug:
        for name in ("net_resets", "net_crumb", "net_beat"):
            assert not any(sram(console, name, i) for i in range(NET_KEEP)), name
        reset_button(console)
        table.run(INTRO_FRAMES)
        table.run(3, pads=(0, PAD_START))
        table.run(TITLE_FRAMES)
        open_menu(table, 1)
        for row in range(RESETS_ROW, RESETS_ROW + 3):
            assert screen_row(console, row).strip() == ""
        assert not any(sram(console, "net_resets", i) for i in range(NET_KEEP))
        return
    sp = console.mpu.sp
    tick, stack = sram(console, "net_tick"), bytes(console.ram[0x101 + sp + i] for i in range(4))
    last_crumb = bytes(sram(console, "net_crumb", i) for i in range(NET_KEEP))
    assert last_crumb[1] in (tick, (tick - 1) & 0xFF)      # this tick's NMI, or the last
    last_beat = bytes(sram(console, "net_beat", i) for i in range(NET_KEEP))
    if damaged:
        console.bus.prg_ram[console.labels["SRAM_CHECK_VAL"] - 0x6000] ^= 0xFF
    reset_button(console)
    console.mpu.sp = (sp - 3) & 0xFF           # the reset's three, with nothing written
    table.run(INTRO_FRAMES)
    table.run(3, pads=(0, PAD_START))
    table.run(TITLE_FRAMES)
    assert console.byte("net_mode") == 0
    assert sram(console, "net_why") == 0      # no drop of the session's
    open_menu(table, 1)
    kept = bytes.fromhex(screen_row(console, RESETS_ROW).replace(" ", ""))
    assert len(kept) == NET_KEEP
    assert kept[0] == sp and kept[1] == IN_SESSION and kept[2] == tick
    assert kept[8:] == stack
    # The last session NMI's that came to the exchange, kept through the
    # reset: as it was then.
    crumb = bytes.fromhex(screen_row(console, RESETS_ROW + 1).replace(" ", ""))
    assert crumb == last_crumb
    if damaged:                                 # the game's clear did come
        assert sram(console, "SRAM_CHECK_VAL") == 0x41 and sram(console, "net_stack_copy") == 0
    # And the NMIs since, kept likewise.
    beat = bytes.fromhex(screen_row(console, RESETS_ROW + 2).replace(" ", ""))
    assert beat == last_beat
    assert beat[0] + 256 * beat[1] < 60       # the console never stopped
    assert beat[6] & 0x80                     # its NMI on (SOFT_PPU_CTRL)
