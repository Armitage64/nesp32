#!/usr/bin/env python3
"""Write the NESradio ROM's tiles, palette and the screen it comes up with,
the status line's texts, and its stations.

    tools/gen_screen.py build
    tools/gen_screen.py build --preview screen.png

The tiles are the jukebox's (../jukebox/tools/gen_ui.py): its 5 x 7 font with
each character at its ASCII code, its palettes, and its header, the name in
the big letters over the credit line, with what this ROM is between the two.
The font has capitals only.

Under the header are a status line that the ROM writes; a radio's dial, an
FM scale that is on the screen from the start, with a needle at the
station's frequency, which is a sprite the ROM moves and hides for a station
with none; the middle of the screen, which the ROM writes; and at the foot
what the buttons do, which it writes too: on the menu A plays the
station, and Select is the cartridge's menu again; with a station A plays
and pauses, which it says with a picture of each, and B is the menu again
while it is tuning or paused. Over the foot, on the menu, is the quality,
which Up and Down change, and which the ROM draws with the foot.

The middle is the station, which Left and Right change: its letters, big,
then where it is and what it plays, from the list here, which the ROM
draws whatever the middle shows; and at its foot, while no station is
tuned in, what changes the station. With a station tuned in
in the second mode, what it is playing takes the middle, a page the
nesp32 makes of the titles in its stream (tools/gen_news.py says where,
and how). screen.bin is the nametable and its attributes with all
of that on it; screen.inc tells the ROM where the status line is, holds
what it may say, and the stations.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "jukebox", "tools"))
sys.path.insert(0, HERE)

import gen_news  # noqa: E402
import gen_ui  # noqa: E402
import pcm  # noqa: E402

SUBTITLE = "NESRADIO"
# The status line: as wide as what the nesp32 may say of a station that
# failed (NESP_TUNER_TEXT_MAX), which the ROM writes there as it comes.
STATUS_ROW = 8
STATUS_WIDTH = 28
STATUS_COLUMN = (gen_ui.SCREEN_COLUMNS - STATUS_WIDTH) // 2
# In the order of the ROM's STATUS_* numbers; the one after the last is the
# nesp32's own words.
STATUS_TEXT = (("WAITING", "WAITING FOR LINK"), ("OFF", ""),
               ("NO_WIFI", "NO WI-FI"), ("TUNING", "TUNING"), ("ON_AIR", "ON THE AIR"),
               ("PAUSED", "PAUSED"),
               ("OLD", "UPDATE NESP32"))
# The foot, by the ROM's FOOT_* numbers: the jukebox's menus, and for a
# station A as the way out of it, but for one that is paused, which A plays
# again (the jukebox's pictures of play and pause).
PLAY, PAUSE, A_HELP = gen_ui.PLAY, gen_ui.PAUSE, gen_ui.A_HELP
FOOT_WIDTH, FOOT_COLUMN = gen_ui.FOOT_WIDTH, gen_ui.FOOT_COLUMN
FOOT_TEXT = (("ALONE", "A : PLAY"),                 # the menu of a ROM built by itself
             ("CART", "A : PLAY   SELECT : MENU"),  # the menu, on the cartridge
             ("PLAIN", "A : STOP"),                 # on the air
             ("BACK", "A : STOP   B : BACK"),       # tuning
             ("PAUSED", A_HELP + "   B : BACK"))    # paused
assert all(len(text) <= FOOT_WIDTH for _, text in FOOT_TEXT)
ICONS, icon_pixels = gen_ui.ICONS, gen_ui.icon_pixels
# The quality, over the foot, in the order of the nesp32's modes, which the
# ROM draws with the menu's feet and takes off with the others: Up and
# Down change it. Its rates are NESP_TUNER_RATE's and NESP_TUNER_NEWS_RATE's,
# which the ROM asserts; "k" and "z" are tiles of their own, the font's
# lowercase being its capitals.
QUALITY_ROW = gen_ui.HELP_ROW - 1
QUALITY_RATES = (pcm.PERIODS.index(7), gen_news.RATE)


def khz(rate):
    return "%dkHz" % round(pcm.sample_rate(pcm.PERIODS[rate]) / 1000)


QUALITY = ("UP/DOWN : " + khz(QUALITY_RATES[0]), "UP/DOWN : %s + INFO" % khz(QUALITY_RATES[1]))
QUALITY_WIDTH = max(len(line) for line in QUALITY)
QUALITY_COLUMN = (gen_ui.SCREEN_COLUMNS - QUALITY_WIDTH) // 2
LOWERCASE = {"k": "10 10 12 14 18 14 12", "z": "00 00 1F 02 04 08 1F"}

# The stations, in the menu's order: the letters the middle has big, the FM
# frequency the dial's needle is at (None for one that is only on the
# Internet: no needle), where it is and what it plays, and the address of
# its stream, which must be MP3 (any rate, one channel or two) and may be
# http or https, and sent on elsewhere. The first is the one the nesp32 has
# when it is told none. Frequencies checked 2026-10-24.
STATIONS = (
    ("NPR", None, "WASHINGTON, DC", "NEWS & TALK",
     "https://npr-ice.streamguys1.com/live.mp3"),
    ("WNYC", 93.9, "NEW YORK", "NEWS & TALK", "https://fm939.wnyc.org/wnycfm"),
    ("WQXR", 105.9, "NEW YORK", "CLASSICAL", "https://stream.wqxr.org/wqxr"),
    ("KEXP", 90.3, "SEATTLE", "ECLECTIC", "https://kexp-mp3-128.streamguys1.com/kexp128.mp3"),
    ("KUSC", 91.5, "LOS ANGELES", "CLASSICAL",
     "https://playerservices.streamtheworld.com/api/livestream-redirect/KUSCMP128.mp3"),
    ("BBC", None, "LONDON", "WORLD NEWS", "http://stream.live.vc.bbcmedia.co.uk/bbc_world_service"),
    ("WBGO", 88.3, "NEWARK", "JAZZ", "https://ais-sa8.cdnstream1.com/3629_128.mp3"),
    ("KCLU", 88.3, "THOUSAND OAKS", "NEWS & TALK", "https://kclustream.callutheran.edu/kclump3"),
    ("KUVO", 89.3, "DENVER", "JAZZ", "https://kuvo-ice.streamguys1.com/kuvo-mp3-128"),
    ("PARADISE", None, "PARADISE, CA", "ECLECTIC", "https://stream.radioparadise.com/mp3-128"),
    ("SOMAFM", None, "SAN FRANCISCO", "DOWNTEMPO", "https://ice2.somafm.com/groovesalad-128-mp3"),
)
URL_MAX = 255           # NESP_TUNER_URL_MAX, which the ROM asserts


def on_air(station):
    """The status line for a station that is on the air: which one it is,
    since what it is playing takes the middle of the screen."""
    letters, freq, city, genre, url = station
    return "ON THE AIR: " + letters + (" %.1f" % freq if freq is not None else "")


def where(station):
    letters, freq, city, genre, url = station
    return ("%.1f FM" % freq if freq is not None else "INTERNET") + "  " + city


# The middle: the station's lines, by the row of the middle they are on (the
# big letters' two, where, and what), and on the menu, at its foot, what
# changes the station.
STATION_ROW = 0         # the first of the station's: where the ROM starts again on a turn
STATION_LINES = (0, 1, 3, 5)
HINT_ROW = gen_news.ROWS - 1
HINT = "< / > : CHOOSE STATION"

# The dial: rows of tiles under the status line, and an FM scale across it
# at a tile a megahertz, with a tick each half; the needle is three sprites.
DIAL_ROW = 10           # its top line; then the numbers, the ticks, and its bottom line
DIAL_FIRST, DIAL_LAST = 2, 29       # the lines' columns
SCALE_COLUMN, SCALE_MHZ = 4, 86     # the scale starts at this column at this frequency
SCALE_LAST = 110
LABELS = (88, 92, 96, 100, 104, 108)
NEEDLE_TOP = 8 * DIAL_ROW + 6       # its first line on the screen, and its last
NEEDLE_BOTTOM = 8 * (DIAL_ROW + 3) + 1
NEEDLE_NONE = 0xFF                  # the ROM's needle_x for a station with no frequency
DIAL_COLOR, NEEDLE_COLOR = 2, 1     # in palette 1, and the sprites' 0

# Palettes: the jukebox's text and logo, the dial's and the big letters'
# (red, orange and cream), and the hint's grey; and the needle's red.
PALETTES = (gen_ui.PALETTES[gen_ui.PALETTE_TEXT], (0x16, 0x27, 0x38), (0x00, 0x00, 0x10),
            gen_ui.PALETTES[gen_ui.PALETTE_LOGO])
PALETTE_DIAL, PALETTE_HINT = 1, 2
SPRITE_PALETTES = ((0x16, 0x16, 0x16), (0x16, 0x16, 0x16), (0x16, 0x16, 0x16),
                   (0x16, 0x16, 0x16))
# For the preview: the colors the jukebox's has not.
gen_ui.NES_RGB.setdefault(0x27, (212, 136, 32))
gen_ui.NES_RGB.setdefault(0x38, (228, 196, 144))

# A page for the preview: what the nesp32 makes of a station's title.
SAMPLE = tuple(line.center(gen_news.COLUMNS) for line in
               ("NOW PLAYING", "", "DARK CHISME", "", "", "", "SUFFER LIKE ME"))
assert STATUS_ROW < DIAL_ROW and DIAL_ROW + 4 <= gen_news.NEWS_ROW
assert gen_news.NEWS_ROW % 2 == 0 and gen_news.NEWS_ROW + gen_news.ROWS <= QUALITY_ROW
assert HINT_ROW not in STATION_LINES and len(HINT) <= gen_news.COLUMNS
# The quality's grey is the hint's: the two are in one row of attributes.
assert gen_news.NEWS_ROW + HINT_ROW == QUALITY_ROW - 1 and QUALITY_ROW % 2 == 1


def scale_x(mhz):
    """Where a frequency is on the screen, to the pixel."""
    return 8 * SCALE_COLUMN + int(round(8 * (mhz - SCALE_MHZ)))


def areas():
    """What the middle of the screen may show, as lines of text: the menu,
    and nothing, which a station has. The station's own lines are the
    ROM's, from station_rows."""
    menu = [""] * gen_news.ROWS
    menu[HINT_ROW] = HINT.center(gen_news.COLUMNS)
    out = [menu, [""] * gen_news.ROWS]
    for lines in out:
        assert all(len(line) <= gen_news.COLUMNS for line in lines)
    return out


