#!/usr/bin/env python3
"""Write the Bluesky ROM's tiles, its two screens, and the texts and tables
it puts on them.

    tools/gen_screen.py build
    tools/gen_screen.py build --preview docs/screen.png

    chr.bin             8 KB: a page of this ROM's sprites, then ConnectedNES's page
    splash.bin          the splash: ConnectedNES's screen, with this ROM's words
    her.bin             the rest: her screen, with no words
    palette.bin         her palettes, the background's and the sprites'
    screen.inc          where things go, and what the ROM writes there

Every screen is Rachel Simone Weil's, from ConnectedNES (../connectednes):
her picture, her font, her palettes, on her page of tiles. The splash has
this ROM's words in place of hers. The rest have eight lines where she
drew a tweet, on every other row, each after one of her arrows: the
favorites, a handle a line; the form a handle is typed in; and a post, as
the nesp32 lays one out (nesp32's docs/PROTOCOL.md, BSKY), the handle
first, six of the text, and when it was posted last. Her blue ground at the
foot has a line of status, and a line of what the buttons do.

Her font has each character at its ASCII code with the bits in the other
order. Her ground has its own font, colour 1 on colour 3, of which she had
only her own words' letters; this makes the rest it needs, in tiles of her
page that are empty, with the three signs a post's line of when has.

The one sprite is the arrow at a favorite, or the mark under the form's
letter that Up and Down change, white in her sprites' first palette. Its
tiles are the first page's, NESpedia's font's (../../wiki/tools).
"""

import argparse
import importlib.util
import os
import string
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "..")
CONNECTEDNES = os.path.join(APP, "connectednes")
WIKI_TOOLS = os.path.join(APP, "..", "wiki", "tools")


