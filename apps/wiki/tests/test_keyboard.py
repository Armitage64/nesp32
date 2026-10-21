"""The search screen: the field, the keys, and what a search starts."""

import gen_screen
from console import (PAD_A, PAD_B, PAD_DOWN, PAD_LEFT, PAD_RIGHT, PAD_SELECT, PAD_START, PAD_UP)
from drive import STATE_LOADING, STATE_SEARCH, run_until, tap

ALT = gen_screen.ALT
DEFAULT = gen_screen.DEFAULT_QUERY
KEYS = gen_screen.KEYS
SPACE = len(KEYS)               # the last row's: the shift key and the space bar
SHIFT = (SPACE, 0)              # how lit_keys and go_to name them
BAR = (SPACE, 1)


def field(console):
    return console.text(1, gen_screen.FIELD_ROW, gen_screen.FIELD_COLUMN, 30)


def query(console):
    length = console.byte("query_len")
    start = console.labels["query"]
    return bytes(console.memory[start + offset] for offset in range(length)).decode("ascii")


def settle(console):
    console.run(8)              # everything staged has been drawn


def palette_at(console, column, row):
    """The palette of the square of tiles a tile of nametable 1 is in."""
    byte, shift = gen_screen.attribute_cell(column, row)
    return (console.nametable(1)[960 + byte] >> shift) & 3


def lit_keys(console):
    """The keys shown in the cursor's palette, as (row, column); the shift
    key is SHIFT and the space bar BAR. Every key's tile is in the keys'
    colour, and no other square of the keyboard has that palette."""
    lit = []
    for row in range(len(KEYS)):
        for column in range(len(KEYS[0])):
            at = gen_screen.key_column(column), gen_screen.KEY_ROW + 2 * row
            tile = console.tiles(1, at[1], at[0], 1)[0]
            assert chr(tile & 0x7F).upper() == KEYS[row][column] and tile & ALT
            if palette_at(console, *at) == gen_screen.PALETTE_CURSOR:
                lit.append((row, column))
    at = gen_screen.key_column(0), gen_screen.SPACE_ROW
    assert console.tiles(1, at[1], at[0], 1)[0] == ord(gen_screen.SHIFT_CHAR) | ALT
    if palette_at(console, *at) == gen_screen.PALETTE_CURSOR:
        lit.append(SHIFT)
    bar = console.tiles(1, gen_screen.SPACE_ROW, gen_screen.SPACE_COLUMN, 5)
    assert bytes(tile & 0x7F for tile in bar) == b"SPACE" and all(tile & ALT for tile in bar)
    palettes = {palette_at(console, gen_screen.SPACE_COLUMN + offset, gen_screen.SPACE_ROW)
                for offset in range(5)}
    assert len(palettes) == 1
    if palettes == {gen_screen.PALETTE_CURSOR}:
        lit.append(BAR)
    squares = sum(1 for row in range(8, 30, 2) for column in range(0, 32, 2)
                  if palette_at(console, column, row) == gen_screen.PALETTE_CURSOR)
    assert squares == sum(3 if key == BAR else 1 for key in lit)
    return lit


def go_to(console, row, column):
    """Walk the cursor to a key."""
    while console.byte("cur_row") != row:
        tap(console, PAD_DOWN if console.byte("cur_row") < row else PAD_UP)
    if row == SPACE:
        if (console.byte("cur_col") == 0) != (column == 0):
            tap(console, PAD_RIGHT)
        return
    while console.byte("cur_col") != column:
        tap(console, PAD_RIGHT if console.byte("cur_col") < column else PAD_LEFT)


def shift(console):
    go_to(console, *SHIFT)
    tap(console, PAD_A)


def type_text(console, text):
    for char in text:
        if char == " ":
            go_to(console, *BAR)
        else:
            row = next(index for index, keys in enumerate(KEYS) if char.upper() in keys)
            if char.isalpha() and (char.islower() != bool(console.byte("lower"))):
                shift(console)
            go_to(console, row, KEYS[row].index(char.upper()))
        tap(console, PAD_A)


def clear(console):
    while console.byte("query_len"):
        tap(console, PAD_B)


