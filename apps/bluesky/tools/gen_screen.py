#!/usr/bin/env python3
"""Write the Bluesky ROM's tiles, its two screens, their palettes, and the
texts it puts on them.

    tools/gen_screen.py build
    tools/gen_screen.py build --preview docs/screen.png

    chr.bin             8 KB: this ROM's page of tiles, then ConnectedNES's
    screen.bin          the app's nametable: the header, and nothing under it
    splash.bin          the splash's: ConnectedNES's, with this ROM's words
    palette.bin         the app's palettes, the background's and the sprites'
    splash_palette.bin  the splash's, which are ConnectedNES's
    screen.inc          where things go, and what the ROM writes there

There are two screens. The splash is Rachel Simone Weil's, from
ConnectedNES (../connectednes): her picture, her font, her palettes, on her
page of tiles, with this ROM's words in place of hers. The status line on
it says how it stands with the nesp32, and Start leaves it.

The app's screen is NESpedia's (../../wiki/tools/gen_screen.py): its 5 x 7
font with small letters, at the characters' ASCII codes in white and again
with bit 7 set in blue, and its header with "Bluesky" for the name. Under
the header are a status line, the middle of the screen, which is the
favorites, the form a handle is typed in, or a post, and a foot that says
what the buttons do. A post is the nesp32's lines as they come (nesp32's
docs/PROTOCOL.md, BSKY): its author's name in blue, and $1C to $1E the
signs for replies, reposts and likes, which this page has besides the
font.

One sprite is the arrow at a favorite, or the mark under the form's
letter that Up and Down change. It uses this page's tiles too.
"""

import argparse
import importlib.util
import os
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

# --- the app's screen, in tiles --------------------------------------------------

LOGO_ROW, LOGO_TEXT = wiki.LOGO_ROW, "Bluesky"
HEADER_ROWS = wiki.HEADER_ROWS
COLUMNS = proto.NESP_BSKY_COLUMNS   # a line of a post
POST_ROWS = proto.NESP_BSKY_ROWS
HANDLE_MAX = proto.NESP_BSKY_HANDLE_MAX
FAVORITES = proto.NESP_BSKY_FAVORITES
LEFT = (SCREEN_COLUMNS - COLUMNS) // 2
STATUS_ROW = 8
BODY_ROW = 10                       # the middle: POST_ROWS rows from here
FOOT_ROW = 27
PAINT_ROWS = POST_ROWS + 1          # what the ROM paints a row at a time: the middle, the foot

# In the order of the ROM's STATUS_* numbers. After the last are the
# nesp32's own words (STATUS_WHY) and the count of posts the ROM makes
# (STATUS_COUNT).
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
    ("REMOVE", "SELECT AGAIN TO REMOVE"),
    ("REMOVED", "REMOVED FROM FAVORITES"),
    ("SAVED", "SAVED TO FAVORITES"),
    ("FULL", "NO ROOM FOR MORE FAVORITES"),
)
COUNT_TEXT = "POST %d OF %d"        # STATUS_COUNT, which the ROM writes

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

FOOT_LIST = "A:READ  SELECT:REMOVE"
FOOT_FORM = "A:READ  START:SAVE  B:BACK"
FOOT_POST = "</>:POST  START:SAVE  B:BACK"

# The signs a post's last line has, as the nesp32 numbers them.
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
SIGN_COLOR = 3

PALETTES = (
    (0x21, 0x10, 0x30),             # 0: the text white, a post's author and titles blue
    (0x21, 0x10, 0x30),
    (0x21, 0x10, 0x30),
    wiki.PALETTES[wiki.PALETTE_LOGO],
)
SPRITE_PALETTE = (0x21, 0x10, 0x30)     # the arrow and the mark, white
BACKDROP = wiki.BACKDROP
ARROW_TILE = ord(">")
MARK_TILE = ord("_")

# --- the splash, in ConnectedNES's tiles -------------------------------------------

