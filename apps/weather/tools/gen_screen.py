#!/usr/bin/env python3
"""Write the Weather ROM's tiles, palette and the screen it comes up with,
and the texts it puts on it.

    tools/gen_screen.py build
    tools/gen_screen.py build --preview screen.png

The tiles are the jukebox's (../jukebox/tools/gen_ui.py): its 5 x 7 font with
each character at its ASCII code, and its header, the name in the big
letters over the credit line, with what this ROM is between the two. The
font has capitals only, and a report from the nesp32 is in capitals, so the
tiles of the small letters are free: they are the pictures of the weather,
eight of them, four tiles each, where the nesp32's rows expect them
(nesp32's docs/PROTOCOL.md, WEATHER).

Under the header are a status line, and the middle of the screen, which is
the form a zip code is entered in or the report, row for row as the nesp32
lays it out. Under that, whose weather it is, in the small font of the
header's credit line, and a foot that says what the buttons do. screen.bin
is the nametable with the header and that credit on it; screen.inc tells
the ROM where the rest goes and holds what the ROM itself writes there.

The form's digits are in a box, and the one that Up and Down change
pulses, as the key under NESpedia's cursor does (../wiki): its square of
the screen has a palette of its own, and the font's colour in that palette
is changed every few frames.

A day's name is three letters over its picture, which is two tiles wide,
so the ROM puts it in tiles of its own: the same letters, half a tile to
the left (DAY_SHIFT), centered over the picture.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "jukebox", "tools"))

import gen_ui  # noqa: E402

SUBTITLE = "WEATHER"
STATUS_ROW = 8
STATUS_WIDTH = 28                   # the nesp32's words for what went wrong fit
STATUS_COLUMN = (gen_ui.SCREEN_COLUMNS - STATUS_WIDTH) // 2
# In the order of the ROM's STATUS_* numbers; the one after the last is the
# nesp32's own words.
STATUS_TEXT = (("WAITING", "WAITING FOR LINK"), ("NONE", ""), ("NO_WIFI", "NO WI-FI"),
               ("FINDING", "FINDING THE ZIP CODE"), ("FETCHING", "FETCHING THE WEATHER"),
               ("NO_ZIP", "NO SUCH ZIP CODE"), ("OLD", "UPDATE NESP32"))

# The middle: the nesp32's rows, which these numbers are (the ROM checks).
ROWS = 13
COLUMNS = 28
ZIP_LEN = 5
DEGREE = 0x1F
PICTURE = 0x60
BODY_ROW = 10
BODY_COLUMN = (gen_ui.SCREEN_COLUMNS - COLUMNS) // 2
CREDIT_ROW = 24
CREDIT = "WEATHER DATA: OPEN-METEO.COM"     # in the small font
CREDIT_TILES = 14                   # the tiles it is drawn across
CREDIT_COLUMN = (gen_ui.SCREEN_COLUMNS - CREDIT_TILES) // 2
FOOT_ROW = gen_ui.HELP_ROW
FOOT_FORM = "A : SUBMIT"
FOOT_FORM_CART = "A : SUBMIT   B : QUIT"   # on the cartridge, B is its menu again
FOOT_REPORT = "B : BACK"
# What the ROM paints, a row at a time: the middle's rows, then the foot.
PAINT_ROWS = ROWS + 1

# The days, as the nesp32 lays them out: each one's name over its picture,
# from the same column. Three letters are a tile wider than the picture,
# so the ROM puts each name's tiles here in their place, which have its
# letters half a tile to the left: centered over the picture.
DAY_ROW = 8
DAY_COLUMNS = (1, 7, 13, 19, 25)
DAY_NAMES = ("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT")
DAY_SHIFT = 4                       # pixels to the left
DAY_TILES = 4                       # from the column before the name's

# The form, by the middle's rows.
FORM_TITLE_ROW, FORM_TITLE = 2, "ENTER YOUR ZIP CODE"
FORM_DIGITS_ROW = 5
FORM_DIGIT_STEP = 2                 # columns from a digit to the next
FORM_DIGIT_COLUMN = (COLUMNS - (FORM_DIGIT_STEP * (ZIP_LEN - 1) + 1)) // 2
FORM_ZIP = "00000"                  # what the form begins with when nothing is kept
# A box round the digits, one pixel thick, in the light blue: the rows
# above and below theirs, and two columns clear of them each side.
BOX_COLOR = 2
BOX_FIRST = FORM_DIGIT_COLUMN - 2   # the first and the last of the middle's columns it crosses
BOX_LAST = FORM_DIGIT_COLUMN + FORM_DIGIT_STEP * (ZIP_LEN - 1) + 2
BOX_LEFT, BOX_RIGHT = 3, 8 * (BOX_LAST - BOX_FIRST) + 4     # x of its sides, from BOX_FIRST
BOX_TOP, BOX_BOTTOM = 4, 8 * 2 + 2                          # y, from the row above the digits

# The palettes: the font is colour 3, white, and a picture has yellow and
# a light blue besides, which is also the box's and the small font's.
BACKDROP = gen_ui.BACKDROP
PALETTE_SKY = (0x28, 0x21, 0x30)
PALETTES = (PALETTE_SKY, PALETTE_SKY, PALETTE_SKY, gen_ui.PALETTES[gen_ui.PALETTE_LOGO])
PALETTE_TEXT, PALETTE_CURSOR = 0, 1
# The form's digit that Up and Down change is shown by giving its 2 x 2
# tiles PALETTE_CURSOR, whose colour 3 (the font's) the ROM steps through
# these, white to the logo's blues and back: NESpedia's pulse. Every digit
# has such a square to itself.
PULSE = (0x30, 0x31, 0x21, 0x12, 0x21, 0x31)
PULSE_ADDRESS = 0x3F00 + 4 * PALETTE_CURSOR + 3
ATTRIBUTES = gen_ui.NAMETABLE + 0x3C0

# The small font's letters that the header's credit line has no use for.
SMALL_FONT = dict(gen_ui.SMALL_FONT)
SMALL_FONT.update({"W": "55575", "A": "25755", "H": "55755", "D": "65556", ":": "02020",
                   "P": "65644", "N": "65555", "M": "57555", "-": "00700", ".": "00002",
                   "C": "34443"})

# The pictures, 16 x 16, in the order of the nesp32's PICTURE numbers.
# Y is yellow, B the light blue, W white.
PICTURES = (
    ("SUN", """
        ................
        .......YY.......
        ..Y....YY....Y..
        ...Y........Y...
        .....YYYYYY.....
        ....YYYYYYYY....
        ....YYYYYYYY....
        .YY.YYYYYYYY.YY.
        .YY.YYYYYYYY.YY.
        ....YYYYYYYY....
        ....YYYYYYYY....
        .....YYYYYY.....
        ...Y........Y...
        ..Y....YY....Y..
        .......YY.......
        ................"""),
    ("MOON", """
        ................
        ......WWWW......
        ....WWWW........
        ...WWWW.....B...
        ..WWWW.....BBB..
        ..WWWW......B...
        .WWWWW..........
        .WWWWW..........
        .WWWWWW.........
        .WWWWWW.....W...
        ..WWWWWW...WW...
        ..WWWWWWWWWWW...
        ...WWWWWWWWW....
        ....WWWWWWW.....
        ......WWWW......
        ................"""),
    ("PARTLY", """
        ................
        .........Y......
        .....Y...Y...Y..
        ......Y.....Y...
        ........YYYY....
        .......YYYYYY...
        ....WWWWYYYYY.YY
        ...WWWWWWYYYY...
        ..WWWWWWWWWYY...
        .WWWWWWWWWWWW...
        .WWWWWWWWWWWWW..
        .WWWWWWWWWWWWW..
        .BWWWWWWWWWWWB..
        ..BBBBBBBBBBB...
        ................
        ................"""),
    ("CLOUD", """
        ................
        ................
        ................
        ......WWWW......
        .....WWWWWW.....
        ....WWWWWWWWW...
        ..WWWWWWWWWWWW..
        .WWWWWWWWWWWWWW.
        .WWWWWWWWWWWWWW.
        .WWWWWWWWWWWWWW.
        .BWWWWWWWWWWWWB.
        ..BBBBBBBBBBBB..
        ................
        ................
        ................
        ................"""),
    ("FOG", """
        ................
        ................
        ...WWWWWWWWWW...
        ................
        .WWWWWWWWWWWWWW.
        ................
        ...BBBBBBBBBBBB.
        ................
        .WWWWWWWWWWWW...
        ................
        ...BBBBBBBBBBB..
        ................
        .WWWWWWWWWWWWWW.
        ................
        ................
        ................"""),
    ("RAIN", """
        ................
        ......WWWW......
        .....WWWWWW.....
        ....WWWWWWWWW...
        ..WWWWWWWWWWWW..
        .WWWWWWWWWWWWWW.
        .WWWWWWWWWWWWWW.
        ..WWWWWWWWWWWW..
        ................
        ....B...B...B...
        ...B...B...B....
        ................
        .....B...B...B..
        ....B...B...B...
        ................
        ................"""),
    ("SNOW", """
        ................
        ......WWWW......
        .....WWWWWW.....
        ....WWWWWWWWW...
        ..WWWWWWWWWWWW..
        .WWWWWWWWWWWWWW.
        .WWWWWWWWWWWWWW.
        ..WWWWWWWWWWWW..
        ................
        ...W.....W......
        ..WBW...WBW..W..
        ...W.....W..WBW.
        ......W......W..
        .....WBW........
        ......W.........
        ................"""),
    ("STORM", """
        ................
        ......WWWW......
        .....WWWWWW.....
        ....WWWWWWWWW...
        ..WWWWWWWWWWWW..
        .WWWWWWWWWWWWWW.
        .WWWWWWWWWWWWWW.
        ..WWWWWWWWWWWW..
        ........YY......
        .......YY...B...
        ..B...YYYY.B....
        .B......YY......
        .......YY...B...
        ......YY...B....
        ......Y.........
        ................"""),
)
PICTURE_COLORS = {".": 0, "Y": 1, "B": 2, "W": 3}
DEGREE_TILE = """
    .WW.....
    W..W....
    W..W....
    .WW.....
    ........
    ........
    ........
    ........"""


def pixels(drawing):
    rows = [[PICTURE_COLORS[char] for char in line.strip()]
            for line in drawing.strip().splitlines()]
    assert len({len(row) for row in rows}) == 1 and len(rows) == len(rows[0])
    return rows


def picture_tiles(which):
    """A picture's four tiles as the nesp32 numbers them: top left, top
    right, bottom left, bottom right."""
    first = PICTURE + 4 * which
    return (first, first + 1), (first + 2, first + 3)


def small_text(text, width, color):
    """Text in the small font, centered in a strip `width` pixels wide and
    one tile high: gen_ui's, with this ROM's letters."""
    pixels_ = [[0] * width for _ in range(8)]
    left = (width - (4 * len(text) - 1)) // 2
    for index, char in enumerate(text):
        for y, row in enumerate(SMALL_FONT[char]):
            for x in range(3):
                if int(row) >> (2 - x) & 1:
                    pixels_[1 + y][left + 4 * index + x] = color
    return pixels_


def day_pixels(name):
    """A day's name as a picture of the DAY_TILES tiles that take its
    place: the font's letters, DAY_SHIFT pixels to the left of where the
    tiles from its column would have them."""
    picture = [[0] * (8 * DAY_TILES) for _ in range(8)]
    for index, char in enumerate(name):
        for y, row in enumerate(gen_ui.font_tile(char)):
            for x, color in enumerate(row):
                if color:
                    picture[y][8 * (1 + index) + x - DAY_SHIFT] = color
    return picture


def box_pixels():
    """The box as a picture of the three rows of tiles it crosses."""
    picture = [[0] * (8 * (BOX_LAST - BOX_FIRST + 1)) for _ in range(8 * 3)]
    for x in range(BOX_LEFT, BOX_RIGHT + 1):
        picture[BOX_TOP][x] = picture[BOX_BOTTOM][x] = BOX_COLOR
    for y in range(BOX_TOP, BOX_BOTTOM + 1):
        picture[y][BOX_LEFT] = picture[y][BOX_RIGHT] = BOX_COLOR
    return picture


def digit_place(index):
    """(column, row) on the screen of one of the form's digits."""
    return (BODY_COLUMN + FORM_DIGIT_COLUMN + FORM_DIGIT_STEP * index,
            BODY_ROW + FORM_DIGITS_ROW)