def test_power_on_shows_the_default_search(console, build):
    c = console()
    c.run(10)
    assert c.byte("state") == STATE_SEARCH
    assert query(c) == DEFAULT == "Nintendo Entertainment System"
    assert field(c) == DEFAULT + "_"
    assert lit_keys(c) == [(1, 0)]          # the cursor starts on Q
    # But for that key's palette, the screen is the one the build laid out.
    shown = bytearray(c.nametable(1))
    byte, value = gen_screen.key_attribute(1, 0)
    assert shown[960 + byte] == value
    shown[960 + byte] = 0
    assert bytes(shown) == (build / "screen.bin").read_bytes()
    assert c.text(1, gen_screen.PROMPT_ROW, 0, 32).rstrip("\x00") == "\x00SEARCH"
    assert c.nametable(0) == bytes(1024)


def test_the_logo_and_the_credit_are_the_headers(console):
    c = console()
    c.run(3)
    header = c.nametable(1)[:32 * gen_screen.HEADER_ROWS]
    rows = [header[32 * row:32 * row + 32] for row in range(gen_screen.HEADER_ROWS)]
    used = [row for row, tiles in enumerate(rows) if any(tiles)]
    assert used == [gen_screen.LOGO_ROW, gen_screen.LOGO_ROW + 1, gen_screen.CREDIT_ROW]
    logo = rows[gen_screen.LOGO_ROW]
    assert logo[:8] == bytes(8) and logo[24:] == bytes(8) and all(logo[8:24])    # 8 letters, centered
    # The header's rows take the logo's palette; the rest take the text's.
    attributes = c.nametable(1)[960:]
    assert attributes[:16] == bytes([0xFF] * 16) and attributes[16:] == bytes(48)


def test_the_cursors_key_pulses_through_white_and_the_blues(console):
    c = console()
    c.run(10)
    seen = []
    for _ in range(120):
        c.run(1)
        color = c.vram[gen_screen.PULSE_ADDRESS]
        if not seen or seen[-1] != color:
            seen.append(color)
    pulse = list(gen_screen.PULSE)
    assert len(seen) >= 12
    start = pulse.index(seen[0])
    assert seen == [pulse[(start + step) % len(pulse)] for step in range(len(seen))]
    assert set(pulse) == {0x30, 0x31, 0x21, 0x12}
    # Only that one colour of that one palette moves.
    assert c.vram[0x3F01] == 0x21 and c.vram[0x3F03] == 0x30
    # Typing goes on through it.
    type_text(c, "1")
    settle(c)
    assert query(c) == DEFAULT + "1" and field(c) == DEFAULT + "1"


def test_delete_and_type(console):
    c = console()
    c.run(3)
    for _ in range(7):
        tap(c, PAD_B)
    settle(c)
    assert query(c) == "Nintendo Entertainment" and field(c) == "Nintendo Entertainment_".ljust(30)
    type_text(c, " Sys")
    settle(c)
    assert query(c) == "Nintendo Entertainment Sys"
    assert field(c) == "Nintendo Entertainment Sys_".ljust(30)


def test_every_key_types_its_character(console):
    c = console()
    c.run(3)
    clear(c)
    for keys in KEYS:
        clear(c)
        type_text(c, keys)
        settle(c)
        assert query(c) == keys and field(c) == (keys + "_").ljust(30)


def test_small_letters(console):
    c = console()
    c.run(3)
    clear(c)
    type_text(c, "Zelda II")
    settle(c)
    assert query(c) == "Zelda II"
    assert field(c) == "Zelda II_".ljust(30)
    # Capitals are showing again, and one key is lit.
    assert c.text(1, gen_screen.KEY_ROW + 2, gen_screen.KEY_COLUMN, 19)[::2] == KEYS[1]
    assert len(lit_keys(c)) == 1


def test_shift_redraws_the_letters_and_keeps_the_cursor_lit(console):
    c = console()
    c.run(3)
    shift(c)
    settle(c)
    for row in (1, 2, 3):
        shown = c.tiles(1, gen_screen.KEY_ROW + 2 * row, gen_screen.KEY_COLUMN, 19)
        letters = bytes(tile & 0x7F for tile in shown[::2]).decode()
        assert letters == KEYS[row].lower()
    assert c.text(1, gen_screen.KEY_ROW, gen_screen.KEY_COLUMN, 19)[::2] == KEYS[0]
    assert lit_keys(c) == [SHIFT] and query(c) == DEFAULT     # it types nothing
    tap(c, PAD_A)
    settle(c)
    assert c.text(1, gen_screen.KEY_ROW + 2, gen_screen.KEY_COLUMN, 19)[::2] == KEYS[1]
    assert lit_keys(c) == [SHIFT]