def pixels(width, height):
    return [[0] * width for _ in range(height)]


def tile(rows):
    """A tile from rows of 8 digits, each a color."""
    return [[int(char) for char in row] for row in rows]


LINE_TOP = tile(["00000000"] * 4 + ["22222222"] + ["00000000"] * 3)
LINE_BOTTOM = tile(["00000000"] * 3 + ["22222222"] + ["00000000"] * 4)
TICKS = tile(["00000000"] * 4 + ["20002000"] * 4)
TICKS_MAJOR = tile(["00000000"] + ["20000000"] * 3 + ["20002000"] * 4)
NEEDLE = tile(["00011000"] * 8)
END_ROWS = NEEDLE_BOTTOM - (NEEDLE_TOP + 16) + 1     # of the third sprite
NEEDLE_END = tile(["00011000"] * END_ROWS + ["00000000"] * (8 - END_ROWS))


def lowercase_tile(char):
    """A letter of LOWERCASE, drawn as the font's are."""
    out = gen_ui.empty_tile()
    for y, value in enumerate(LOWERCASE[char].split()):
        for x in range(5):
            if int(value, 16) >> (4 - x) & 1:
                out[y][x + 1] = 3
    return out


def add_tile(screen, pixels8):
    """A tile of its own, not on the screen: its number."""
    data = gen_ui.tile_bytes(pixels8)
    if data not in screen.shared:
        if screen.next_tile > 0xFF:
            raise ValueError("out of background tiles")
        screen.shared[data] = screen.next_tile
        screen.tiles[screen.next_tile] = data
        screen.next_tile += 1
    return screen.shared[data]