def attribute_cell(column, row):
    """(index of the attribute byte, shift of the palette in it) for the
    2 x 2 square of tiles a tile is in."""
    return (row // 4) * 8 + column // 4, ((row // 2) % 2) * 4 + ((column // 2) % 2) * 2


def digit_attributes():
    """(the first attribute byte's index, how many there are, and for each
    digit which of them it is in and that byte with the digit lit)."""
    cells = [attribute_cell(*digit_place(index)) for index in range(ZIP_LEN)]
    if len({(byte, shift) for byte, shift in cells}) != ZIP_LEN:
        raise ValueError("two digits share a square of the screen")
    first = min(byte for byte, _ in cells)
    count = max(byte for byte, _ in cells) - first + 1
    return first, count, [(byte - first, PALETTE_CURSOR << shift) for byte, shift in cells]


def build_screen():
    screen = gen_ui.Screen()
    screen.names[:] = b" " * len(screen.names)  # the ROM writes text over text
    for which, (_, drawing) in enumerate(PICTURES):
        tiles = gen_ui.cut_tiles(pixels(drawing))
        for numbers, row in zip(picture_tiles(which), tiles):
            for number, tile in zip(numbers, row):
                screen.tiles[number] = gen_ui.tile_bytes(tile)
    screen.tiles[DEGREE] = gen_ui.tile_bytes(pixels(DEGREE_TILE))
    gen_ui.header(screen, SUBTITLE)
    screen.picture(CREDIT_COLUMN, CREDIT_ROW,
                   small_text(CREDIT, 8 * CREDIT_TILES, gen_ui.LOGO_BLUE))
    # The box's tiles, which the ROM paints with the form: drawn where the
    # form has them, to be given numbers, and taken off again.
    column, row = BODY_COLUMN + BOX_FIRST, BODY_ROW + FORM_DIGITS_ROW - 1
    screen.picture(column, row, box_pixels())
    width = BOX_LAST - BOX_FIRST + 1
    screen.box = []
    for line in range(3):
        start = (row + line) * gen_ui.SCREEN_COLUMNS + column
        screen.box.append(bytes(screen.names[start:start + width]))
        screen.names[start:start + width] = b" " * width
    # The days' names likewise.
    column, row = BODY_COLUMN + DAY_COLUMNS[0] - 1, BODY_ROW + DAY_ROW
    start = row * gen_ui.SCREEN_COLUMNS + column
    screen.days = {}
    for name in DAY_NAMES:
        screen.picture(column, row, day_pixels(name))
        screen.days[name] = bytes(screen.names[start:start + DAY_TILES])
        screen.names[start:start + DAY_TILES] = b" " * DAY_TILES
    return screen


def on_screen(rows, screen=None):
    """A report's rows as the ROM draws them: with the days' names in
    their own tiles."""
    screen = screen or build_screen()
    rows = [bytearray(row.encode("latin-1")) for row in rows]
    for column in DAY_COLUMNS:
        name = bytes(rows[DAY_ROW][column:column + 3]).decode("latin-1")
        if name in screen.days:
            rows[DAY_ROW][column - 1:column - 1 + DAY_TILES] = screen.days[name]
    return [row.decode("latin-1") for row in rows]


def palette_data():
    data = bytearray()
    for colors in PALETTES:
        data += bytes((BACKDROP,) + tuple(colors))
    return bytes(data)


def form_lines(screen=None):
    """The form as the ROM paints it, less the digits: the middle's rows,
    and the foot, as tiles."""
    screen = screen or build_screen()
    lines = [""] * PAINT_ROWS
    lines[FORM_TITLE_ROW] = FORM_TITLE.center(COLUMNS)
    lines[ROWS] = FOOT_FORM.center(COLUMNS)
    assert all(len(line) <= COLUMNS for line in lines)
    lines = [bytearray(line.ljust(COLUMNS).encode("ascii")) for line in lines]
    for line, tiles in enumerate(screen.box):
        lines[FORM_DIGITS_ROW - 1 + line][BOX_FIRST:BOX_LAST + 1] = tiles
    return [line.decode("latin-1") for line in lines]


def paint_addresses():
    return ([gen_ui.address(BODY_COLUMN, BODY_ROW + row) for row in range(ROWS)]
            + [gen_ui.address(BODY_COLUMN, FOOT_ROW)])


def screen_include(screen):
    first, count, lit = digit_attributes()
    lines = ["; Generated by tools/gen_screen.py. Do not edit.", "",
             "STATUS_ADDR = $%04X" % gen_ui.address(STATUS_COLUMN, STATUS_ROW),
             "STATUS_WIDTH = %d" % STATUS_WIDTH]
    text = []
    for index, (name, words) in enumerate(STATUS_TEXT):
        if len(words) > STATUS_WIDTH:
            raise ValueError("status text too wide: " + words)
        lines.append("STATUS_%s = %d" % (name, index))
        text += list(words.center(STATUS_WIDTH).encode("ascii"))
    lines += ["STATUS_WHY = %d          ; the nesp32's own words" % len(STATUS_TEXT),
              "ROWS = %d" % ROWS,
              "COLUMNS = %d" % COLUMNS,
              "PAINT_ROWS = %d         ; the middle's rows, and the foot" % PAINT_ROWS,
              "PICTURE_TILE = $%02X" % PICTURE,
              "DEGREE_TILE = $%02X" % DEGREE,
              "FORM_DIGITS_ROW = %d" % FORM_DIGITS_ROW,
              "DAY_ROW = %d" % DAY_ROW,
              "DAYS = %d" % len(DAY_COLUMNS),
              "DAY_NAMES = %d" % len(DAY_NAMES),
              "DAY_TILES = %d" % DAY_TILES,
              "FORM_DIGIT_COLUMN = %d" % FORM_DIGIT_COLUMN,
              "FORM_DIGIT_STEP = %d" % FORM_DIGIT_STEP,
              "DIGIT_ATTR_ADDR = $%04X ; the attribute bytes the digits' squares are in"
              % (ATTRIBUTES + first),
              "DIGIT_ATTRS = %d" % count,
              "PULSE_ADDR = $%04X" % PULSE_ADDRESS,
              "PULSE_STEPS = %d" % len(PULSE),
              "", '.segment "RODATA"',
              "pulse_colors: .byte " + ", ".join("$%02X" % color for color in PULSE),
              "digit_attr: .byte " + ", ".join("%d" % byte for byte, _ in lit),
              "digit_attr_on: .byte " + ", ".join("$%02X" % value for _, value in lit)]
    lines += gen_ui.byte_lines("status_text", text, per_line=STATUS_WIDTH)
    places = paint_addresses()
    lines += ["paint_lo: .byte " + ", ".join("$%02X" % (place & 0xFF) for place in places),
              "paint_hi: .byte " + ", ".join("$%02X" % (place >> 8) for place in places)]
    form = []
    for line in form_lines(screen):
        form += list(line.encode("latin-1"))
    lines += gen_ui.byte_lines("form_text", form, per_line=COLUMNS)
    lines += gen_ui.byte_lines("report_foot", list(FOOT_REPORT.center(COLUMNS).encode("ascii")),
                               per_line=COLUMNS)
    lines += gen_ui.byte_lines("form_foot_cart",
                               list(FOOT_FORM_CART.center(COLUMNS).encode("ascii")),
                               per_line=COLUMNS)
    lines.append("day_column: .byte " + ", ".join("%d" % column for column in DAY_COLUMNS))
    names, tiles = [], []
    for name in DAY_NAMES:
        names += list(name.encode("ascii")) + [0]   # four to a name, as its tiles are
        tiles += list(screen.days[name])
    lines += gen_ui.byte_lines("day_names", names, per_line=DAY_TILES)
    lines += gen_ui.byte_lines("day_tiles", tiles, per_line=DAY_TILES)
    lines += gen_ui.byte_lines("form_zip", list(FORM_ZIP.encode("ascii")))
    return "\n".join(lines) + "\n"


# --- the preview ---------------------------------------------------------------

def picture_rows(which):
    return tuple("".join(chr(tile) for tile in row) for row in picture_tiles(which))


def sample_report():
    """A report as the nesp32 lays one out, with most of the pictures."""
    sun, moon, partly, cloud, fog, rain, snow, storm = (picture_rows(which)
                                                        for which in range(len(PICTURES)))
    degree = chr(DEGREE)
    days = (partly, sun, rain, storm, snow)
    return [line.ljust(COLUMNS) for line in (
        "BEVERLY HILLS, CA      90210",
        "",
        partly[0] + "  72" + degree + "F  PARTLY CLOUDY",
        partly[1] + "  HIGH 74" + degree + "  LOW 55" + degree,
        "    HUMIDITY 43%",
        "    WIND 9 MPH",
        "",
        "",
        " TUE   WED   THU   FRI   SAT",
        " " + "    ".join(day[0] for day in days),
        " " + "    ".join(day[1] for day in days),
        " 74    81    66    58    31",
        " 55    61    52    40    24",
    )]


def with_form(screen, digits=FORM_ZIP, cursor=0):
    """The form, with one digit in the cursor's palette."""
    out = screen.copy()
    for row, line in enumerate(form_lines(screen)):
        place = paint_addresses()[row] - gen_ui.NAMETABLE
        out.text(place % gen_ui.SCREEN_COLUMNS, place // gen_ui.SCREEN_COLUMNS, line)
    for index, digit in enumerate(digits):
        out.text(*digit_place(index), digit)
    byte, shift = attribute_cell(*digit_place(cursor))
    out.attributes[byte] |= PALETTE_CURSOR << shift
    return out


def with_report(screen, rows):
    out = screen.copy()
    for row, line in enumerate(on_screen(rows, screen)):
        out.text(BODY_COLUMN, BODY_ROW + row, line)
    out.text(BODY_COLUMN, FOOT_ROW, FOOT_REPORT.center(COLUMNS))
    return out


def render(screen, pulse=0):
    palettes = list(PALETTES)
    palettes[PALETTE_CURSOR] = PALETTES[PALETTE_CURSOR][:2] + (PULSE[pulse],)
    return gen_ui.render(screen.chr(), screen.nametable(), palettes=palettes, backdrop=BACKDROP)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("out_dir", help="directory for chr.bin, screen.bin, palette.bin "
                                        "and screen.inc")
    parser.add_argument("--preview", help="also write the screen with a report on it as a "
                                          "PNG, and with the form beside it")
    args = parser.parse_args(argv)
    screen = build_screen()
    os.makedirs(args.out_dir, exist_ok=True)
    gen_ui.write_if_changed(os.path.join(args.out_dir, "chr.bin"), screen.chr())
    gen_ui.write_if_changed(os.path.join(args.out_dir, "screen.bin"), screen.nametable())
    gen_ui.write_if_changed(os.path.join(args.out_dir, "palette.bin"), palette_data())
    gen_ui.write_if_changed(os.path.join(args.out_dir, "screen.inc"),
                            screen_include(screen).encode())
    if args.preview:
        gen_ui.write_png(args.preview, render(with_report(screen, sample_report())))
        base, extension = os.path.splitext(args.preview)
        gen_ui.write_png(base + "-form" + extension,
                         render(with_form(screen, "90210", 2), pulse=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
