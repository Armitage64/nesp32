#!/usr/bin/env python3
"""Generate the player ROM's screen: tiles, the nametable, and lookup tables.

    tools/gen_ui.py build
    tools/gen_ui.py build --preview screen.png

Writes into the output directory:

    chr.bin                 8 KB of CHR ROM (background tiles in the first 4 KB)
    screen.bin              nametable and attributes for the link ROM
    screen_standalone.bin   the same for the standalone ROM (other help text)
    ui_data.inc             palette, screen positions and tables for nes/ui.inc

The layout lives here and nowhere else: nes/ui.inc takes every address and
size from ui_data.inc. Outputs are only rewritten when their contents
change, so make does not rebuild the ROMs for nothing.
"""

import argparse
import math
import os
import struct
import sys
import zlib

SCREEN_COLUMNS = 32
SCREEN_ROWS = 30
NAMETABLE = 0x2000

# --- layout, in tiles ---------------------------------------------------------

LOGO_ROW = 3
LOGO_TEXT = "NESP32 JUKEBOX"           # letters 2 x 2 tiles, centered
CREDIT_ROW = 6
CREDIT_TEXT = "RETRO BITS (2026)"   # in the small font, under the logo
CREDIT_COLUMN, CREDIT_TILES = 11, 10  # the tiles it is drawn across
LOGO_LAST_ROW = 7                   # the logo's palette covers rows 0 to here
GAME_COLUMN, GAME_ROW = 2, 9        # the game the track came from
TITLE_COLUMN, TITLE_ROW = 2, 11    # the track's name
TITLE_MAX = 28                      # jbs.TITLE_MAX: the widest name
TIME_TEMPLATE = " 0:00 / 0:00 "     # position / length, as a track starts
TIME_COLUMN, TIME_ROW = 9, 13
TIME_TOTAL = 8                      # where the length's characters go
TIME_TOTAL_WIDTH = 5                # jbs.LENGTH_CHARS
STATUS_COLUMN, STATUS_ROW = 8, 14
STATUS_WIDTH = 16
BAR_COLUMN, BAR_ROW = 2, 16
BAR_COUNT = 28
BAR_ROWS = 8
BAR_MAX = 8 * BAR_ROWS              # a bar's height in pixels
BASELINE_ROW = BAR_ROW + BAR_ROWS
HELP_ROW = 26
HELP_LINK = "START=PLAY/PAUSE  </>=TRACK"
HELP_STANDALONE = "START=PAUSE"

# Indexed by ui_status in nes/ui.inc. Playing shows nothing: the clock
# running says as much.
STATUS_TEXT = ("WAITING FOR LINK", "PRESS START", "LOADING", "", "PAUSED",
               "THE END", "SAMPLED SOUND", "UPDATE NESP32", "NO MUSIC FOUND")

# --- tiles ---------------------------------------------------------------------

TILE_BLANK = 0x00
TILE_BAR = 0x00         # + height in pixels, 0-8: the bar tiles are $01-$08
TILE_BASELINE = 0x09
TILE_LOGO = 0x80        # the big letters, as many as they need

# Background palettes. Color 3 is white in all of them, and the font uses
# only color 3, so text can sit anywhere. Bars use color 1, which is what
# changes from band to band.
BACKDROP = 0x0F
PALETTES = (
    (0x2A, 0x00, 0x30),     # 0: text; green bars
    (0x28, 0x00, 0x30),     # 1: yellow bars
    (0x16, 0x00, 0x30),     # 2: red bars
    (0x12, 0x21, 0x31),     # 3: the logo: three blues, dark to pale
)
PALETTE_TEXT, PALETTE_LOGO = 0, 3
BAR_BAND_PALETTES = (2, 1, 0, 0)    # per two rows of tiles, top band first

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
}
# The tile for a character is its ASCII code. Titles arrive in mixed case
# and the font has capitals only, so the lowercase tiles repeat them.
FONT_ALIASES = {"`": "'", "{": "(", "|": "!", "}": ")", "~": "-"}


def glyph(char):
    """A character as 7 rows of 5 pixels (0 or 1)."""
    char = FONT_ALIASES.get(char, char.upper())
    rows = [int(value, 16) for value in FONT.get(char, FONT["?"]).split()]
    return [[(row >> (4 - x)) & 1 for x in range(5)] for row in rows]


# A 3 x 5 font for the credit line, one row per digit, bit 2 leftmost. Only
# the characters that line uses.
SMALL_FONT = {
    " ": "00000", "R": "65655", "E": "74647", "T": "72222", "O": "75557",
    "B": "65656", "I": "72227", "S": "34216", "(": "12221", ")": "42224",
    "2": "61247", "0": "75557", "6": "34757",
}


def small_text(text, width, color):
    """Text in the small font, centered in a strip `width` pixels wide and
    one tile high."""
    pixels = [[0] * width for _ in range(8)]
    left = (width - (4 * len(text) - 1)) // 2
    for index, char in enumerate(text):
        for y, row in enumerate(SMALL_FONT[char]):
            for x in range(3):
                if int(row) >> (2 - x) & 1:
                    pixels[1 + y][left + 4 * index + x] = color
    return pixels


