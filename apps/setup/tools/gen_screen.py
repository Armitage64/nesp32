#!/usr/bin/env python3
"""Write the setup ROM's tiles, its header and the numbers its code needs.

    tools/gen_screen.py build [--preview header.png]

    chr.bin       8 KB of tiles, used for the background and the sprites
    header.bin    the top HEADER_ROWS rows of the screen, which never change
    screen.inc    layout constants and tables for nes/*.s

The header is nesp32's logo (nes/lib/logo.py), and under it what this ROM
is, in the 5 x 7 font and the logo's cyan. The logo takes two palettes, its
own and the red one for its 32, which the header's attributes
(header_attributes) split between the P and the 3. The 5 x 7 font is
nes-jukebox's, with nes-wiki's small letters.

Tiles:

    $00          blank
    $01-$1F, $80-$9F   the header's letters, and the few pictures
    $20-$7E      the font at its ASCII codes, in colour 3 (white)
    $A0-$FE      the font again in colour 1 (blue): a character with bit 7
                 set. Labels, and the keys of the keyboard.

Everything under the header is text the ROM writes: this file only says
where.
"""

import argparse
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "..", "nes", "lib"))
import logo  # noqa: E402

SCREEN_COLUMNS = 32
SCREEN_ROWS = 30

# --- layout, in tiles ---------------------------------------------------------

LOGO_ROW, LOGO_ROWS = logo.ROW, logo.ROWS
TITLE_ROW, TITLE_ROWS = logo.TITLE_ROW, 1   # under the logo, in the 5 x 7 font
TITLE_TOP = 1                       # pixels down those rows that its letters start
TITLE_TEXT = "SETUP"
TITLE_COLOR = 2                     # of the logo's palette: its cyan
HEADER_ROWS = 8                     # rows 0 to 7; the logo's palettes cover them

LEFT = 2                            # the first column anything is written in
WIDTH = 28                          # and how many there are: the safe part of a television
HEADING_ROW = 9                     # what this screen is
BODY_ROW = 11                       # its first line
MESSAGE_ROW = 26                    # one line for what is going on
HELP_ROW = 27                       # which buttons do what

# The status screen: a label and a value on every line.
VALUE_COLUMN = 12
STATUS_LABELS = ("NESP32", "FIRMWARE", "BOARD", "WI-FI", "NETWORK", "ADDRESS", "SIGNAL",
                 "BATTERY")
VALUE_WIDTH = LEFT + WIDTH - VALUE_COLUMN
# Its menu, a line under the lines; on the cartridge Quit is after them.
MENU_ROW = BODY_ROW + len(STATUS_LABELS) + 1
MENU_ITEMS = ("WI-FI SETUP", "TEST INTERFACE", "ENABLE USB DRIVE", "BLUETOOTH", "FLIP LCD")
if MENU_ROW + len(MENU_ITEMS) + 1 > MESSAGE_ROW:
    raise ValueError("the menu, with Quit, runs into the message line")

# The Bluetooth keyboard's screen: the keyboard paired and how it stands, as
# the status screen's lines are, a line in a box that shows what is typed on
# it, and a menu under that.
KBD_LABELS = ("KEYBOARD", "STATUS")
KBD_ECHO_ROW = BODY_ROW + len(KBD_LABELS) + 3     # its label two rows up, the box between
KBD_MENU_ROW = KBD_ECHO_ROW + 3
KBD_MENU_ITEMS = ("PAIR DEVICE", "FORGET DEVICE", "BACK")

# The list of networks.
LIST_ROW = 11
LIST_ROWS = 12                      # networks in view
LIST_COLUMN = LEFT + 2              # after the arrow
LIST_NAME = 22                      # characters of a name shown
LIST_LOCK = LIST_COLUMN + LIST_NAME + 1
LIST_BARS = LIST_LOCK + 2
LIST_WIDTH = LIST_BARS + 1 - LIST_COLUMN

