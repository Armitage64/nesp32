#!/usr/bin/env python3
"""Write the Bluesky ROM's tiles, its three screens, their palettes, and the
texts and tables it puts on them.

    tools/gen_screen.py build
    tools/gen_screen.py build --preview docs/screen.png

    chr.bin             8 KB: this ROM's page of tiles, then ConnectedNES's
    screen.bin          the app's nametable: the header, and nothing under it
    splash.bin          the splash: ConnectedNES's, with this ROM's words
    post.bin            a post: ConnectedNES's, with no words
    palette.bin         the app's palettes, the background's and the sprites'
    splash_palette.bin  hers
    screen.inc          where things go, and what the ROM writes there

Two of the screens are Rachel Simone Weil's, from ConnectedNES
(../connectednes): her picture, her font, her palettes, on her page of
tiles. The splash has this ROM's words in place of hers. A post is drawn
where she drew a tweet: eight lines of 24 characters on every other row,
each after one of her arrows, the handle first, six of the text, and when
it was posted last; the nesp32 lays the lines out (nesp32's
docs/PROTOCOL.md, BSKY). Her blue ground at the foot has a line of status,
and a line of what the buttons do.

Her font has each character at its ASCII code with the bits in the other
order. Her ground has its own font, colour 1 on colour 3, of which she had
only her own words' letters; this makes the rest it needs, in tiles of her
page that are empty, with the three signs a post's line of when has.

The favorites and the form are on the third screen, NESpedia's
(../../wiki/tools/gen_screen.py): its 5 x 7 font with small letters, at the
characters' ASCII codes in white and again with bit 7 set in blue, and its
header with "Bluesky" for the name. Under the header are a status line,
the middle of the screen, and a foot that says what the buttons do. One
sprite is the arrow at a favorite, or the mark under the form's letter
that Up and Down change.
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

# --- the app's screen, in tiles --------------------------------------------------

LOGO_ROW, LOGO_TEXT = wiki.LOGO_ROW, "Bluesky"
HEADER_ROWS = wiki.HEADER_ROWS
COLUMNS = 28                        # the app's lines, and every status text
ROWS = 16                           # the middle's
LEFT = (SCREEN_COLUMNS - COLUMNS) // 2
STATUS_ROW = 8
BODY_ROW = 10                       # the middle: ROWS rows from here
FOOT_ROW = 27
PAINT_ROWS = ROWS + 1               # what the ROM paints a row at a time: the middle, the foot

# In the order of the ROM's STATUS_* numbers, centered in COLUMNS. After the
# last are the nesp32's own words (STATUS_WHY) and the count of posts the
# ROM makes (STATUS_COUNT). The splash's are in her font, and the rest
# where they are shown: on the app's screen in its font, and on a post's on
# her ground.
STATUS_TEXT = (
    ("NONE", ""),
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
    ("FULL", "NO ROOM FOR MORE FAVORITES"),
    ("SPLASH_WAITING", "Looking for the nesp32..."),
    ("SPLASH_START", "Press Start"),
    ("SPLASH_OLD", "Update the nesp32"),
)
COUNT_TEXT = "POST %d OF %d"        # STATUS_COUNT, which the ROM writes,
PAGE_TEXT = " PAGE %d/%d"           # and this after it for a post of more than a page

# The favorites, by the middle's rows: a title, a handle a row, and after
# them the way to the form. The arrow is a sprite in the column before.
LIST_TITLE_ROW, LIST_TITLE = 0, "Favorites"
LIST_ROW = 2                        # the first favorite
OTHER_ROW, OTHER_TEXT = LIST_ROW + FAVORITES + 1, "Read another handle"
ARROW_COLUMN = LEFT - 1

# The form, likewise. The handle is typed a letter at a time, from these,
# in this order: Up is the next and Down the one before.
FORM_TITLE_ROW, FORM_TITLE = 0, "Read a handle"
FORM_ROW = 3                        # "@" and the handle
FORM_HELP = ((6, "Up and Down change a letter,"),
             (7, "Left and Right move along."),
             (9, "A name with no dot in it"),
             (10, "means name.bsky.social."))
LETTERS = " abcdefghijklmnopqrstuvwxyz0123456789.-"

FOOT_LIST = "A:READ  START:REMOVE"
FOOT_LIST_CART = "A:READ START:REMOVE SEL:MENU"     # on the cartridge, Select is its menu
FOOT_FORM = "A:READ  START:SAVE  B:BACK"

PALETTES = (
    (0x21, 0x10, 0x30),             # the text white, titles blue
    (0x21, 0x10, 0x30),
    (0x21, 0x10, 0x30),
    wiki.PALETTES[wiki.PALETTE_LOGO],
)
SPRITE_PALETTE = (0x21, 0x10, 0x30)     # the arrow and the mark, white
BACKDROP = wiki.BACKDROP
ARROW_TILE = ord(">")
MARK_TILE = ord("_")

# --- her screens, in her tiles -------------------------------------------------------

HER_COLUMN = 4                      # where every line of hers began
HER_BLANK = 0x00                    # her blank tile
HER_GROUND = 0x37                   # her blue ground's
HER_CTRL_PAGE = 1                   # her picture and her font are on her second page
HER_STATUS_WIDTH = 26               # to where her foot's line ended
HER_STATUS_SKIP = (COLUMNS - HER_STATUS_WIDTH) // 2     # of a status text, which is centered

# The rows her words were on, which come off both her screens: and the
# dots under "WiFi".
HER_WORD_ROWS = (10, 12, 16, 20, 21)

# The splash: these words on her rows, from her column, and her status
# line, and two lines on her ground where she had one.
SPLASH_LINES = (
    (10, "Bluesky for the nesp32"),
    (12, "after ConnectedNES by"),
    (14, "Rachel Weil (HXLNT)"),
    (16, "nobadmemories.com"),
)
SPLASH_STATUS_ROW = 20
SPLASH_FOOT_LINES = ((25, "nesp32 port:"), (26, "youtube.com/@levimaaia"))

# A post: her eight lines, each a line of the nesp32's; the status on her
# ground, and under it what the buttons do.
POST_SLOT_ROWS = (8, 10, 12, 14, 16, 18, 20, 22)
TEXT_SLOTS = len(POST_SLOT_ROWS) - 2    # the text's, between the handle and when
POST_STATUS_ROW = 25
POST_HELP_ROW, POST_HELP = 26, "L/R:post U/D:page B:back"

# Her ground's font: what any status may say (capitals, digits, and what
# the nesp32's words may have), and every character of the fixed lines.
GROUND_CHARS = (set(string.ascii_uppercase + string.digits + ":/.-'!?,")
                | set("".join(text for _, text in SPLASH_FOOT_LINES) + POST_HELP)) - {" "}

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


def her_page():
    return HerPage().page


def her_screen(page=None):
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
        put(names, row, page.text(text, HER_STATUS_WIDTH, ground=True))
    return bytes(names) + read("test.atr")


def post_screen(page=None):
    """A post's screen with no post on it: her screen, her ground's two
    lines with what the buttons do."""
    page = page or HerPage()
    names = her_screen()
    put(names, POST_STATUS_ROW, page.text("", HER_STATUS_WIDTH, ground=True))
    put(names, POST_HELP_ROW, page.text(POST_HELP, HER_STATUS_WIDTH, ground=True))
    return bytes(names) + read("test.atr")


def her_status(text, ground=False, page=None):
    """A status text as her screens show it."""
    page = page or HerPage()
    centered = text.center(COLUMNS)[HER_STATUS_SKIP:HER_STATUS_SKIP + HER_STATUS_WIDTH]
    return page.text(centered, HER_STATUS_WIDTH, ground=ground)


def post_slot(text, slot, page=None):
    """A line of a post as it is drawn in one of her eight: her font, and
    where it has a space, her picture as it was there."""
    page = page or HerPage()
    names = post_screen(page)
    start = POST_SLOT_ROWS[slot] * SCREEN_COLUMNS + HER_COLUMN
    under = names[start:start + POST_COLUMNS]
    return bytes(under[index] if char == " " else page.font.get(char, HER_BLANK)
                 for index, char in enumerate(text.ljust(POST_COLUMNS)))


# --- the app's screen --------------------------------------------------------------

def build_screen():
    screen = wiki.Screen()
    column = (SCREEN_COLUMNS - 2 * len(LOGO_TEXT)) // 2
    for index, char in enumerate(LOGO_TEXT):
        screen.picture(column + 2 * index, LOGO_ROW, wiki.big_letter(char))
    screen.picture(wiki.CREDIT_COLUMN, wiki.CREDIT_ROW, wiki.credit_pixels())
    screen.palette_rows(0, HEADER_ROWS - 1, wiki.PALETTE_LOGO)
    return screen


def palette_data():
    data = bytearray()
    for colors in PALETTES + (SPRITE_PALETTE,) * 4:
        data += bytes((BACKDROP,) + tuple(colors))
    return bytes(data)


def chr_data(screen, page=None):
    return screen.chr()[:PAGE] + (page or HerPage()).page


def line(text, alt=False):
    """A row of the middle as tiles: text, padded with spaces."""
    if len(text) > COLUMNS:
        raise ValueError("too wide: %r" % text)
    return bytes(ord(char) | (wiki.ALT if alt and char != " " else 0)
                 for char in text.ljust(COLUMNS))


def list_rows(handles):
    """The favorites as the ROM paints them, the arrow aside."""
    rows = [line("")] * ROWS
    rows[LIST_TITLE_ROW] = line(LIST_TITLE, alt=True)
    for index, handle in enumerate(handles):
        rows[LIST_ROW + index] = line("@" + handle)
    rows[OTHER_ROW] = line(OTHER_TEXT)
    return rows


def form_rows(handle=""):
    rows = [line("")] * ROWS
    rows[FORM_TITLE_ROW] = line(FORM_TITLE, alt=True)
    rows[FORM_ROW] = line("@" + handle.ljust(HANDLE_MAX))
    for row, text in FORM_HELP:
        rows[row] = line(text)
    return rows


def address(column, row):
    return NAMETABLE + SCREEN_COLUMNS * row + column


def paint_addresses():
    return ([address(LEFT, BODY_ROW + row) for row in range(ROWS)]
            + [address(LEFT, FOOT_ROW)])


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
             "STATUS_ADDR = $%04X" % address(LEFT, STATUS_ROW),
             "SPLASH_STATUS_ADDR = $%04X" % address(HER_COLUMN, SPLASH_STATUS_ROW),
             "POST_STATUS_ADDR = $%04X" % address(HER_COLUMN, POST_STATUS_ROW),
             "COLUMNS = %d" % COLUMNS,
             "HER_STATUS_WIDTH = %d" % HER_STATUS_WIDTH,
             "HER_STATUS_SKIP = %d" % HER_STATUS_SKIP]
    text = []
    for index, (name, words) in enumerate(STATUS_TEXT):
        if len(words) > (COLUMNS if not name.startswith("SPLASH") else HER_STATUS_WIDTH):
            raise ValueError("status text too wide: " + words)
        lines.append("STATUS_%s = %d" % (name, index))
        text += list(words.center(COLUMNS).encode("ascii"))
    lines += ["STATUS_WHY = %d          ; the nesp32's own words" % len(STATUS_TEXT),
              "STATUS_COUNT = %d        ; which post this is, of how many" % (len(STATUS_TEXT) + 1),
              "HER_CTRL_PAGE = %d" % HER_CTRL_PAGE,
              "HER_BLANK = $%02X" % HER_BLANK,
              "ROWS = %d" % ROWS,
              "PAINT_ROWS = %d         ; the middle's rows, and the foot" % PAINT_ROWS,
              "POST_COLUMNS = %d" % POST_COLUMNS,
              "POST_LINES = %d" % POST_LINES,
              "POST_SLOTS = %d" % len(POST_SLOT_ROWS),
              "TEXT_SLOTS = %d" % TEXT_SLOTS,
              "HANDLE_MAX = %d" % HANDLE_MAX,
              "FAVORITES = %d" % FAVORITES,
              "LIST_ROW = %d" % LIST_ROW,
              "OTHER_ROW = %d" % OTHER_ROW,
              "FORM_ROW = %d" % FORM_ROW,
              "LETTER_COUNT = %d" % len(LETTERS),
              "ARROW_X = %d" % (8 * ARROW_COLUMN),
              "MARK_X = %d          ; under the form's first letter" % (8 * (LEFT + 1)),
              "BODY_Y = %d          ; the middle's first row, in pixels" % (8 * BODY_ROW),
              "ARROW_TILE = $%02X" % ARROW_TILE,
              "MARK_TILE = $%02X" % MARK_TILE,
              "", '.segment "RODATA"']
    lines += byte_lines("status_text", text, per_line=COLUMNS)
    lines += lo_hi("paint", paint_addresses())
    slots = [address(HER_COLUMN, row) for row in POST_SLOT_ROWS]
    lines += lo_hi("slot", slots)
    # Where in post.bin each line's tiles are, for what a space shows.
    lines += ["slot_off_lo: .byte " + ", ".join("$%02X" % ((slot - NAMETABLE) & 0xFF)
                                              for slot in slots),
              "slot_off_hi: .byte " + ", ".join("$%02X" % ((slot - NAMETABLE) >> 8)
                                              for slot in slots)]
    rows = []
    for row in list_rows([]):
        rows += list(row)
    lines += byte_lines("list_text", rows, per_line=COLUMNS)
    rows = []
    for row in form_rows():
        rows += list(row)
    lines += byte_lines("form_text", rows, per_line=COLUMNS)
    for name, text in (("foot_list", FOOT_LIST), ("foot_list_cart", FOOT_LIST_CART),
                       ("foot_form", FOOT_FORM)):
        lines += byte_lines(name, line(text.center(COLUMNS)), per_line=COLUMNS)
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

# The NES's 64 colours, as a 2C02 shows them, for the previews: her
# screens have some that the jukebox's preview has no need of.
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


def render(page, names, palettes, backdrop, sprites=(), sprite_palette=SPRITE_PALETTE):
    """The screen as rows of (r, g, b), from a page of tiles and a 1 KB
    nametable, with sprites as (x, y, tile) from the same page."""
    rows = [[None] * (8 * SCREEN_COLUMNS) for _ in range(8 * SCREEN_ROWS)]
    for row in range(SCREEN_ROWS):
        for column in range(SCREEN_COLUMNS):
            tile = names[row * SCREEN_COLUMNS + column]
            attribute = names[960 + (row // 4) * 8 + column // 4]
            shift = ((row // 2) % 2) * 4 + ((column // 2) % 2) * 2
            colors = (backdrop,) + tuple(palettes[(attribute >> shift) & 3])
            for y in range(8):
                for x in range(8):
                    color = colors[tile_pixel(page, tile, x, y)]
                    rows[8 * row + y][8 * column + x] = NES_RGB[color & 0x3F]
    for x, y, tile in sprites:
        for dy in range(8):
            for dx in range(8):
                color = tile_pixel(page, tile, dx, dy)
                if color:
                    rows[y + 1 + dy][x + dx] = NES_RGB[sprite_palette[color - 1]]
    return rows


def her_palettes():
    pal = read("test.pal")
    return [tuple(pal[4 * index + 1:4 * index + 4]) for index in range(4)], pal[0]


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


def preview_post(page):
    names = bytearray(post_screen(page))
    for slot, text in enumerate(sample_post()):
        put(names, POST_SLOT_ROWS[slot], post_slot(text, slot, page))
    put(names, POST_STATUS_ROW, her_status("POST 1 OF 25 PAGE 1/2", ground=True, page=page))
    palettes, backdrop = her_palettes()
    return render(page.page, bytes(names), palettes, backdrop)


def preview_app(screen, rows, foot, status="", sprites=()):
    names = bytearray(screen.nametable())
    for row, data in enumerate(rows):
        start = SCREEN_COLUMNS * (BODY_ROW + row) + LEFT
        names[start:start + COLUMNS] = data
    for row, text in ((STATUS_ROW, status.center(COLUMNS)), (FOOT_ROW, foot.center(COLUMNS))):
        start = SCREEN_COLUMNS * row + LEFT
        names[start:start + COLUMNS] = text.encode("ascii")
    return render(screen.chr()[:PAGE], names, PALETTES, BACKDROP, sprites)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("out_dir")
    parser.add_argument("--preview", help="also write the screens as PNGs: this name with "
                                          "a post on it, and -list, -form and -splash")
    args = parser.parse_args(argv)
    page = HerPage()
    screen = build_screen()
    os.makedirs(args.out_dir, exist_ok=True)
    for name, data in (("chr.bin", chr_data(screen, page)), ("screen.bin", screen.nametable()),
                       ("splash.bin", splash(page)), ("post.bin", post_screen(page)),
                       ("palette.bin", palette_data()),
                       ("splash_palette.bin", read("test.pal")),
                       ("screen.inc", screen_include(page).encode("ascii"))):
        write_if_changed(os.path.join(args.out_dir, name), data)
    if args.preview:
        sys.path.insert(0, os.path.join(APP, "..", "jukebox", "tools"))
        import gen_ui
        base, extension = os.path.splitext(args.preview)
        gen_ui.write_png(args.preview, preview_post(page))
        handles = ["levimaaia.com", "andyreitano.com", "adriansdigitalbasement.com",
                   "jeriellsworth.bsky.social"]
        arrow = (8 * ARROW_COLUMN, 8 * (BODY_ROW + LIST_ROW), ARROW_TILE)
        gen_ui.write_png(base + "-list" + extension,
                         preview_app(screen, list_rows(handles), FOOT_LIST_CART,
                                     sprites=[arrow]))
        mark = (8 * (LEFT + 1 + 6), 8 * (BODY_ROW + FORM_ROW), MARK_TILE)
        gen_ui.write_png(base + "-form" + extension,
                         preview_app(screen, form_rows("bsky.a"), FOOT_FORM, sprites=[mark]))
        names = bytearray(splash(page))
        put(names, SPLASH_STATUS_ROW, her_status("Press Start", page=page))
        palettes, backdrop = her_palettes()
        gen_ui.write_png(base + "-splash" + extension,
                         render(page.page, bytes(names), palettes, backdrop))
    return 0


if __name__ == "__main__":
    sys.exit(main())