def draw_dial(screen):
    top, bottom = add_tile(screen, LINE_TOP), add_tile(screen, LINE_BOTTOM)
    ticks, major = add_tile(screen, TICKS), add_tile(screen, TICKS_MAJOR)
    for column in range(DIAL_FIRST, DIAL_LAST + 1):
        screen.put(column, DIAL_ROW, top)
        screen.put(column, DIAL_ROW + 3, bottom)
    for mhz in range(SCALE_MHZ, SCALE_LAST):
        column = SCALE_COLUMN + mhz - SCALE_MHZ
        screen.put(column, DIAL_ROW + 2, major if mhz in LABELS else ticks)
    for mhz in LABELS:
        # From the column before its tick's: "88" ends on it, "100" is
        # over it to within a few pixels.
        screen.text(SCALE_COLUMN + mhz - SCALE_MHZ - 1, DIAL_ROW + 1, str(mhz))
    screen.palette_rows(DIAL_ROW, DIAL_ROW + 3, PALETTE_DIAL)


def big_rows(screen, letters):
    """A station's letters in the header's big ones, centered in the
    middle: its two lines of tiles. They are drawn on the middle to be given
    numbers, and taken off again."""
    row = gen_news.NEWS_ROW
    column = gen_news.NEWS_COLUMN + (gen_news.COLUMNS - 2 * len(letters)) // 2
    for index, char in enumerate(letters):
        if char != " ":
            screen.picture(column + 2 * index, row, gen_ui.big_letter(char))
    lines = []
    for line in (row, row + 1):
        start = line * gen_ui.SCREEN_COLUMNS + gen_news.NEWS_COLUMN
        lines.append(bytes(screen.names[start:start + gen_news.COLUMNS]))
        screen.names[start:start + gen_news.COLUMNS] = b" " * gen_news.COLUMNS
    return lines