# Rows of her screen that had her words: theirs are taken off, and these
# put on, from the column hers began at. A row with an arrow before it had
# one in hers.
SPLASH_COLUMN = 4
SPLASH_LINES = (
    (10, "Bluesky for the nesp32"),
    (12, "after ConnectedNES by"),
    (14, "Rachel Weil (HXLNT)"),
    (16, "nobadmemories.com"),
)
SPLASH_STATUS_ROW = 20
SPLASH_STATUS_WIDTH = SCREEN_COLUMNS - SPLASH_COLUMN
# In the order of the ROM's SPLASH_* numbers.
SPLASH_STATUS = (
    ("WAITING", "Looking for the nesp32..."),
    ("START", "Press Start"),
    ("OLD", "Update the nesp32"),
)
SPLASH_FOOT_COLUMN = 4              # after her heart
SPLASH_FOOT_END = 30                # where her line ended
# Her line had room for 26 characters, so this ROM's is two, the second
# under the first on her ground.
SPLASH_FOOT_LINES = ((25, "nesp32 port:"), (26, "youtube.com/@levimaaia"))
SPLASH_FOOT = "".join(text for _, text in SPLASH_FOOT_LINES)    # every character of them
SPLASH_BLANK = 0x00                 # her blank tile, under the words
# Her foot is on her blue ground, in letters of colour 1 on colour 3 in
# place of colour 0: a font of their own, which she had only the letters of
# her own words in. The ground between words is this tile.
SPLASH_GROUND = 0x37
SPLASH_CTRL_PAGE = 1                # her words and picture are on her second page


def read(name):
    with open(os.path.join(CONNECTEDNES, name), "rb") as handle:
        return handle.read()


def her_tile(char):
    """Her font has a character at its ASCII code with the bits reversed."""
    if char == " ":
        return SPLASH_BLANK
    code = ord(char)
    return int("{:08b}".format(code)[::-1], 2)


def her_text(text, width=None):
    tiles = bytes(her_tile(char) for char in text)
    return tiles if width is None else tiles.ljust(width, bytes((SPLASH_BLANK,)))


def her_names():
    return b"".join(read("loadingscreen%d.nam" % number) for number in range(1, 5))


def on_ground(tile):
    """One of her font's tiles as her foot's letters are: what is colour 0
    in it, colour 3."""
    out = bytearray(tile)
    for y in range(8):
        out[y] |= ~tile[y] & ~tile[8 + y] & 0xFF
        out[8 + y] |= ~tile[y] & ~tile[8 + y] & 0xFF
    return bytes(out)


def foot_font():
    """Her page, with a letter on her ground for each character of this
    ROM's foot, in tiles that are empty and that her screen does not use;
    and which tile each character has."""
    page = bytearray(read("ascii.chr")[PAGE:2 * PAGE])
    used = set(her_names())
    free = [tile for tile in range(256)
            if not any(page[16 * tile:16 * tile + 16]) and tile not in used]
    tiles = {" ": SPLASH_GROUND}
    for char in sorted(set(SPLASH_FOOT) - {" "}):
        if not free:
            raise ValueError("ConnectedNES's page has no room for the foot's letters")
        tile = free.pop(0)
        plain = her_tile(char)
        page[16 * tile:16 * tile + 16] = on_ground(page[16 * plain:16 * plain + 16])
        tiles[char] = tile
    return bytes(page), tiles


def her_page():
    return foot_font()[0]


def splash():
    """Her nametable and attributes, with this ROM's words."""
    names = bytearray(her_names()[:SCREEN_COLUMNS * SCREEN_ROWS])
    # Her words come off: every tile after the arrows' column on the rows
    # that had them, and the dots under "WiFi".
    for row in (10, 12, 16, SPLASH_STATUS_ROW, SPLASH_STATUS_ROW + 1):
        start = row * SCREEN_COLUMNS
        names[start + SPLASH_COLUMN:start + SCREEN_COLUMNS] = bytes(
            (SPLASH_BLANK,)) * (SCREEN_COLUMNS - SPLASH_COLUMN)
    for row, text in SPLASH_LINES:
        start = row * SCREEN_COLUMNS + SPLASH_COLUMN
        names[start:start + len(text)] = her_text(text)
    _, tiles = foot_font()
    for row, words in SPLASH_FOOT_LINES:
        foot = row * SCREEN_COLUMNS
        text = words.ljust(SPLASH_FOOT_END - SPLASH_FOOT_COLUMN)
        if len(text) > SPLASH_FOOT_END - SPLASH_FOOT_COLUMN:
            raise ValueError("too wide for her foot: %r" % words)
        names[foot + SPLASH_FOOT_COLUMN:foot + SPLASH_FOOT_END] = bytes(tiles[char]
                                                                       for char in text)
    return bytes(names) + read("test.atr")