# The keyboard: a field, and three layers of four rows of ten keys.
FIELD_ROW = 13
FIELD_WIDTH = WIDTH
KEY_COLUMN, KEY_ROW = 6, 16         # the first key; the rest are KEY_STEP apart
KEY_STEP = 2
LAYERS = (
    ("1234567890", "qwertyuiop", "asdfghjkl-", "zxcvbnm,._"),
    ("!@#$%^&*()", "QWERTYUIOP", "ASDFGHJKL+", "ZXCVBNM<>?"),
    ("\"'/:;=[\\]`", "{|}~      ", "          ", "          "),
)
KEY_ROWS, KEY_COLUMNS = 4, 10
SPACE_ROW = KEY_ROW + KEY_STEP * KEY_ROWS
SPACE_TEXT = "SPACE"
SPACE_COLUMN = (SCREEN_COLUMNS - len(SPACE_TEXT)) // 2
CURSOR_CHAR = "_"

# The link test: a label and a number on every line.
TEST_LABELS = ("REQUESTS", "GOOD", "NO REPLY", "WRONG", "", "NESP32'S REPLY TIME",
               "LAST", "SLOWEST")
TEST_VALUE_COLUMN = 14

# --- tiles ---------------------------------------------------------------------

TILE_BLANK = 0x00
PICTURE_TILES = list(range(0x01, 0x20)) + list(range(0x80, 0xA0))
ALT = 0x80                          # a font tile in the second colour

BACKDROP = 0x0F
PALETTES = (
    (0x21, 0x10, 0x30),     # 0: text white, labels and keys blue
    (0x21, 0x10, 0x30),
    (0x16, 0x00, 0x30),     # 2: the logo's 32: red, and white
    logo.PALETTE,           # 3: the rest of the logo: navy, cyan, white
)
PALETTE_RED = 2
PALETTE_LOGO = 3
SPRITE_PALETTE = (0x21, 0x10, 0x30)     # colour 3, white: the cursors



# A 5 x 7 font, one row per byte, bit 4 leftmost.
FONT = {
    " ": "00 00 00 00 00 00 00", "!": "04 04 04 04 04 00 04",
    '"': "0A 0A 0A 00 00 00 00", "#": "0A 0A 1F 0A 1F 0A 0A",
    "$": "04 0F 14 0E 05 1E 04", "%": "18 19 02 04 08 13 03",
    "&": "0C 12 14 08 15 12 0D", "'": "04 04 08 00 00 00 00",
    "(": "02 04 08 08 08 04 02", ")": "08 04 02 02 02 04 08",
    "*": "00 04 15 0E 15 04 00", "+": "00 04 04 1F 04 04 00",
    ",": "00 00 00 00 0C 04 08", "-": "00 00 00 1F 00 00 00",
    ".": "00 00 00 00 00 0C 0C", "/": "00 01 02 04 08 10 00",
    "0": "0E 11 13 15 19 11 0E", "1": "04 0C 04 04 04 04 0E",
    "2": "0E 11 01 02 04 08 1F", "3": "1F 02 04 02 01 11 0E",
    "4": "02 06 0A 12 1F 02 02", "5": "1F 10 1E 01 01 11 0E",
    "6": "06 08 10 1E 11 11 0E", "7": "1F 01 02 04 08 08 08",
    "8": "0E 11 11 0E 11 11 0E", "9": "0E 11 11 0F 01 02 0C",
    ":": "00 0C 0C 00 0C 0C 00", ";": "00 0C 0C 00 0C 04 08",
    "<": "02 04 08 10 08 04 02", "=": "00 00 1F 00 1F 00 00",
    ">": "08 04 02 01 02 04 08", "?": "0E 11 01 02 04 00 04",
    "@": "0E 11 01 0D 15 15 0E", "A": "0E 11 11 1F 11 11 11",
    "B": "1E 11 11 1E 11 11 1E", "C": "0E 11 10 10 10 11 0E",
    "D": "1E 11 11 11 11 11 1E", "E": "1F 10 10 1E 10 10 1F",
    "F": "1F 10 10 1E 10 10 10", "G": "0E 11 10 17 11 11 0F",
    "H": "11 11 11 1F 11 11 11", "I": "0E 04 04 04 04 04 0E",
    "J": "07 02 02 02 02 12 0C", "K": "11 12 14 18 14 12 11",
    "L": "10 10 10 10 10 10 1F", "M": "11 1B 15 15 11 11 11",
    "N": "11 19 15 13 11 11 11", "O": "0E 11 11 11 11 11 0E",
    "P": "1E 11 11 1E 10 10 10", "Q": "0E 11 11 11 15 12 0D",
    "R": "1E 11 11 1E 14 12 11", "S": "0F 10 10 0E 01 01 1E",
    "T": "1F 04 04 04 04 04 04", "U": "11 11 11 11 11 11 0E",
    "V": "11 11 11 11 11 0A 04", "W": "11 11 11 15 15 1B 11",
    "X": "11 11 0A 04 0A 11 11", "Y": "11 11 0A 04 04 04 04",
    "Z": "1F 01 02 04 08 10 1F", "[": "0E 08 08 08 08 08 0E",
    "\\": "00 10 08 04 02 01 00", "]": "0E 02 02 02 02 02 0E",
    "^": "04 0A 11 00 00 00 00", "_": "00 00 00 00 00 00 1F",
    "`": "08 04 02 00 00 00 00", "a": "00 00 0E 01 0F 11 0F",
    "b": "10 10 16 19 11 11 1E", "c": "00 00 0E 10 10 11 0E",
    "d": "01 01 0D 13 11 11 0F", "e": "00 00 0E 11 1F 10 0E",
    "f": "06 09 08 1C 08 08 08", "g": "00 00 0F 11 0F 01 0E",
    "h": "10 10 16 19 11 11 11", "i": "04 00 0C 04 04 04 0E",
    "j": "02 00 06 02 02 12 0C", "k": "10 10 12 14 18 14 12",
    "l": "0C 04 04 04 04 04 0E", "m": "00 00 1A 15 15 11 11",
    "n": "00 00 16 19 11 11 11", "o": "00 00 0E 11 11 11 0E",
    "p": "00 00 1E 11 1E 10 10", "q": "00 00 0D 13 0F 01 01",
    "r": "00 00 16 19 10 10 10", "s": "00 00 0E 10 0E 01 1E",
    "t": "08 08 1C 08 08 09 06", "u": "00 00 11 11 11 13 0D",
    "v": "00 00 11 11 11 0A 04", "w": "00 00 11 11 15 15 0A",
    "x": "00 00 11 0A 04 0A 11", "y": "00 00 11 11 0F 01 0E",
    "z": "00 00 1F 02 04 08 1F", "{": "02 04 04 08 04 04 02",
    "|": "04 04 04 04 04 04 04", "}": "08 04 04 02 04 04 08",
    "~": "00 00 08 15 02 00 00",
}