def load_wiki():
    """NESpedia's gen_screen.py, which has this one's name, as its own
    module. It finds nesp32's numbers through its stick.py."""
    sys.path.insert(0, WIKI_TOOLS)
    spec = importlib.util.spec_from_file_location(
        "nespedia_screen", os.path.join(WIKI_TOOLS, "gen_screen.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wiki = load_wiki()
from stick import proto  # noqa: E402

SCREEN_COLUMNS, SCREEN_ROWS = wiki.SCREEN_COLUMNS, wiki.SCREEN_ROWS
NAMETABLE = 0x2000
PAGE = 0x1000                       # a page of tiles

POST_COLUMNS = proto.NESP_BSKY_COLUMNS
POST_LINES = proto.NESP_BSKY_ROWS
HANDLE_ROW, WHEN_ROW, TEXT_ROW = (proto.NESP_BSKY_HANDLE_ROW, proto.NESP_BSKY_WHEN_ROW,
                                  proto.NESP_BSKY_TEXT_ROW)
HANDLE_MAX = proto.NESP_BSKY_HANDLE_MAX
FAVORITES = proto.NESP_BSKY_FAVORITES
SIGN_CODES = (proto.NESP_BSKY_REPLY, proto.NESP_BSKY_REPOST, proto.NESP_BSKY_LIKE)

# --- her screen ----------------------------------------------------------------------

HER_COLUMN = 4                      # where every line of hers began
WIDTH = 26                          # from there to where her foot's line ended
HER_BLANK = 0x00                    # her blank tile
HER_GROUND = 0x37                   # her blue ground's
HER_WORD_ROWS = (10, 12, 16, 20, 21)    # the rows her words were on, and the dots under "WiFi"
SLOT_ROWS = (8, 10, 12, 14, 16, 18, 20, 22)     # her eight lines
SLOTS = len(SLOT_ROWS)
TEXT_SLOTS = SLOTS - 2              # a post's text's: between the handle and when
STATUS_ROW, HELP_ROW = 25, 26       # on her ground
PAINT_ROWS = SLOTS + 1              # what the ROM paints a row at a time: her lines, the help

# In the order of the ROM's STATUS_* numbers, centered in COLUMNS, of which
# her ground shows the middle WIDTH. After the last are the nesp32's own
# words (STATUS_WHY) and the count of posts the ROM makes (STATUS_COUNT).
COLUMNS = 28
SKIP = (COLUMNS - WIDTH) // 2
STATUS_TEXT = (
    ("NONE", ""),
    ("FAVORITES", "FAVORITES"),
    ("WAITING", "WAITING FOR LINK"),
    ("OLD", "UPDATE THE NESP32"),
    ("NO_WIFI", "NO WI-FI"),
    ("FETCHING", "FETCHING POSTS"),
    ("NO_POSTS", "NO POSTS YET"),
    ("NOT_FOUND", "NO ONE HAS THAT HANDLE"),
    ("BAD", "THAT IS NOT A HANDLE"),
    ("EMPTY", "TYPE A HANDLE FIRST"),
    ("REMOVE", "START AGAIN TO REMOVE"),
    ("REMOVED", "REMOVED FROM FAVORITES"),
    ("SAVED", "SAVED TO FAVORITES"),
    ("FULL", "NO ROOM FOR MORE"),
    ("SPLASH_WAITING", "Looking for the nesp32..."),
    ("SPLASH_START", "Press Start"),
    ("SPLASH_OLD", "Update the nesp32"),
)
COUNT_TEXT = "POST %d OF %d"        # STATUS_COUNT, which the ROM writes,
PAGE_TEXT = " PAGE %d/%d"           # and this after it for a post of more than a page

# The favorites: a handle a line, and after them the way to the form. The
# lines show eight of them at a time, the arrow's among them.
OTHER_TEXT = "Read another handle"
ARROW_COLUMN = HER_COLUMN - 2       # over her arrow

# The form, by her lines. The handle is typed a letter at a time, from
# these, in this order: Up is the next and Down the one before.
FORM_LINES = ((0, "Read a handle:"),
              (4, "Up/Down: change a letter"),
              (5, "Left/Right: move along"),
              (6, "With no dot, a name is"),
              (7, "name.bsky.social"))
FORM_SLOT = 2                       # the handle's line
FORM_MAX = WIDTH                    # letters in it
LETTERS = " abcdefghijklmnopqrstuvwxyz0123456789.-"

HELP_LIST = "A:read Start:remove"
HELP_LIST_CART = "A:read St:remove Sel:menu"    # on the cartridge, Select is its menu
HELP_FORM = "A:read Start:save B:back"
HELP_POST = "L/R:post U/D:page B:back"

# The splash: these words on her rows, from her column, her status line,
# and two lines on her ground where she had one.
SPLASH_LINES = (
    (10, "Bluesky for the nesp32"),
    (12, "after ConnectedNES by"),
    (14, "Rachel Weil (HXLNT)"),
    (16, "nobadmemories.com"),
)
SPLASH_STATUS_ROW = 20
SPLASH_FOOT_LINES = ((25, "nesp32 port:"), (26, "youtube.com/@levimaaia"))

# Her ground's font: what any status may say (capitals, digits, and what
# the nesp32's words may have), and every character of the fixed lines.
GROUND_CHARS = (set(string.ascii_uppercase + string.digits + ":/.-'!?,")
                | set("".join(text for _, text in SPLASH_FOOT_LINES)
                      + HELP_LIST + HELP_LIST_CART + HELP_FORM + HELP_POST)) - {" "}

# The signs a post's line of when has, in her font's colour.
SIGNS = {
    proto.NESP_BSKY_REPLY: """
        ........
        ..#.....
        .##.....
        ########
        .##....#
        ..#....#
        .......#
        ........""",            # a reply: an arrow that turns back
    proto.NESP_BSKY_REPOST: """
        ........
        .####...
        ##..#...
        #.......
        #...#...
        #..###..
        ....#...
        ........""",            # a repost: the end of one arrow, and another
    proto.NESP_BSKY_LIKE: """
        ........
        .##.##..
        #######.
        #######.
        .#####..
        ..###...
        ...#....
        ........""",            # a like: a heart
}
HER_FONT_COLOR = 1

# The sprite's tiles, on the first page, in her sprites' white.
ARROW_TILE = ord(">")
MARK_TILE = ord("_")
SPRITE_COLOR = 2


def read(name):
    with open(os.path.join(CONNECTEDNES, name), "rb") as handle:
        return handle.read()


def reversed_code(char):
    return int("{:08b}".format(ord(char))[::-1], 2)


def her_names():
    return b"".join(read("loadingscreen%d.nam" % number) for number in range(1, 5))


def tile_from(drawing, color):
    rows = [line.strip() for line in drawing.strip().splitlines()]
    return [[color if char == "#" else 0 for char in row] for row in rows]


def on_ground(tile):
    """One of her font's tiles as her ground's letters are: what is colour 0
    in it, colour 3."""
    out = bytearray(tile)
    for y in range(8):
        out[y] |= ~tile[y] & ~tile[8 + y] & 0xFF
        out[8 + y] |= ~tile[y] & ~tile[8 + y] & 0xFF
    return bytes(out)


class HerPage:
    """Her page of tiles, with the ground's letters and the signs in tiles
    that are empty and that her screen does not use; and which tile each
    character has, in her font and on her ground."""

    def __init__(self):
        page = bytearray(read("ascii.chr")[PAGE:2 * PAGE])
        used = set(her_names())
        free = [tile for tile in range(256)
                if not any(page[16 * tile:16 * tile + 16]) and tile not in used]
        self.font = {" ": HER_BLANK}
        for code in range(0x21, 0x7F):
            tile = reversed_code(chr(code))
            if any(page[16 * tile:16 * tile + 16]):
                self.font[chr(code)] = tile
        self.ground = {" ": HER_GROUND}

        def take():
            if not free:
                raise ValueError("ConnectedNES's page has no room for this ROM's tiles")
            return free.pop(0)

        for char in sorted(GROUND_CHARS):
            if char not in self.font:
                raise ValueError("ConnectedNES's font has no %r" % char)
            tile = take()
            plain = self.font[char]
            page[16 * tile:16 * tile + 16] = on_ground(page[16 * plain:16 * plain + 16])
            self.ground[char] = tile
        for code, drawing in SIGNS.items():
            tile = take()
            page[16 * tile:16 * tile + 16] = wiki.tile_bytes(tile_from(drawing, HER_FONT_COLOR))
            self.font[chr(code)] = tile
        self.page = bytes(page)
        self.free = len(free)

    def text(self, text, width=None, ground=False):
        table = self.ground if ground else self.font
        blank = HER_GROUND if ground else HER_BLANK
        tiles = bytes(table.get(char, blank) for char in text)
        return tiles if width is None else tiles.ljust(width, bytes((blank,)))

    def table(self, ground=False):
        """ASCII to tiles, 128 of them: what the ROM maps a line through."""
        mapping = self.ground if ground else self.font
        blank = HER_GROUND if ground else HER_BLANK
        return bytes(mapping.get(chr(code), blank) for code in range(128))


def her_screen():
    """Her nametable, with her words taken off."""
    names = bytearray(her_names()[:SCREEN_COLUMNS * SCREEN_ROWS])
    for row in HER_WORD_ROWS:
        start = row * SCREEN_COLUMNS
        names[start + HER_COLUMN:start + SCREEN_COLUMNS] = bytes(
            (HER_BLANK,)) * (SCREEN_COLUMNS - HER_COLUMN)
    return names


def put(names, row, tiles, column=HER_COLUMN):
    start = row * SCREEN_COLUMNS + column
    names[start:start + len(tiles)] = tiles


def splash(page=None):
    """The splash: her screen with this ROM's words."""
    page = page or HerPage()
    names = her_screen()
    for row, text in SPLASH_LINES:
        put(names, row, page.text(text))
    for row, text in SPLASH_FOOT_LINES:
        put(names, row, page.text(text, WIDTH, ground=True))
    return bytes(names) + read("test.atr")


def blank_screen(page=None):
    """The screen for the rest, with nothing on her lines or her ground."""
    page = page or HerPage()
    names = her_screen()
    for row in (STATUS_ROW, HELP_ROW):
        put(names, row, page.text("", WIDTH, ground=True))
    return bytes(names) + read("test.atr")


def status_tiles(text, ground=True, page=None):
    """A status text as her screens show it."""
    page = page or HerPage()
    centered = text.center(COLUMNS)[SKIP:SKIP + WIDTH]
    return page.text(centered, WIDTH, ground=ground)


def slot_tiles(text, slot, page=None, width=WIDTH):
    """Text on one of her eight lines: her font, and where it has a space,
    her picture as it was there."""
    page = page or HerPage()
    names = blank_screen(page)
    start = SLOT_ROWS[slot] * SCREEN_COLUMNS + HER_COLUMN
    under = names[start:start + width]
    return bytes(under[index] if char == " " else page.font.get(char, HER_BLANK)
                 for index, char in enumerate(text.ljust(width)[:width]))


def help_tiles(text, page=None):
    return (page or HerPage()).text(text, WIDTH, ground=True)


def list_lines(handles, top=0):
    """The favorites' eight lines from `top`, as text."""
    entries = list(handles) + [OTHER_TEXT]
    shown = entries[top:top + SLOTS]
    return shown + [""] * (SLOTS - len(shown))


def form_lines(handle=""):
    lines = [""] * SLOTS
    for slot, text in FORM_LINES:
        lines[slot] = text
    lines[FORM_SLOT] = handle
    return lines


def sprite_page():
    """The first page: the sprite's two tiles."""
    page = bytearray(PAGE)
    for tile in (ARROW_TILE, MARK_TILE):
        page[16 * tile:16 * tile + 16] = wiki.tile_bytes(wiki.font_tile(chr(tile), SPRITE_COLOR))
    return bytes(page)


def chr_data(page=None):
    return sprite_page() + (page or HerPage()).page


def address(column, row):
    return NAMETABLE + SCREEN_COLUMNS * row + column


def byte_lines(label, values, per_line=16):
    out = []
    values = list(values)
    for at in range(0, len(values), per_line):
        out.append(("%s: " % label if at == 0 else "    ") + ".byte "
                   + ", ".join("$%02X" % value for value in values[at:at + per_line]))
    if not values:
        out.append("%s:" % label)
    return out


def lo_hi(label, values):
    return ["%s_lo: .byte %s" % (label, ", ".join("$%02X" % (value & 0xFF) for value in values)),
            "%s_hi: .byte %s" % (label, ", ".join("$%02X" % (value >> 8) for value in values))]


def screen_include(page):
    lines = ["; Generated by tools/gen_screen.py. Do not edit.", "",
             "SPLASH_STATUS_ADDR = $%04X" % address(HER_COLUMN, SPLASH_STATUS_ROW),
             "STATUS_ADDR = $%04X" % address(HER_COLUMN, STATUS_ROW),
             "HELP_ADDR = $%04X" % address(HER_COLUMN, HELP_ROW),
             "COLUMNS = %d" % COLUMNS,
             "WIDTH = %d" % WIDTH,
             "SKIP = %d" % SKIP]
    text = []
    for index, (name, words) in enumerate(STATUS_TEXT):
        if len(words) > WIDTH:
            raise ValueError("status text too wide: " + words)
        lines.append("STATUS_%s = %d" % (name, index))
        text += list(words.center(COLUMNS).encode("ascii"))
    lines += ["STATUS_WHY = %d          ; the nesp32's own words" % len(STATUS_TEXT),
              "STATUS_COUNT = %d        ; which post this is, of how many" % (len(STATUS_TEXT) + 1),
              "HER_BLANK = $%02X" % HER_BLANK,
              "SLOTS = %d" % SLOTS,
              "TEXT_SLOTS = %d" % TEXT_SLOTS,
              "PAINT_ROWS = %d         ; her lines, and the help" % PAINT_ROWS,
              "POST_COLUMNS = %d" % POST_COLUMNS,
              "POST_LINES = %d" % POST_LINES,
              "HANDLE_MAX = %d" % HANDLE_MAX,
              "FAVORITES = %d" % FAVORITES,
              "FORM_SLOT = %d" % FORM_SLOT,
              "FORM_MAX = %d" % FORM_MAX,
              "LETTER_COUNT = %d" % len(LETTERS),
              "ARROW_X = %d" % (8 * ARROW_COLUMN),
              "MARK_X = %d          ; under the form's first letter" % (8 * HER_COLUMN),
              "ARROW_TILE = $%02X" % ARROW_TILE,
              "MARK_TILE = $%02X" % MARK_TILE,
              "", '.segment "RODATA"']
    lines += byte_lines("status_text", text, per_line=COLUMNS)
    slots = [address(HER_COLUMN, row) for row in SLOT_ROWS]
    lines += lo_hi("slot", slots + [address(HER_COLUMN, HELP_ROW)])
    # Where in her.bin each line's tiles are, for what a space shows.
    lines += lo_hi("slot_off", [slot - NAMETABLE for slot in slots])
    lines += ["slot_y: .byte " + ", ".join("%d" % (8 * row - 1) for row in SLOT_ROWS)
              + "     ; a sprite on each, as a sprite's Y is written"]
    form = []
    for text in form_lines():
        form += list(text.ljust(WIDTH).encode("ascii"))
    lines += byte_lines("form_text", form, per_line=WIDTH)
    lines += byte_lines("other_text", OTHER_TEXT.encode("ascii"))
    lines.append("OTHER_LEN = %d" % len(OTHER_TEXT))
    for name, text in (("help_list", HELP_LIST), ("help_list_cart", HELP_LIST_CART),
                       ("help_form", HELP_FORM), ("help_post", HELP_POST)):
        if len(text) > WIDTH:
            raise ValueError("help too wide: " + text)
        lines += byte_lines(name, help_tiles(text, page), per_line=WIDTH)
    lines += byte_lines("letters", LETTERS.encode("ascii"))
    lines += byte_lines("her_font", page.table())
    lines += byte_lines("her_ground", page.table(ground=True))
    return "\n".join(lines) + "\n"


def write_if_changed(path, data):
    try:
        with open(path, "rb") as handle:
            if handle.read() == data:
                return
    except FileNotFoundError:
        pass
    with open(path, "wb") as handle:
        handle.write(data)


# --- the preview -------------------------------------------------------------------

# The NES's 64 colours, as a 2C02 shows them.
NES_RGB = (
    (84, 84, 84), (0, 30, 116), (8, 16, 144), (48, 0, 136), (68, 0, 100), (92, 0, 48),
    (84, 4, 0), (60, 24, 0), (32, 42, 0), (8, 58, 0), (0, 64, 0), (0, 60, 0), (0, 50, 60),
    (0, 0, 0), (0, 0, 0), (0, 0, 0),
    (152, 150, 152), (8, 76, 196), (48, 50, 236), (92, 30, 228), (136, 20, 176),
    (160, 20, 100), (152, 34, 32), (120, 60, 0), (84, 90, 0), (40, 114, 0), (8, 124, 0),
    (0, 118, 40), (0, 102, 120), (0, 0, 0), (0, 0, 0), (0, 0, 0),
    (236, 238, 236), (76, 154, 236), (120, 124, 236), (176, 98, 236), (228, 84, 236),
    (236, 88, 180), (236, 106, 100), (212, 136, 32), (160, 170, 0), (116, 196, 0),
    (76, 208, 32), (56, 204, 108), (56, 180, 204), (60, 60, 60), (0, 0, 0), (0, 0, 0),
    (236, 238, 236), (168, 204, 236), (188, 188, 236), (212, 178, 236), (236, 174, 236),
    (236, 174, 212), (236, 180, 176), (228, 196, 144), (204, 210, 120), (180, 222, 120),
    (168, 226, 144), (152, 226, 180), (160, 214, 228), (160, 162, 160), (0, 0, 0), (0, 0, 0),
)


def tile_pixel(page, tile, x, y):
    data = page[16 * tile:16 * tile + 16]
    return (data[y] >> (7 - x) & 1) | (data[8 + y] >> (7 - x) & 1) << 1


def render(names, page=None, sprites=()):
    """Her screen as rows of (r, g, b), from a 1 KB nametable, with sprites
    as (x, y, tile) from the first page."""
    page = page or HerPage()
    pal = read("test.pal")
    palettes = [pal[4 * index:4 * index + 4] for index in range(8)]
    rows = [[None] * (8 * SCREEN_COLUMNS) for _ in range(8 * SCREEN_ROWS)]
    for row in range(SCREEN_ROWS):
        for column in range(SCREEN_COLUMNS):
            tile = names[row * SCREEN_COLUMNS + column]
            attribute = names[960 + (row // 4) * 8 + column // 4]
            shift = ((row // 2) % 2) * 4 + ((column // 2) % 2) * 2
            colors = palettes[(attribute >> shift) & 3]
            for y in range(8):
                for x in range(8):
                    rows[8 * row + y][8 * column + x] = NES_RGB[
                        colors[tile_pixel(page.page, tile, x, y)] & 0x3F]
    sprites_page = sprite_page()
    for x, y, tile in sprites:
        for dy in range(8):
            for dx in range(8):
                color = tile_pixel(sprites_page, tile, dx, dy)
                if color:
                    rows[y + 1 + dy][x + dx] = NES_RGB[palettes[4][color] & 0x3F]
    return rows


def sample_post():
    """A post's eight lines as they are drawn, as the nesp32 lays one out
    (nesp32's tests/test_bsky.py)."""
    reply, repost, like = (chr(code) for code in SIGN_CODES)
    return ["@levimaaia.com",
            "Bluesky on a NES, through",
            "a nesp32 on the second",
            "controller port. Rachel",
            "Weil did this with tweets",
            "in 2016, ConnectedNES.",
            "",
            "2h  %s3 %s12 %s140" % (reply, repost, like)]


def screen_with(lines, status, help_text, page, width=WIDTH):
    names = bytearray(blank_screen(page))
    for slot, text in enumerate(lines):
        put(names, SLOT_ROWS[slot], slot_tiles(text, slot, page, width))
    put(names, STATUS_ROW, status_tiles(status, page=page))
    put(names, HELP_ROW, help_tiles(help_text, page))
    return bytes(names)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("out_dir")
    parser.add_argument("--preview", help="also write the screens as PNGs: this name with "
                                          "a post on it, and -list, -form and -splash")
    args = parser.parse_args(argv)
    page = HerPage()
    os.makedirs(args.out_dir, exist_ok=True)
    for name, data in (("chr.bin", chr_data(page)), ("splash.bin", splash(page)),
                       ("her.bin", blank_screen(page)), ("palette.bin", read("test.pal")),
                       ("screen.inc", screen_include(page).encode("ascii"))):
        write_if_changed(os.path.join(args.out_dir, name), data)
    if args.preview:
        sys.path.insert(0, os.path.join(APP, "..", "jukebox", "tools"))
        import gen_ui
        base, extension = os.path.splitext(args.preview)
        gen_ui.write_png(args.preview, render(screen_with(
            sample_post(), "POST 1 OF 25 PAGE 1/2", HELP_POST, page, POST_COLUMNS), page))
        handles = ["levimaaia.com", "andyreitano.com", "adriansdigitalbasement.com",
                   "jeriellsworth.bsky.social"]
        arrow = (8 * ARROW_COLUMN, 8 * SLOT_ROWS[0], ARROW_TILE)
        gen_ui.write_png(base + "-list" + extension, render(screen_with(
            list_lines(handles), "FAVORITES", HELP_LIST_CART, page), page, [arrow]))
        mark = (8 * (HER_COLUMN + 6), 8 * SLOT_ROWS[FORM_SLOT], MARK_TILE)
        gen_ui.write_png(base + "-form" + extension, render(screen_with(
            form_lines("bsky.a"), "", HELP_FORM, page), page, [mark]))
        names = bytearray(splash(page))
        put(names, SPLASH_STATUS_ROW, status_tiles("Press Start", ground=False, page=page))
        gen_ui.write_png(base + "-splash" + extension, render(bytes(names), page))
    return 0


if __name__ == "__main__":
    sys.exit(main())
