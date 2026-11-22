#!/usr/bin/env python3
"""Write the Gallery's tiles, its search screen and the numbers the ROM needs.

    tools/gen_screen.py build [--preview search.png] [--info info.png]

    chr.bin       4 KB of tiles, the first pattern table: the ROM copies
                  them to the cartridge's CHR RAM, where a picture's own
                  take their place while it is shown
    screen.bin    nametable 1: the header and the search screen
    screen.inc    layout constants for nes/*.s

All of it is NESpedia's (apps/wiki/tools/gen_screen.py), less its reader,
with the Gallery's name and an info page: the header is the jukebox's
(apps/jukebox/tools/gen_ui.py), nesp32's logo (nes/lib/logo.py) and the
program's name under it in the 5 x 7 font, which has small letters.

Tiles:

    $00          blank
    $01-$1F, $80-$9F   the header's logo and name, and the search box
    $20-$7F      the font at its ASCII codes, in colour 3 (white), and at
                 $7F the shift key's arrow
    $A0-$FF      the font again in colour 1 (blue): a character with bit 7
                 set. The keys of the keyboard, and the info page's titles.
"""

import argparse
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "nes", "lib"))

import logo  # noqa: E402
from stick import COLUMNS, QUERY_MAX  # noqa: E402

SCREEN_COLUMNS = 32
SCREEN_ROWS = 30

# --- layout, in tiles ---------------------------------------------------------

LOGO_ROW, LOGO_ROWS = logo.ROW, logo.ROWS
TITLE_ROW = logo.TITLE_ROW          # under the logo, in the 5 x 7 font, centered
TITLE_TEXT = "GALLERY"
TITLE_TOP = 1                       # pixels down that row that its letters start
HEADER_ROWS = 8                     # rows 0 to 7; the logo's palettes cover them

TEXT_COLUMN = 2                     # a line of the info page: COLUMNS wide from here

PROMPT_ROW, PROMPT_TEXT = 10, "SEARCH"    # over the field's first character
FIELD_COLUMN, FIELD_ROW = 1, 12     # QUERY_MAX wide
# A box round the field, one pixel thick, in the text palette's blue. The
# field fills the screen but for a column each side, so the box's sides are
# in those columns, as far in from the screen's edges as they will go.
BOX_COLOR = 1
BOX_LEFT, BOX_RIGHT = 5, 8 * 32 - 6             # x of its sides
BOX_TOP, BOX_BOTTOM = 8 * (FIELD_ROW - 1) + 4, 8 * (FIELD_ROW + 1) + 2    # y of its top and bottom
CURSOR_CHAR = "_"
KEY_COLUMN, KEY_ROW = 6, 15         # the first key; the rest are KEY_STEP apart
KEY_STEP = 2
KEYS = ("1234567890", "QWERTYUIOP", "ASDFGHJKL-", "ZXCVBNM,.'")
SPACE_ROW = KEY_ROW + KEY_STEP * len(KEYS)
SPACE_TEXT = "SPACE"
SPACE_COLUMN = (SCREEN_COLUMNS - len(SPACE_TEXT)) // 2
# The shift key is on the space bar's row, under the first column of keys:
# an arrow, at a code of the font's own that no text uses.
SHIFT_CHAR = "\x7f"
STATUS_COLUMN, STATUS_ROW = 2, 24   # COLUMNS wide
HELP = ((26, "A : TYPE   B : DELETE"), (28, "START : SEARCH"))
HELP_CART = "START : SEARCH   SELECT : MENU"   # on the cartridge, Select is its menu
DEFAULT_QUERY = "LIGHTHOUSE"


# The info page, in nametable 0, before a picture: which it is, its words
# (the nesp32's, a line each), how it is going, and the buttons.
INFO = ((3, "PICTURES FROM", True), (4, "WIKIMEDIA COMMONS", True),
        (22, "LEFT / RIGHT : MORE", False))