# The few pictures, 8 rows of 8 pixels, '#' lit.
PICTURES = {
    "LOCK": ("........", "..###...", ".#...#..", ".#...#..", "#######.", "###.###.",
             "###.###.", "#######."),
    "ARROW": ("........", ".#......", ".###....", ".#####..", ".###....", ".#......",
              "........", "........"),
    "UNDER": ("#######.", "#######.", "........", "........", "........", "........",
              "........", "........"),
}


# A box round a line of text, one pixel thick, as NESpedia's search box: its
# sides in the columns either side of the line, its top and bottom in the
# rows above and below.
BOX_X_LEFT, BOX_X_RIGHT = 5, 2          # pixels into the side columns
BOX_Y_TOP, BOX_Y_BOTTOM = 4, 2          # pixels into the rows above and below


def box_pictures():
    """The box's tiles: corners, edges and sides."""
    def tile(lit):
        return tuple("".join("#" if (x, y) in lit else "." for x in range(8)) for y in range(8))
    top = {(x, BOX_Y_TOP) for x in range(8)}
    bottom = {(x, BOX_Y_BOTTOM) for x in range(8)}
    left = {(BOX_X_LEFT, y) for y in range(8)}
    right = {(BOX_X_RIGHT, y) for y in range(8)}
    return {
        "BOX_TL": tile({p for p in top | left if p[0] >= BOX_X_LEFT and p[1] >= BOX_Y_TOP}),
        "BOX_T": tile(top),
        "BOX_TR": tile({p for p in top | right if p[0] <= BOX_X_RIGHT and p[1] >= BOX_Y_TOP}),
        "BOX_L": tile(left),
        "BOX_R": tile(right),
        "BOX_BL": tile({p for p in bottom | left
                        if p[0] >= BOX_X_LEFT and p[1] <= BOX_Y_BOTTOM}),
        "BOX_B": tile(bottom),
        "BOX_BR": tile({p for p in bottom | right
                        if p[0] <= BOX_X_RIGHT and p[1] <= BOX_Y_BOTTOM}),
    }