def test_select_does_nothing_off_the_cartridge(console):
    c = console()
    c.run(3)
    assert not c.byte("on_cart")
    tap(c, PAD_SELECT)
    settle(c)
    assert c.byte("state") == STATE_SEARCH and query(c) == DEFAULT
    assert c.byte("lower") == 0 and lit_keys(c) == [(1, 0)]
    help_row, help_text = gen_screen.HELP[-1]
    assert c.text(1, help_row, 0, 32).strip("\x00 ") == help_text


def test_the_last_rows_left_and_right_go_between_shift_and_space(console):
    c = console()
    c.run(3)
    go_to(c, 3, 4)
    tap(c, PAD_DOWN)
    settle(c)
    assert lit_keys(c) == [BAR] and c.byte("cur_col") == 4
    tap(c, PAD_LEFT)
    settle(c)
    assert lit_keys(c) == [SHIFT]
    tap(c, PAD_LEFT)
    settle(c)
    assert lit_keys(c) == [BAR]
    tap(c, PAD_RIGHT)
    settle(c)
    assert lit_keys(c) == [SHIFT]
    tap(c, PAD_UP)                          # the shift key is under Z
    assert (c.byte("cur_row"), c.byte("cur_col")) == (3, 0)


def test_one_key_is_lit_wherever_the_cursor_goes(console):
    c = console()
    c.run(3)
    for row, column in ((0, 0), (0, 9), (3, 9), BAR, SHIFT, (3, 4), (1, 0)):
        go_to(c, row, column)
        settle(c)
        assert lit_keys(c) == [(row, column)]
    # Moving while the letters are being drawn again loses no key.
    shift(c)
    go_to(c, 3, 2)
    shift(c)
    go_to(c, 0, 5)
    settle(c)
    assert lit_keys(c) == [(0, 5)]


def test_the_cursor_wraps_sideways_and_stops_at_the_top_and_bottom(console):
    c = console()
    c.run(3)
    tap(c, PAD_LEFT)
    assert (c.byte("cur_row"), c.byte("cur_col")) == (1, 9)
    tap(c, PAD_RIGHT)
    assert c.byte("cur_col") == 0
    for _ in range(3):
        tap(c, PAD_UP)
    assert c.byte("cur_row") == 0
    for _ in range(8):
        tap(c, PAD_DOWN)
    assert c.byte("cur_row") == SPACE


def test_a_held_direction_repeats(console):
    c = console()
    c.run(3)
    c.run(19, pad=PAD_RIGHT)
    assert c.byte("cur_col") == 1           # one step, then a wait
    c.run(25, pad=PAD_RIGHT)
    assert c.byte("cur_col") == 6           # then one every 5 frames
    c.run(20, pad=0)
    assert c.byte("cur_col") == 6


def test_the_field_holds_thirty_characters(console):
    c = console()
    c.run(3)
    type_text(c, "12")
    settle(c)
    assert query(c) == DEFAULT.replace(" ", " ") + "1"
    assert field(c) == DEFAULT + "1" and len(query(c)) == 30    # full: no cursor


def test_a_search_cannot_start_with_a_space_or_be_empty(console):
    c = console()
    c.run(3)
    clear(c)
    settle(c)
    assert field(c) == "_".ljust(30)
    type_text(c, " ")
    assert query(c) == ""
    tap(c, PAD_START)
    c.run(3)
    assert c.byte("state") == STATE_SEARCH
    tap(c, PAD_B)                           # nothing to delete
    assert query(c) == ""
    type_text(c, "A B")
    assert query(c) == "A B"


def test_start_searches_and_b_gives_up(console):
    c = console()
    c.run(3)
    tap(c, PAD_START)
    assert c.byte("state") == STATE_LOADING
    c.run(4)
    assert c.text(1, gen_screen.STATUS_ROW, 2, 28).strip() == "SEARCHING..."
    tap(c, PAD_B)
    c.run(4)
    assert c.byte("state") == STATE_SEARCH
    assert c.text(1, gen_screen.STATUS_ROW, 2, 28).strip() == ""
    # The keyboard works again.
    tap(c, PAD_B)
    settle(c)
    assert query(c) == DEFAULT[:-1]


def test_the_keys_do_nothing_while_a_search_is_out(console):
    c = console()
    c.run(3)
    tap(c, PAD_START)
    tap(c, PAD_A)
    tap(c, PAD_RIGHT)
    assert query(c) == DEFAULT and c.byte("cur_col") == 0
    run_until(c, 3)