def build_screen():
    screen = gen_ui.Screen()
    screen.names[:] = b" " * len(screen.names)  # the ROM writes text over text
    gen_ui.header(screen, SUBTITLE)
    screen.icons = gen_ui.icon_tiles(screen, FOOT_COLUMN, gen_ui.HELP_ROW)
    draw_dial(screen)
    screen.lowercase = {char: add_tile(screen, lowercase_tile(char)) for char in LOWERCASE}
    screen.needle = (add_tile(screen, NEEDLE), add_tile(screen, NEEDLE_END))
    # The station's lines, by station: its big letters' two, and the two of
    # text, centered.
    screen.station_rows = []
    for station in STATIONS:
        letters, freq, city, genre, url = station
        rows = big_rows(screen, letters)
        rows += [text.center(gen_news.COLUMNS).encode("ascii")
                 for text in (where(station), genre)]
        screen.station_rows.append(rows)
    screen.palette_rows(gen_news.NEWS_ROW, gen_news.NEWS_ROW + 1, PALETTE_DIAL)
    screen.palette_rows(QUALITY_ROW - 1, QUALITY_ROW, PALETTE_HINT)
    return screen


def foot_tiles(text, screen):
    return gen_ui.foot_tiles(text, screen.icons)


def quality_tiles(text, screen):
    """A line of the quality, with the lowercase tiles in it: the two start
    alike, so that Up and Down change only what follows "UP/DOWN :"."""
    return bytes(screen.lowercase.get(char, ord(char)) for char in text.ljust(QUALITY_WIDTH))


def palette_data():
    data = bytearray()
    for colors in PALETTES + SPRITE_PALETTES:
        data += bytes((gen_ui.BACKDROP,) + colors)
    return bytes(data)


def needle_x(station):
    """Where the needle's sprites go across for a station, or NEEDLE_NONE."""
    freq = station[1]
    if freq is None:
        return NEEDLE_NONE
    assert SCALE_MHZ <= freq < SCALE_LAST
    return scale_x(freq) - 3        # its line is the tile's fourth and fifth pixels