def bars_picture(level):
    """Signal strength, 1 to 4: bars that get taller, the first `level` lit."""
    rows = [["."] * 8 for _ in range(8)]
    for bar in range(level):
        for y in range(6 - 2 * bar, 8):
            rows[y][2 * bar] = "#"
    return tuple("".join(row) for row in rows)




def font_text(text, width, color):
    """Text in the 5 x 7 font and one color, centered to the pixel in a
    strip `width` pixels wide and TITLE_ROWS tiles high. Text set in whole
    tiles can be half a tile off the name's middle."""
    pixels = [[0] * width for _ in range(8 * TITLE_ROWS)]
    left = (width - (8 * len(text) - 3)) // 2
    for index, char in enumerate(text):
        for y, row in enumerate(glyph(char)):
            for x, on in enumerate(row):
                if on:
                    pixels[TITLE_TOP + y][left + 8 * index + x] = color
    return pixels


def glyph(char):
    """A character as 7 rows of 5 pixels (0 or 1)."""
    rows = [int(value, 16) for value in FONT.get(char, FONT["?"]).split()]
    return [[(row >> (4 - x)) & 1 for x in range(5)] for row in rows]


def empty_tile():
    return [[0] * 8 for _ in range(8)]


def font_tile(char, color=3):
    tile = empty_tile()
    for y, row in enumerate(glyph(char)):
        for x, on in enumerate(row):
            if on:
                tile[y][x + 1] = color
    return tile


def picture_tile(rows, color=3):
    return [[color if char == "#" else 0 for char in row] for row in rows]


def big_letter(char):
    """A letter at twice the size, 16 x 16 pixels: pale blue over a deeper
    one, with a dark blue shadow below and to the right."""
    pixels = [[0] * 16 for _ in range(16)]
    lit = set()
    for y, row in enumerate(glyph(char)):
        for x, on in enumerate(row):
            if on:
                for dy in (0, 1):
                    for dx in (0, 1):
                        lit.add((3 + 2 * x + dx, 1 + 2 * y + dy))
    for x, y in lit:
        if (x + 1, y + 1) not in lit and x + 1 < 16 and y + 1 < 16:
            pixels[y + 1][x + 1] = 1
    for x, y in lit:
        pixels[y][x] = 3 if y < 8 else 2
    return pixels


def cut_tiles(pixels):
    """Split a picture into rows of 8 x 8 tiles."""
    return [[[row[x:x + 8] for row in pixels[y:y + 8]] for x in range(0, len(pixels[0]), 8)]
            for y in range(0, len(pixels), 8)]


def tile_bytes(tile):
    planes = bytearray(16)
    for y, row in enumerate(tile):
        for x, color in enumerate(row):
            planes[y] |= (color & 1) << (7 - x)
            planes[8 + y] |= (color >> 1) << (7 - x)
    return bytes(planes)


class Screen:
    """The tile set and the header being laid out."""

    def __init__(self):
        self.tiles = {TILE_BLANK: tile_bytes(empty_tile())}
        for code in range(0x20, 0x7F):
            self.tiles[code] = tile_bytes(font_tile(chr(code)))
            self.tiles[code | ALT] = tile_bytes(font_tile(chr(code), 1))
        self.shared = {}                # tile bytes -> index, for the pictures
        self.free = list(PICTURE_TILES)
        self.names = bytearray([TILE_BLANK]) * (SCREEN_COLUMNS * SCREEN_ROWS)
        self.named = {}

    def add(self, data):
        if data not in self.shared:
            if not self.free:
                raise ValueError("out of tiles for the pictures")
            self.shared[data] = self.free.pop(0)
            self.tiles[self.shared[data]] = data
        return self.shared[data]

    def put(self, column, row, tile):
        self.names[row * SCREEN_COLUMNS + column] = tile

    def picture(self, column, row, pixels):
        for dy, tiles in enumerate(cut_tiles(pixels)):
            for dx, tile in enumerate(tiles):
                data = tile_bytes(tile)
                if data != self.tiles[TILE_BLANK]:
                    self.put(column + dx, row + dy, self.add(data))

    def chr(self):
        data = bytearray(0x2000)
        for index, tile in self.tiles.items():
            data[index * 16:index * 16 + 16] = tile
        return bytes(data)