def check_her_font():
    """Every character this ROM writes in her font has a tile there."""
    page = her_page()
    texts = [text for _, text in SPLASH_LINES] + [text for _, text in SPLASH_STATUS]
    for char in set("".join(texts) + SPLASH_FOOT) - {" "}:
        tile = her_tile(char)
        if not any(page[16 * tile:16 * tile + 16]):
            raise ValueError("ConnectedNES's font has no %r" % char)


# --- the app's screen --------------------------------------------------------------

def tile_from(drawing):
    rows = [line.strip() for line in drawing.strip().splitlines()]
    return [[SIGN_COLOR if char == "#" else 0 for char in row] for row in rows]


def build_screen():
    screen = wiki.Screen()
    # The header's pictures may not take the signs' tiles.
    screen.free = [tile for tile in screen.free if tile not in SIGNS]
    for number, drawing in SIGNS.items():
        screen.tiles[number] = wiki.tile_bytes(tile_from(drawing))
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


def chr_data(screen):
    return screen.chr()[:PAGE] + her_page()


def line(text, alt=False):
    """A row of the middle as tiles: text, padded with spaces."""
    if len(text) > COLUMNS:
        raise ValueError("too wide: %r" % text)
    return bytes(ord(char) | (wiki.ALT if alt and char != " " else 0)
                 for char in text.ljust(COLUMNS))


def list_rows(handles):
    """The favorites as the ROM paints them, the arrow aside."""
    rows = [line("")] * POST_ROWS
    rows[LIST_TITLE_ROW] = line(LIST_TITLE, alt=True)
    for index, handle in enumerate(handles):
        rows[LIST_ROW + index] = line("@" + handle)
    rows[OTHER_ROW] = line(OTHER_TEXT)
    return rows


def form_rows(handle=""):
    rows = [line("")] * POST_ROWS
    rows[FORM_TITLE_ROW] = line(FORM_TITLE, alt=True)
    rows[FORM_ROW] = line("@" + handle.ljust(HANDLE_MAX))
    for row, text in FORM_HELP:
        rows[row] = line(text)
    return rows


def paint_addresses():
    return ([NAMETABLE + SCREEN_COLUMNS * (BODY_ROW + row) + LEFT for row in range(POST_ROWS)]
            + [NAMETABLE + SCREEN_COLUMNS * FOOT_ROW + LEFT])


def byte_lines(label, values, per_line=16):
    out = []
    values = list(values)
    for at in range(0, len(values), per_line):
        out.append(("%s: " % label if at == 0 else "    ") + ".byte "
                   + ", ".join("$%02X" % value for value in values[at:at + per_line]))
    if not values:
        out.append("%s:" % label)
    return out