def screen_include(screen):
    lines = ["; Generated by tools/gen_screen.py. Do not edit.", "",
             "STATUS_ADDR = $%04X" % gen_ui.address(STATUS_COLUMN, STATUS_ROW),
             "STATUS_WIDTH = %d" % STATUS_WIDTH,
             "FOOT_ADDR = $%04X" % gen_ui.address(FOOT_COLUMN, gen_ui.HELP_ROW),
             "FOOT_WIDTH = %d" % FOOT_WIDTH,
             "QUALITY_ADDR = $%04X" % gen_ui.address(QUALITY_COLUMN, QUALITY_ROW),
             "QUALITY_WIDTH = %d" % QUALITY_WIDTH,
             "QUALITY_HIGH_RATE = %d" % QUALITY_RATES[0],
             "QUALITY_NEWS_RATE = %d" % QUALITY_RATES[1],
             "STATION_ROW = %d          ; of the middle: the station's first" % STATION_ROW,
             "STATIONS = %d" % len(STATIONS),
             "STATION_LINES = %d" % len(STATION_LINES),
             "NEEDLE_NONE = $%02X" % NEEDLE_NONE,
             "NEEDLE_SPRITES = 3"]
    lines += ["FOOT_%s = %d" % (name, index) for index, (name, _) in enumerate(FOOT_TEXT)]
    text = []
    for index, (name, words) in enumerate(STATUS_TEXT):
        if len(words) > STATUS_WIDTH:
            raise ValueError("status text too wide: " + words)
        lines.append("STATUS_%s = %d" % (name, index))
        text += list(words.center(STATUS_WIDTH).encode("ascii"))
    lines += ["STATUS_WHY = %d          ; the nesp32's own words" % len(STATUS_TEXT),
              "", '.segment "RODATA"']
    lines += gen_ui.byte_lines("status_text", text, per_line=STATUS_WIDTH)
    foot = b"".join(foot_tiles(text, screen) for _, text in FOOT_TEXT)
    lines += gen_ui.byte_lines("foot_text", list(foot), per_line=FOOT_WIDTH)
    # Over the foot: the menu's, a line to each mode, and the others' nothing.
    quality = b"".join(quality_tiles(line, screen) for line in QUALITY + ("",))
    lines += gen_ui.byte_lines("quality_text", list(quality), per_line=QUALITY_WIDTH)
    # The middle of the screen: where each of its lines is, in the ROM and
    # on the first nametable.
    middle = []
    for area in areas():
        for line in area:
            middle += list(line.ljust(gen_news.COLUMNS).encode("ascii"))
    count = len(areas()) * gen_news.ROWS
    lines += ["area_lo: .byte " + ", ".join(
                  "<(area_text + %d)" % (index * gen_news.COLUMNS) for index in range(count)),
              "area_hi: .byte " + ", ".join(
                  ">(area_text + %d)" % (index * gen_news.COLUMNS) for index in range(count))]
    places = [gen_ui.address(gen_news.NEWS_COLUMN, gen_news.NEWS_ROW + row)
              for row in range(gen_news.ROWS)]
    lines += ["area_screen_lo: .byte " + ", ".join("$%02X" % (place & 0xFF) for place in places),
              "area_screen_hi: .byte " + ", ".join("$%02X" % (place >> 8) for place in places)]
    lines += gen_ui.byte_lines("area_text", middle, per_line=gen_news.COLUMNS)
    # The station's own lines of the middle: by row of it, which of them
    # ($FF for none), and by station times STATION_LINES plus that, where.
    field = [0xFF] * gen_news.ROWS
    for index, row in enumerate(STATION_LINES):
        field[row] = index
    lines += gen_ui.byte_lines("station_field", field, per_line=gen_news.ROWS)
    count = len(STATIONS) * len(STATION_LINES)
    lines += ["station_row_lo: .byte " + ", ".join(
                  "<(station_rows + %d)" % (index * gen_news.COLUMNS) for index in range(count)),
              "station_row_hi: .byte " + ", ".join(
                  ">(station_rows + %d)" % (index * gen_news.COLUMNS) for index in range(count))]
    rows = b"".join(b"".join(station) for station in screen.station_rows)
    lines += gen_ui.byte_lines("station_rows", list(rows), per_line=gen_news.COLUMNS)
    # The stations' addresses, and the needle: where it goes across, and its
    # three sprites' lines and tiles, top to bottom.
    for index, station in enumerate(STATIONS):
        url = station[4]
        assert len(url) <= URL_MAX
        lines += ["station_url_%d: .byte \"%s\"" % (index, url)]
    for label, part in (("station_url_lo", "<"), ("station_url_hi", ">")):
        lines.append(label + ": .byte " + ", ".join(
            "%s(station_url_%d)" % (part, index) for index in range(len(STATIONS))))
    lines.append("station_url_len: .byte " + ", ".join(
        "%d" % len(station[4]) for station in STATIONS))
    # The status line on the air, by station, as wide as the line.
    for index, station in enumerate(STATIONS):
        text = on_air(station)
        assert len(text) <= STATUS_WIDTH
        lines.append("station_on_air_%d: .byte \"%s\"" % (index, text.center(STATUS_WIDTH)))
    for label, part in (("station_on_air_lo", "<"), ("station_on_air_hi", ">")):
        lines.append(label + ": .byte " + ", ".join(
            "%s(station_on_air_%d)" % (part, index) for index in range(len(STATIONS))))
    lines.append("needle_x: .byte " + ", ".join(
        "$%02X" % needle_x(station) for station in STATIONS))
    tops = [NEEDLE_TOP + 8 * index - 1 for index in range(3)]     # OAM's Y is a line early
    lines.append("needle_sprite_y: .byte " + ", ".join("%d" % top for top in tops))
    needle, end = screen.needle
    lines.append("needle_sprite_tile: .byte $%02X, $%02X, $%02X" % (needle, needle, end))
    return "\n".join(lines) + "\n"