def build_screen(title=TITLE_TEXT):
    """The tiles and the header, with a word under the name: this ROM's, or
    the cartridge menu's (nes/cart/gen_cart.py)."""
    screen = Screen()
    screen.picture(0, LOGO_ROW, logo.pixels(8 * SCREEN_COLUMNS))
    screen.picture(0, TITLE_ROW, font_text(title, 8 * SCREEN_COLUMNS, TITLE_COLOR))
    for name, rows in PICTURES.items():
        screen.named[name] = screen.add(tile_bytes(picture_tile(rows)))
    for name, rows in box_pictures().items():
        screen.named[name] = screen.add(tile_bytes(picture_tile(rows, 1)))
    for level in range(1, 5):
        screen.named["BARS%d" % level] = screen.add(tile_bytes(picture_tile(bars_picture(level))))
    return screen


def header_attributes():
    """The header's attribute bytes: the logo's palette, and the red one
    where the logo's 32 is."""
    if HEADER_ROWS % 4:
        raise ValueError("the header must end where a row of attributes does")
    data = bytearray()
    for top in range(0, HEADER_ROWS, 4):
        for left in range(0, SCREEN_COLUMNS, 4):
            byte = 0
            for quarter, (dy, dx) in enumerate(((0, 0), (0, 2), (2, 0), (2, 2))):
                red = logo.is_red(top + dy, left + dx)
                byte |= (PALETTE_RED if red else PALETTE_LOGO) << (2 * quarter)
            data.append(byte)
    return bytes(data)