def screen_include():
    lines = ["; Generated by tools/gen_screen.py. Do not edit.", "",
             "STATUS_ADDR = $%04X" % (NAMETABLE + SCREEN_COLUMNS * STATUS_ROW + LEFT),
             "STATUS_WIDTH = %d" % COLUMNS]
    text = []
    for index, (name, words) in enumerate(STATUS_TEXT):
        if len(words) > COLUMNS:
            raise ValueError("status text too wide: " + words)
        lines.append("STATUS_%s = %d" % (name, index))
        text += list(words.center(COLUMNS).encode("ascii"))
    lines += ["STATUS_WHY = %d          ; the nesp32's own words" % len(STATUS_TEXT),
              "STATUS_COUNT = %d        ; which post this is, of how many" % (len(STATUS_TEXT) + 1),
              "SPLASH_STATUS_ADDR = $%04X" % (NAMETABLE + SCREEN_COLUMNS * SPLASH_STATUS_ROW
                                              + SPLASH_COLUMN)]
    if SPLASH_STATUS_WIDTH != COLUMNS:
        raise ValueError("the NMI draws both status lines the one width")
    for index, (name, _) in enumerate(SPLASH_STATUS):
        lines.append("SPLASH_%s = %d" % (name, index))
    lines += ["SPLASH_CTRL_PAGE = %d" % SPLASH_CTRL_PAGE,
              "COLUMNS = %d" % COLUMNS,
              "POST_ROWS = %d" % POST_ROWS,
              "PAINT_ROWS = %d         ; the middle's rows, and the foot" % PAINT_ROWS,
              "HANDLE_MAX = %d" % HANDLE_MAX,
              "FAVORITES = %d" % FAVORITES,
              "LIST_ROW = %d" % LIST_ROW,
              "LIST_TITLE_ROW = %d" % LIST_TITLE_ROW,
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
    splash_text = []
    for _, words in SPLASH_STATUS:
        splash_text += list(her_text(words, SPLASH_STATUS_WIDTH))
    lines += byte_lines("splash_text", splash_text, per_line=COLUMNS)
    places = paint_addresses()
    lines += ["paint_lo: .byte " + ", ".join("$%02X" % (place & 0xFF) for place in places),
              "paint_hi: .byte " + ", ".join("$%02X" % (place >> 8) for place in places)]
    title = []
    for row in list_rows([]):
        title += list(row)
    lines += byte_lines("list_text", title, per_line=COLUMNS)
    form = []
    for row in form_rows():
        form += list(row)
    lines += byte_lines("form_text", form, per_line=COLUMNS)
    for name, text in (("foot_list", FOOT_LIST), ("foot_form", FOOT_FORM),
                       ("foot_post", FOOT_POST)):
        lines += byte_lines(name, line(text.center(COLUMNS)), per_line=COLUMNS)
    lines += byte_lines("letters", LETTERS.encode("ascii"))
    lines += byte_lines("count_text", line(COUNT_TEXT.split("%")[0]), per_line=COLUMNS)
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

# The NES's 64 colours, as a 2C02 shows them, for the previews: her splash
# has some that the jukebox's preview has no need of.
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


def sample_post():
    """A post as the nesp32 lays one out (nesp32's tests/test_bsky.py)."""
    reply, repost, like = (chr(proto.NESP_BSKY_REPLY), chr(proto.NESP_BSKY_REPOST),
                           chr(proto.NESP_BSKY_LIKE))
    counts = "%s3 %s12 %s140" % (reply, repost, like)
    texts = ["@levimaaia.com", "", "Bluesky on a NES, through a", "nesp32 on the second",
             "controller port. Rachel Weil", "did this with tweets in 2016", "(ConnectedNES).",
             "", "Favorites are kept on the", "nesp32 over power-off.", "", "", "", "",
             "2h".ljust(COLUMNS - len(counts)) + counts]
    return [line("Levi", alt=True)] + [bytes(ord(char) for char in text.ljust(COLUMNS))
                                       for text in texts]


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
                                          "the post on it, and -list, -form and -splash")
    args = parser.parse_args(argv)
    check_her_font()
    screen = build_screen()
    os.makedirs(args.out_dir, exist_ok=True)
    for name, data in (("chr.bin", chr_data(screen)), ("screen.bin", screen.nametable()),
                       ("splash.bin", splash()), ("palette.bin", palette_data()),
                       ("splash_palette.bin", read("test.pal")),
                       ("screen.inc", screen_include().encode("ascii"))):
        write_if_changed(os.path.join(args.out_dir, name), data)
    if args.preview:
        sys.path.insert(0, os.path.join(APP, "..", "jukebox", "tools"))
        import gen_ui
        base, extension = os.path.splitext(args.preview)
        post = sample_post()
        gen_ui.write_png(args.preview, preview_app(screen, post, FOOT_POST, "POST 1 OF 25"))
        handles = ["levimaaia.com", "andyreitano.com", "adriansdigitalbasement.com",
                   "jeriellsworth.bsky.social"]
        arrow = (8 * ARROW_COLUMN, 8 * (BODY_ROW + LIST_ROW), ARROW_TILE)
        gen_ui.write_png(base + "-list" + extension,
                         preview_app(screen, list_rows(handles), FOOT_LIST, sprites=[arrow]))
        mark = (8 * (LEFT + 1 + 6), 8 * (BODY_ROW + FORM_ROW), MARK_TILE)
        gen_ui.write_png(base + "-form" + extension,
                         preview_app(screen, form_rows("bsky.a"), FOOT_FORM, sprites=[mark]))
        names = bytearray(splash())
        start = SCREEN_COLUMNS * SPLASH_STATUS_ROW + SPLASH_COLUMN
        names[start:start + SPLASH_STATUS_WIDTH] = her_text(SPLASH_STATUS[1][1],
                                                            SPLASH_STATUS_WIDTH)
        pal = read("test.pal")
        palettes = [tuple(pal[4 * index + 1:4 * index + 4]) for index in range(4)]
        gen_ui.write_png(base + "-splash" + extension,
                         render(her_page(), bytes(names), palettes, pal[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