INFO_HELP_ROW = 24
INFO_HELP = "B : SEARCH"
INFO_HELP_CART = "B : SEARCH   SELECT : MENU"
COUNT_ROW = 7
COUNT_TEXT = "PICTURE 00 OF 00"   # the digits are the ROM's
CAPTION_ROWS = (10, 11, 13, 14)     # the nesp32's lines: the name, twice, by whom, licence
INFO_STATUS_ROW = 18

# --- tiles ---------------------------------------------------------------------

TILE_BLANK = 0x00
PICTURE_TILES = list(range(0x01, 0x20)) + list(range(0x80, 0xA0))
ALT = 0x80                          # a font tile in the second colour

BACKDROP = 0x0F
PALETTES = (
    (0x21, 0x10, 0x30),     # 0: text white, headings and keys blue
    (0x30, 0x10, 0x30),     # 1: the key under the cursor; its colour 1 pulses
    (0x16, 0x00, 0x30),     # 2: the logo's 32, red and white
    logo.PALETTE,           # 3: the rest of the logo, and the name
)
PALETTE_TEXT, PALETTE_CURSOR, PALETTE_RED, PALETTE_LOGO = 0, 1, 2, 3
# The cursor's key is shown by giving its 2 x 2 tiles PALETTE_CURSOR, whose
# colour 1 (the keys' colour) the ROM steps through these, white to
# blues and back. Every key has such a square to itself.
PULSE = (0x30, 0x31, 0x21, 0x12, 0x21, 0x31)
PULSE_ADDRESS = 0x3F00 + 4 * PALETTE_CURSOR + 1
ATTRIBUTES = 0x27C0                 # nametable 1's
TITLE_COLOR = logo.CYAN             # of the logo's palette
SPRITE_PALETTE = (BACKDROP, 0x10, 0x30)     # colour 1 is sprite 0's: as the backdrop, unseen

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
    "~": "00 00 08 15 02 00 00", SHIFT_CHAR: "04 0A 11 1B 0A 0A 0E",
}


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
    """The tile set and one nametable being laid out."""

    def __init__(self):
        self.tiles = {TILE_BLANK: tile_bytes(empty_tile())}
        for code in range(0x20, 0x80):
            self.tiles[code] = tile_bytes(font_tile(chr(code)))
            self.tiles[code | ALT] = tile_bytes(font_tile(chr(code), 1))
        self.shared = {}                # tile bytes -> index, for the pictures
        self.free = list(PICTURE_TILES)
        self.names = bytearray([TILE_BLANK]) * (SCREEN_COLUMNS * SCREEN_ROWS)
        self.attributes = bytearray(64)

    def put(self, column, row, tile):
        self.names[row * SCREEN_COLUMNS + column] = tile

    def text(self, column, row, text, alt=False):
        for offset, char in enumerate(text):
            self.put(column + offset, row, ord(char) | (ALT if alt else 0))

    def centered(self, row, text, alt=False):
        self.text((SCREEN_COLUMNS - len(text)) // 2, row, text, alt)

    def picture(self, column, row, pixels):
        for dy, tiles in enumerate(cut_tiles(pixels)):
            for dx, tile in enumerate(tiles):
                data = tile_bytes(tile)
                if data == self.tiles[TILE_BLANK]:
                    continue
                if data not in self.shared:
                    if not self.free:
                        raise ValueError("out of tiles for the header")
                    self.shared[data] = self.free.pop(0)
                    self.tiles[self.shared[data]] = data
                self.put(column + dx, row + dy, self.shared[data])

    def palette_rows(self, first_row, last_row, palette):
        """Give whole rows of tiles a palette. Attributes cover 2 x 2 tiles,
        so the rows must come in even-aligned pairs."""
        if first_row % 2 or not last_row % 2:
            raise ValueError("palette rows must be even-aligned pairs")
        for row in range(first_row, last_row + 1, 2):
            for column in range(0, SCREEN_COLUMNS, 2):
                index = (row // 4) * 8 + column // 4
                shift = ((row // 2) % 2) * 4 + ((column // 2) % 2) * 2
                value = self.attributes[index] & ~(3 << shift)
                self.attributes[index] = value | (palette << shift)

    def palette_at(self, row, column, palette):
        """Give the 2 x 2 tiles a tile is in a palette."""
        index, shift = attribute_cell(column, row)
        self.attributes[index] = self.attributes[index] & ~(3 << shift) | (palette << shift)

    def header(self):
        """Give the header its palettes: the logo's, and the red one for
        its 32."""
        self.palette_rows(0, HEADER_ROWS - 1, PALETTE_LOGO)
        for row in range(0, HEADER_ROWS, 2):
            for column in range(0, SCREEN_COLUMNS, 2):
                if logo.is_red(row, column):
                    self.palette_at(row, column, PALETTE_RED)

    def chr(self):
        data = bytearray(0x2000)
        for index, tile in self.tiles.items():
            data[index * 16:index * 16 + 16] = tile
        return bytes(data)

    def nametable(self):
        return bytes(self.names) + bytes(self.attributes)


def title_pixels():
    """The name in the 5 x 7 font, centered to the pixel in a strip the
    screen's width and one tile high."""
    pixels = [[0] * (8 * SCREEN_COLUMNS) for _ in range(8)]
    left = (8 * SCREEN_COLUMNS - (8 * len(TITLE_TEXT) - 3)) // 2
    for index, char in enumerate(TITLE_TEXT):
        for y, row in enumerate(glyph(char)):
            for x, on in enumerate(row):
                if on:
                    pixels[TITLE_TOP + y][left + 8 * index + x] = TITLE_COLOR
    return pixels


def key_column(index):
    return KEY_COLUMN + KEY_STEP * index


def field_text(query):
    """The field as the ROM draws it: the text, a cursor if there is room,
    and spaces."""
    text = query + (CURSOR_CHAR if len(query) < QUERY_MAX else "")
    return text.ljust(QUERY_MAX)


def box_pixels():
    """The box as a picture of the three rows of tiles it crosses."""
    top = 8 * (FIELD_ROW - 1)
    pixels = [[0] * (8 * SCREEN_COLUMNS) for _ in range(24)]
    for x in range(BOX_LEFT, BOX_RIGHT + 1):
        pixels[BOX_TOP - top][x] = pixels[BOX_BOTTOM - top][x] = BOX_COLOR
    for y in range(BOX_TOP - top, BOX_BOTTOM - top + 1):
        pixels[y][BOX_LEFT] = pixels[y][BOX_RIGHT] = BOX_COLOR
    return pixels


def build_screen(query=""):
    """The search screen as it is at power-on, with its field empty: the ROM
    puts DEFAULT_QUERY in it unless a Bluetooth keyboard is paired. The
    preview shows it with a query."""
    screen = Screen()
    screen.picture(0, LOGO_ROW, logo.pixels(8 * SCREEN_COLUMNS))
    screen.picture(0, TITLE_ROW, title_pixels())
    screen.header()
    screen.text(FIELD_COLUMN, PROMPT_ROW, PROMPT_TEXT)
    screen.picture(0, FIELD_ROW - 1, box_pixels())
    screen.text(FIELD_COLUMN, FIELD_ROW, field_text(query))
    for row, keys in enumerate(KEYS):
        for index, char in enumerate(keys):
            screen.put(key_column(index), KEY_ROW + KEY_STEP * row, ord(char) | ALT)
    screen.put(key_column(0), SPACE_ROW, ord(SHIFT_CHAR) | ALT)
    screen.text(SPACE_COLUMN, SPACE_ROW, SPACE_TEXT, alt=True)
    for row, text in HELP:
        screen.centered(row, text)
    return screen


def attribute_cell(column, row):
    """(index of the attribute byte, shift of the palette in it) for the
    2 x 2 square of tiles a tile is in."""
    return (row // 4) * 8 + column // 4, ((row // 2) % 2) * 4 + ((column // 2) % 2) * 2


def key_attribute(row, index):
    """(attribute byte's index, its value with the key lit) for a key."""
    byte, shift = attribute_cell(key_column(index), KEY_ROW + KEY_STEP * row)
    return byte, PALETTE_CURSOR << shift


def shift_attribute():
    """(attribute byte's index, its value with the shift key lit)."""
    byte, shift = attribute_cell(key_column(0), SPACE_ROW)
    return byte, PALETTE_CURSOR << shift


def space_attributes():
    """(first attribute byte's index, the values with the space bar lit)."""
    values = {}
    for column in range(SPACE_COLUMN, SPACE_COLUMN + len(SPACE_TEXT)):
        byte, shift = attribute_cell(column, SPACE_ROW)
        values[byte] = values.get(byte, 0) | PALETTE_CURSOR << shift
    first = min(values)
    if sorted(values) != list(range(first, first + len(values))):
        raise ValueError("the space bar's attribute bytes are not in a row")
    return first, [values[byte] for byte in sorted(values)]


def check_keys_have_squares():
    """No two keys share a square, and nothing else is in one."""
    squares = [attribute_cell(key_column(index), KEY_ROW + KEY_STEP * row)
               for row in range(len(KEYS)) for index in range(len(KEYS[0]))]
    squares.append(attribute_cell(key_column(0), SPACE_ROW))
    squares += [attribute_cell(column, SPACE_ROW)
                for column in range(SPACE_COLUMN, SPACE_COLUMN + len(SPACE_TEXT), 2)]
    if len(set(squares)) != len(squares):
        raise ValueError("two keys share an attribute square")


def info_texts(on_cart=None):
    """The info page's words that do not change: (row, column, text, alt).
    With on_cart None, without the help, which depends on it."""
    texts = [(row, (SCREEN_COLUMNS - len(text)) // 2, text, alt) for row, text, alt in INFO]
    texts.append((COUNT_ROW, (SCREEN_COLUMNS - len(COUNT_TEXT)) // 2, COUNT_TEXT, True))
    if on_cart is not None:
        help_text = INFO_HELP_CART if on_cart else INFO_HELP
        texts.append((INFO_HELP_ROW, (SCREEN_COLUMNS - len(help_text)) // 2, help_text, False))
    return texts


def text_bytes(text, alt):
    return ", ".join("$%02X" % (ord(char) | (ALT if alt else 0)) for char in text)


def include():
    check_keys_have_squares()
    lines = ["; Generated by tools/gen_screen.py. Do not edit.", ""]

    def constant(name, value, note=""):
        lines.append("%-16s = %-6s%s" % (name, value, ("  ; " + note) if note else ""))

    constant("COLUMNS", COLUMNS, "characters in a line of the article")
    constant("QUERY_MAX", QUERY_MAX)
    constant("TEXT_COLUMN", TEXT_COLUMN)
    constant("ALT", "$%02X" % ALT, "a character in the second colour")
    constant("FIELD_ADDR", "$%04X" % (0x2400 + 32 * FIELD_ROW + FIELD_COLUMN))
    constant("STATUS_ADDR", "$%04X" % (0x2400 + 32 * STATUS_ROW + STATUS_COLUMN))
    constant("KEY_ROWS", len(KEYS), "rows of keys; the space bar is the row after")
    constant("KEY_COLUMNS", len(KEYS[0]))
    constant("KEY_STEP", KEY_STEP)
    constant("SPACE_LENGTH", len(SPACE_TEXT))
    constant("CURSOR_CHAR", "'%s'" % CURSOR_CHAR)
    help_row, help_text = HELP[-1]
    if not len(help_text) <= len(HELP_CART) <= SCREEN_COLUMNS:
        raise ValueError("the cartridge's help must cover the last line of HELP")
    constant("HELP_CART_ADDR", "$%04X" % (0x2400 + 32 * help_row
                                          + (SCREEN_COLUMNS - len(HELP_CART)) // 2))
    constant("HELP_CART_LENGTH", len(HELP_CART))
    lines += ["", "; The first tile of each row of keys, and of the space bar.",
              "key_row_lo: .lobytes " + ", ".join(
                  "$%04X" % (0x2400 + 32 * (KEY_ROW + KEY_STEP * row) + KEY_COLUMN)
                  for row in range(len(KEYS))) + ", $%04X" % (0x2400 + 32 * SPACE_ROW + SPACE_COLUMN),
              "key_row_hi: .hibytes " + ", ".join(
                  "$%04X" % (0x2400 + 32 * (KEY_ROW + KEY_STEP * row) + KEY_COLUMN)
                  for row in range(len(KEYS))) + ", $%04X" % (0x2400 + 32 * SPACE_ROW + SPACE_COLUMN),
              "key_chars:  .byte " + ", ".join('"%s"' % keys for keys in KEYS),
              'space_text: .byte "%s"' % SPACE_TEXT,
              'help_cart:  .byte "%s"' % HELP_CART,
              "", "; Lighting a key: the attribute byte its square is in, and what to",
              "; write there. All other squares of the keyboard are palette 0.",
              "KEY_ATTR_HI = $%02X" % (ATTRIBUTES >> 8),
              "key_attr_lo: .byte " + ", ".join(
                  "$%02X" % ((ATTRIBUTES + key_attribute(row, index)[0]) & 0xFF)
                  for row in range(len(KEYS)) for index in range(len(KEYS[0]))),
              "key_attr_on: .byte " + ", ".join(
                  "$%02X" % key_attribute(row, index)[1]
                  for row in range(len(KEYS)) for index in range(len(KEYS[0]))),
              "SHIFT_ATTR = $%04X" % (ATTRIBUTES + shift_attribute()[0]),
              "SHIFT_ATTR_ON = $%02X" % shift_attribute()[1],
              "SPACE_ATTR = $%04X" % (ATTRIBUTES + space_attributes()[0]),
              "SPACE_ATTRS = %d" % len(space_attributes()[1]),
              "space_attr_on: .byte " + ", ".join("$%02X" % v for v in space_attributes()[1]),
              "PULSE_ADDR = $%04X" % PULSE_ADDRESS,
              "PULSE_STEPS = %d" % len(PULSE),
              "pulse_colors: .byte " + ", ".join("$%02X" % color for color in PULSE),
              'default_query: .byte "%s"' % DEFAULT_QUERY,
              "DEFAULT_LENGTH = %d" % len(DEFAULT_QUERY),
              "", "; The info page, in nametable 0: its words that do not change, each",
              "; an address, a length and the tiles, then a 0. Then its help, by",
              "; itself and on the cartridge, likewise.",
              "info_texts:"]

    def entry(row, column, text, alt):
        lines.append("    .word $%04X" % (0x2000 + 32 * row + column))
        lines.append("    .byte %d, %s" % (len(text), text_bytes(text, alt)))

    for each in info_texts():
        entry(*each)
    lines.append("    .word 0")
    for label, on_cart in (("info_help", False), ("info_help_cart", True)):
        lines.append(label + ":")
        entry(*info_texts(on_cart)[-1])
        lines.append("    .word 0")
    count_row, count_column = COUNT_ROW, (SCREEN_COLUMNS - len(COUNT_TEXT)) // 2
    lines += ["COUNT_ADDR = $%04X" % (0x2000 + 32 * count_row + count_column),
              "COUNT_INDEX = %d" % COUNT_TEXT.index("00"),
              "COUNT_TOTAL = %d" % COUNT_TEXT.rindex("00"),
              "INFO_STATUS_ADDR = $%04X" % (0x2000 + 32 * INFO_STATUS_ROW + TEXT_COLUMN),
              "caption_lo: .lobytes " + ", ".join(
                  "$%04X" % (0x2000 + 32 * row + TEXT_COLUMN) for row in CAPTION_ROWS),
              "caption_hi: .hibytes " + ", ".join(
                  "$%04X" % (0x2000 + 32 * row + TEXT_COLUMN) for row in CAPTION_ROWS),
              "CAPTION_LINES = %d" % len(CAPTION_ROWS),
              "", "palette_data:"]
    for palette in PALETTES + (SPRITE_PALETTE,) * 4:
        lines.append("    .byte " + ", ".join("$%02X" % color for color in (BACKDROP,) + palette))
    return "\n".join(lines) + "\n"


# --- preview -------------------------------------------------------------------

# The few NES colors the screen uses, as RGB.
NES_RGB = {
    0x0F: (0, 0, 0), 0x00: (84, 84, 84), 0x10: (152, 150, 152), 0x30: (236, 238, 236),
    0x12: (48, 50, 236), 0x21: (76, 154, 236), 0x31: (168, 204, 236),
    0x01: (0, 30, 116), 0x2C: (56, 180, 204), 0x16: (152, 34, 32),
}


def render(chr_data, nametable, palettes=PALETTES, backdrop=BACKDROP):
    """The screen as rows of (r, g, b), from CHR data and a 1 KB nametable."""
    rows = [[None] * (8 * SCREEN_COLUMNS) for _ in range(8 * SCREEN_ROWS)]
    for row in range(SCREEN_ROWS):
        for column in range(SCREEN_COLUMNS):
            tile = nametable[row * SCREEN_COLUMNS + column]
            attribute = nametable[960 + (row // 4) * 8 + column // 4]
            shift = ((row // 2) % 2) * 4 + ((column // 2) % 2) * 2
            colors = (backdrop,) + tuple(palettes[(attribute >> shift) & 3])
            planes = chr_data[tile * 16:tile * 16 + 16]
            for y in range(8):
                for x in range(8):
                    index = ((planes[y] >> (7 - x)) & 1) | (((planes[8 + y] >> (7 - x)) & 1) << 1)
                    rows[8 * row + y][8 * column + x] = NES_RGB.get(colors[index], (255, 0, 255))
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


def info_nametable(screen, lines, status, index=3, total=20, on_cart=False):
    """The info page, with a picture's words, for the preview."""
    other = Screen()
    other.tiles = screen.tiles
    for row, column, text, alt in info_texts(on_cart):
        other.text(column, row, text, alt)
    count_row, count_column = COUNT_ROW, (SCREEN_COLUMNS - len(COUNT_TEXT)) // 2
    other.text(count_column, count_row, COUNT_TEXT.replace("00", "%02d" % index, 1)
               .replace("00", "%02d" % total), alt=True)
    for row, line in zip(CAPTION_ROWS, lines):
        other.text(TEXT_COLUMN, row, line)
    other.text(TEXT_COLUMN, INFO_STATUS_ROW, status.center(COLUMNS))
    return other.nametable()


SAMPLE = ["Westerhever lighthouse and", "its keepers' houses",
          "By Somebody Example", "CC BY-SA 4.0"]


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
    parser.add_argument("out_dir", help="directory for chr.bin, screen.bin and screen.inc")
    parser.add_argument("--preview", help="also write the search screen as a PNG")
    parser.add_argument("--info", help="also write the info page, with sample words, as a PNG")
    args = parser.parse_args(argv)
    screen = build_screen()
    os.makedirs(args.out_dir, exist_ok=True)
    write_if_changed(os.path.join(args.out_dir, "chr.bin"), screen.chr()[:0x1000])
    write_if_changed(os.path.join(args.out_dir, "screen.bin"), screen.nametable())
    write_if_changed(os.path.join(args.out_dir, "screen.inc"), include().encode("ascii"))
    if args.preview:
        write_png(args.preview, render(screen.chr(), build_screen(DEFAULT_QUERY).nametable()))
    if args.info:
        write_png(args.info, render(screen.chr(), info_nametable(screen, SAMPLE, "LOADING...")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