def palette_of(row, column):
    """The palette a tile of the screen is drawn in."""
    if row >= HEADER_ROWS:
        return 0
    byte = header_attributes()[8 * (row // 4) + column // 4]
    return byte >> (2 * (2 * (row % 4 // 2) + column % 4 // 2)) & 3


def address(row, column):
    return 0x2000 + SCREEN_COLUMNS * row + column


def key_x(index):
    return 8 * (KEY_COLUMN + KEY_STEP * index)


def include(screen):
    lines = ["; Generated by apps/setup/tools/gen_screen.py. Do not edit.", ""]

    def constant(name, value, note=""):
        lines.append("%-18s = %-6s%s" % (name, value, ("  ; " + note) if note else ""))

    constant("ALT", "$%02X" % ALT, "a character in the second colour")
    constant("HEADER_ROWS", HEADER_ROWS)
    constant("LEFT", LEFT)
    constant("WIDTH", WIDTH)
    constant("HEADING_ROW", HEADING_ROW)
    constant("BODY_ROW", BODY_ROW)
    constant("MESSAGE_ROW", MESSAGE_ROW)
    constant("HELP_ROW", HELP_ROW)
    constant("VALUE_COLUMN", VALUE_COLUMN)
    constant("VALUE_WIDTH", VALUE_WIDTH)
    constant("MENU_ROW", MENU_ROW)
    constant("KBD_ECHO_ROW", KBD_ECHO_ROW)
    constant("KBD_MENU_ROW", KBD_MENU_ROW)
    constant("LIST_ROW", LIST_ROW)
    constant("LIST_ROWS", LIST_ROWS, "networks in view")
    constant("LIST_COLUMN", LIST_COLUMN)
    constant("LIST_NAME", LIST_NAME, "characters of a name shown")
    constant("LIST_WIDTH", LIST_WIDTH)
    constant("LIST_ARROW_X", 8 * LEFT)
    constant("FIELD_ROW", FIELD_ROW)
    constant("FIELD_WIDTH", FIELD_WIDTH)
    constant("KEY_ROW", KEY_ROW)
    constant("KEY_COLUMN", KEY_COLUMN)
    constant("KEY_ROWS", KEY_ROWS, "rows of keys; the space bar is the row after")
    constant("KEY_COLUMNS", KEY_COLUMNS)
    constant("KEY_STEP", KEY_STEP)
    constant("KEY_LAYERS", len(LAYERS))
    constant("KEY_X", key_x(0), "the first key's place, in pixels")
    constant("KEY_Y", 8 * KEY_ROW)
    constant("SPACE_ROW", SPACE_ROW)
    constant("SPACE_COLUMN", SPACE_COLUMN)
    constant("SPACE_X", 8 * SPACE_COLUMN + 8 * (len(SPACE_TEXT) // 2))
    constant("CURSOR_CHAR", "'%s'" % CURSOR_CHAR)
    constant("TEST_VALUE_COLUMN", TEST_VALUE_COLUMN)
    for name, tile in sorted(screen.named.items()):
        constant("TILE_" + name, "$%02X" % tile)
    lines += ["", "; The keys, a layer after another, a row after another."]
    for layer in LAYERS:
        if len(layer) != KEY_ROWS or any(len(row) != KEY_COLUMNS for row in layer):
            raise ValueError("a layer is %d rows of %d keys" % (KEY_ROWS, KEY_COLUMNS))
    lines.append("key_chars:")
    for layer in LAYERS:
        for row in layer:
            lines.append("    .byte " + ", ".join("$%02X" % ord(char) for char in row))
    lines += ["", "palette_data:"]
    for palette in PALETTES + (SPRITE_PALETTE,) * 4:
        lines.append("    .byte " + ", ".join("$%02X" % color for color in (BACKDROP,) + palette))
    lines += ["", "; The header's attributes; the rest are 0."]
    lines.append("header_attributes:")
    attributes = header_attributes()
    for start in range(0, len(attributes), 8):
        lines.append("    .byte " + ", ".join("$%02X" % byte for byte in attributes[start:start + 8]))
    return "\n".join(lines) + "\n"


# --- preview -------------------------------------------------------------------

# The few NES colors the screen uses, as RGB.
NES_RGB = {
    0x0F: (0, 0, 0), 0x00: (84, 84, 84), 0x10: (152, 150, 152), 0x30: (236, 238, 236),
    0x01: (0, 30, 116), 0x16: (152, 34, 32), 0x21: (76, 154, 236), 0x2C: (56, 180, 204),
}


def render(chr_data, names, header_rows=HEADER_ROWS, sprites=()):
    """A screen as rows of (r, g, b), from CHR data and 960 tile numbers.
    sprites are (x, y, tile), drawn in the sprite palette."""
    rows = [[None] * (8 * SCREEN_COLUMNS) for _ in range(8 * SCREEN_ROWS)]
    for row in range(SCREEN_ROWS):
        for column in range(SCREEN_COLUMNS):
            colors = (BACKDROP,) + tuple(PALETTES[palette_of(row, column)
                                                   if row < header_rows else 0])
            planes = chr_data[names[row * SCREEN_COLUMNS + column] * 16:][:16]
            for y in range(8):
                for x in range(8):
                    index = ((planes[y] >> (7 - x)) & 1) | (((planes[8 + y] >> (7 - x)) & 1) << 1)
                    rows[8 * row + y][8 * column + x] = NES_RGB.get(colors[index], (255, 0, 255))
    for left, top, tile in sprites:
        planes = chr_data[tile * 16:][:16]
        for y in range(8):
            for x in range(8):
                index = ((planes[y] >> (7 - x)) & 1) | (((planes[8 + y] >> (7 - x)) & 1) << 1)
                if index and 0 <= top + y < 8 * SCREEN_ROWS and 0 <= left + x < 8 * SCREEN_COLUMNS:
                    rows[top + y][left + x] = NES_RGB[SPRITE_PALETTE[index - 1]]
    return rows


def write_png(path, rows, scale=2):
    """A minimal PNG writer, so the preview needs no imaging library."""
    width, height = len(rows[0]) * scale, len(rows) * scale
    raw = bytearray()
    for row in rows:
        line = b"\x00" + b"".join(bytes(pixel) * scale for pixel in row)
        raw += line * scale

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    with open(path, "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
                     + chunk(b"IEND", b""))


def write_if_changed(path, data):
    try:
        with open(path, "rb") as handle:
            if handle.read() == data:
                return
    except FileNotFoundError:
        pass
    with open(path, "wb") as handle:
        handle.write(data)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("out_dir", help="directory for chr.bin, header.bin and screen.inc")
    parser.add_argument("--preview", help="also write the header as a PNG")
    args = parser.parse_args(argv)
    screen = build_screen()
    os.makedirs(args.out_dir, exist_ok=True)
    write_if_changed(os.path.join(args.out_dir, "chr.bin"), screen.chr())
    write_if_changed(os.path.join(args.out_dir, "header.bin"),
                     bytes(screen.names[:HEADER_ROWS * SCREEN_COLUMNS]))
    write_if_changed(os.path.join(args.out_dir, "screen.inc"), include(screen).encode("ascii"))
    if args.preview:
        write_png(args.preview, render(screen.chr(), screen.names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