def empty_tile():
    return [[0] * 8 for _ in range(8)]


def font_tile(char):
    tile = empty_tile()
    for y, row in enumerate(glyph(char)):
        for x, on in enumerate(row):
            if on:
                tile[y][x + 1] = 3
    return tile


def bar_tile(height):
    """The bottom `height` pixels of a cell lit, 7 wide, cut into segments of
    3 by a dark line so a bar reads as a column of lamps."""
    tile = empty_tile()
    for y in range(8):
        from_bottom = 7 - y
        if from_bottom < height and from_bottom % 4 != 3:
            for x in range(1, 8):
                tile[y][x] = 1
    return tile


def baseline_tile():
    tile = empty_tile()
    tile[1] = [3] * 8
    return tile


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
    """The tile set and one nametable being laid out."""

    def __init__(self):
        self.tiles = {TILE_BLANK: tile_bytes(empty_tile()),
                      TILE_BASELINE: tile_bytes(baseline_tile())}
        for height in range(1, 9):
            self.tiles[TILE_BAR + height] = tile_bytes(bar_tile(height))
        for code in range(0x20, 0x80):
            self.tiles[code] = tile_bytes(font_tile(chr(code)))
        self.shared = {}    # tile bytes -> index, for the logo
        self.next_tile = TILE_LOGO
        self.names = bytearray([TILE_BLANK]) * (SCREEN_COLUMNS * SCREEN_ROWS)
        self.attributes = bytearray(64)

    def copy(self):
        other = Screen.__new__(Screen)
        other.tiles, other.shared, other.next_tile = self.tiles, self.shared, self.next_tile
        other.names, other.attributes = bytearray(self.names), bytearray(self.attributes)
        return other

    def put(self, column, row, tile):
        self.names[row * SCREEN_COLUMNS + column] = tile

    def text(self, column, row, text):
        for offset, char in enumerate(text):
            self.put(column + offset, row, ord(char))

    def centered(self, row, text):
        self.text((SCREEN_COLUMNS - len(text)) // 2, row, text)

    def picture(self, column, row, pixels):
        for dy, tiles in enumerate(cut_tiles(pixels)):
            for dx, tile in enumerate(tiles):
                data = tile_bytes(tile)
                if data == self.tiles[TILE_BLANK]:
                    continue
                if data not in self.shared:
                    if self.next_tile > 0xFF:
                        raise ValueError("out of background tiles")
                    self.shared[data] = self.next_tile
                    self.tiles[self.next_tile] = data
                    self.next_tile += 1
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

    def chr(self):
        data = bytearray(0x2000)
        for index, tile in self.tiles.items():
            data[index * 16:index * 16 + 16] = tile
        return bytes(data)

    def nametable(self):
        return bytes(self.names) + bytes(self.attributes)


def build_screens():
    """Return (link screen, standalone screen); they share one tile set."""
    screen = Screen()
    column = (SCREEN_COLUMNS - 2 * len(LOGO_TEXT)) // 2
    for index, char in enumerate(LOGO_TEXT):
        if char != " ":
            screen.picture(column + 2 * index, LOGO_ROW, big_letter(char))
    # Color 2 of the logo's palette: its middle blue.
    screen.picture(CREDIT_COLUMN, CREDIT_ROW, small_text(CREDIT_TEXT, 8 * CREDIT_TILES, 2))
    screen.palette_rows(0, LOGO_LAST_ROW, PALETTE_LOGO)
    for band, palette in enumerate(BAR_BAND_PALETTES):
        screen.palette_rows(BAR_ROW + 2 * band, BAR_ROW + 2 * band + 1, palette)
    for column in range(BAR_COLUMN, BAR_COLUMN + BAR_COUNT):
        screen.put(column, BASELINE_ROW, TILE_BASELINE)
    standalone = screen.copy()
    screen.centered(HELP_ROW, HELP_LINK)
    standalone.centered(HELP_ROW, HELP_STANDALONE)
    return screen, standalone


# --- tables for the visualizer -------------------------------------------------

CPU_HZ = 1789773.0
COLUMNS_PER_OCTAVE = 4
LOWEST_HZ = 32.70       # C1: the left edge of the display
TRIANGLE_SHIFT = COLUMNS_PER_OCTAVE  # a triangle plays an octave below a pulse


def pulse_column(period):
    """The bar a pulse channel's 11-bit timer period lands on."""
    hertz = CPU_HZ / (16 * (period + 1))
    column = int(math.floor(COLUMNS_PER_OCTAVE * math.log2(hertz / LOWEST_HZ)))
    return min(max(column, 0), BAR_COUNT - 1)


def period_tables():
    """(low, high): low[p] for periods under 256, high[p >> 3] for the rest."""
    low = [pulse_column(period) for period in range(256)]
    high = [pulse_column(8 * index + 4) if index >= 32 else 0 for index in range(256)]
    return low, high


def noise_columns():
    """The noise channel's 16 periods, shortest (brightest) first, spread
    over the upper part of the display."""
    return [BAR_COUNT - 1 - (index * 3) // 2 for index in range(16)]


def bar_row_tables():
    """Per row of tiles, top first: the tile for each bar height 0..BAR_MAX."""
    tables = []
    for row in range(BAR_ROWS):
        below = 8 * (BAR_ROWS - 1 - row)
        tables.append([TILE_BAR + min(max(height - below, 0), 8)
                       for height in range(BAR_MAX + 1)])
    return tables


# The APU's length counter loads, indexed by the top 5 bits of a channel's
# fourth register, in half frames (the counter is clocked at 120 Hz).
LENGTH_TABLE = (10, 254, 20, 2, 40, 4, 80, 6, 160, 8, 60, 10, 14, 12, 26, 14,
                12, 16, 24, 18, 48, 20, 96, 22, 192, 24, 72, 26, 16, 28, 32, 30)


def envelope_steps():
    """How far an envelope falls per frame, in sixteenths of a volume step,
    for each envelope period: it is clocked at 240 Hz and divided by V + 1."""
    return [round(64 / (period + 1)) for period in range(16)]


def address(column, row):
    return NAMETABLE + row * SCREEN_COLUMNS + column


def byte_lines(label, values, per_line=16):
    lines = ["%s:" % label]
    for start in range(0, len(values), per_line):
        lines.append("    .byte " + ", ".join("$%02X" % v for v in values[start:start + per_line]))
    return lines


def ui_include():
    low, high = period_tables()
    lines = [
        "; Generated by tools/gen_ui.py. Do not edit.",
        "GAME_ADDR = $%04X" % address(GAME_COLUMN, GAME_ROW),
        "TITLE_ADDR = $%04X" % address(TITLE_COLUMN, TITLE_ROW),
        "TIME_ADDR = $%04X" % address(TIME_COLUMN, TIME_ROW),
        "TIME_WIDTH = %d" % len(TIME_TEMPLATE),
        "TIME_TOTAL = %d" % TIME_TOTAL,
        "TIME_TOTAL_WIDTH = %d" % TIME_TOTAL_WIDTH,
        "TITLE_MAX = %d" % TITLE_MAX,
        "STATUS_ADDR = $%04X" % address(STATUS_COLUMN, STATUS_ROW),
        "STATUS_WIDTH = %d" % STATUS_WIDTH,
        "BARS_ADDR = $%04X" % address(BAR_COLUMN, BAR_ROW),
        "BAR_COUNT = %d" % BAR_COUNT,
        "BAR_ROWS = %d" % BAR_ROWS,
        "BAR_MAX = %d" % BAR_MAX,
        "TRIANGLE_SHIFT = %d" % TRIANGLE_SHIFT,
        "",
        '.segment "RODATA"',
    ]
    palette = []
    for colors in PALETTES:
        palette += [BACKDROP] + list(colors)
    lines += byte_lines("ui_palette", palette)
    status = []
    for text in STATUS_TEXT:
        if len(text) > STATUS_WIDTH:
            raise ValueError("status text too wide: " + text)
        status += list(text.center(STATUS_WIDTH).encode("ascii"))
    lines += byte_lines("status_text", status)
    lines += byte_lines("time_template", list(TIME_TEMPLATE.encode("ascii")))
    for row, table in enumerate(bar_row_tables()):
        lines += byte_lines("bar_row%d" % row, table)
    lines += byte_lines("period_col_low", low)
    lines += byte_lines("period_col_high", high)
    lines += byte_lines("noise_col", noise_columns())
    lines += byte_lines("length_table", list(LENGTH_TABLE))
    lines += byte_lines("envelope_step", envelope_steps())
    return "\n".join(lines) + "\n"


# --- preview -------------------------------------------------------------------

# The few NES colors the screen uses, as RGB.
NES_RGB = {
    0x0F: (0, 0, 0), 0x00: (84, 84, 84), 0x10: (152, 150, 152), 0x30: (236, 238, 236),
    0x16: (152, 34, 32), 0x28: (196, 180, 28), 0x2A: (76, 208, 32),
    0x12: (48, 50, 236), 0x21: (76, 154, 236), 0x31: (168, 204, 236),
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
    parser.add_argument("out_dir", help="directory for chr.bin, screen*.bin and ui_data.inc")
    parser.add_argument("--preview", help="also write the link ROM's screen as a PNG")
    args = parser.parse_args(argv)
    screen, standalone = build_screens()
    os.makedirs(args.out_dir, exist_ok=True)
    write_if_changed(os.path.join(args.out_dir, "chr.bin"), screen.chr())
    write_if_changed(os.path.join(args.out_dir, "screen.bin"), screen.nametable())
    write_if_changed(os.path.join(args.out_dir, "screen_standalone.bin"), standalone.nametable())
    write_if_changed(os.path.join(args.out_dir, "ui_data.inc"), ui_include().encode("ascii"))
    if args.preview:
        write_png(args.preview, render(screen.chr(), screen.nametable()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