def preview(screen, station, sprites=True):
    """The screen as rows of RGB, with the needle drawn in, which render()
    leaves out, being a sprite's."""
    rows = gen_ui.render(screen.chr(), screen.nametable(), PALETTES)
    x = needle_x(STATIONS[station])
    if sprites and x != NEEDLE_NONE:
        red = gen_ui.NES_RGB[SPRITE_PALETTES[0][0]]
        for y in range(NEEDLE_TOP, NEEDLE_BOTTOM + 1):
            rows[y][x + 3] = rows[y][x + 4] = red
    return rows


def show_station(screen, station, area):
    """Lay the middle out as the ROM would, on a copy, for the preview."""
    shown = screen.copy()
    for row, text in enumerate(areas()[area]):
        shown.text(gen_news.NEWS_COLUMN, gen_news.NEWS_ROW + row, text)
    for index, row in enumerate(STATION_LINES):
        line = screen.station_rows[station][index]
        start = (gen_news.NEWS_ROW + row) * gen_ui.SCREEN_COLUMNS + gen_news.NEWS_COLUMN
        shown.names[start:start + gen_news.COLUMNS] = line
    return shown


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("out_dir", help="directory for chr.bin, screen.bin, palette.bin "
                                        "and screen.inc")
    parser.add_argument("--preview", help="also write the opening screen as a PNG")
    args = parser.parse_args(argv)
    screen = build_screen()
    os.makedirs(args.out_dir, exist_ok=True)
    gen_ui.write_if_changed(os.path.join(args.out_dir, "chr.bin"), screen.chr())
    gen_ui.write_if_changed(os.path.join(args.out_dir, "screen.bin"), screen.nametable())
    gen_ui.write_if_changed(os.path.join(args.out_dir, "palette.bin"), palette_data())
    gen_ui.write_if_changed(os.path.join(args.out_dir, "screen.inc"),
                            screen_include(screen).encode())
    if args.preview:
        # The menu, with WNYC on the dial and a status line with nothing on it.
        menu = show_station(screen, 1, 0)
        menu.text(FOOT_COLUMN, gen_ui.HELP_ROW, foot_tiles(dict(FOOT_TEXT)["CART"], screen)
                  .decode("latin-1"))
        menu.text(QUALITY_COLUMN, QUALITY_ROW,
                  quality_tiles(QUALITY[0], screen).decode("latin-1"))
        gen_ui.write_png(args.preview, preview(menu, 1))
        # And KEXP playing in the second mode: a page.
        playing = screen.copy()
        playing.centered(STATUS_ROW, on_air(STATIONS[3]))
        playing.text(FOOT_COLUMN, gen_ui.HELP_ROW,
                     foot_tiles(dict(FOOT_TEXT)["PLAIN"], screen).decode("latin-1"))
        for row, text in enumerate(SAMPLE):
            playing.text(gen_news.NEWS_COLUMN, gen_news.NEWS_ROW + row, text)
        base, extension = os.path.splitext(args.preview)
        gen_ui.write_png(base + "-news" + extension, preview(playing, 3))
    return 0


if __name__ == "__main__":
    sys.exit(main())
