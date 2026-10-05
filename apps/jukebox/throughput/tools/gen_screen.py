#!/usr/bin/env python3
"""Write the test ROM's tiles, palette and the screen it shows before a Stick
answers.

    tools/gen_screen.py build
    tools/gen_screen.py build --preview screen.png

All of it is the jukebox's (../tools/gen_ui.py): its 5 x 7 font with each
character at its ASCII code, so the Stick sends plain text to draw, its
palettes, and its header, a name in the big letters over the credit line,
with what this ROM is for between the two in the credit line's blue.
The font has capitals only; small letters get the capitals' shapes.
screen.bin is the nametable and its attributes: the header, and a line that
the Stick's first draw replaces.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
sys.path.insert(0, os.path.join(HERE, "..", "stick"))

import gen_ui  # noqa: E402
from linktest import tester  # noqa: E402

LOGO_ROW = 2
LOGO_TEXT = "N-ESP-32"              # letters 2 x 2 tiles, centered
SUBTITLE_ROW, SUBTITLE_ROWS = 4, 2  # right under the logo, in the 5 x 7 font
SUBTITLE_TOP = 4                    # pixels down those rows that its letters start
SUBTITLE = "THROUGHPUT TEST"
CREDIT_ROW = 6                      # the jukebox's credit line
LOGO_LAST_ROW = 7                   # the logo's palette covers rows 0 to here
LOGO_BLUE = 2                       # that palette's middle blue: the credit's
WAITING = "WAITING"


def font_text(text, width, color):
    """Text in the 5 x 7 font and one color, centered to the pixel in a
    strip `width` pixels wide and SUBTITLE_ROWS tiles high. Text set in
    whole tiles can be half a tile off the logo's middle."""
    pixels = [[0] * width for _ in range(8 * SUBTITLE_ROWS)]
    left = (width - (8 * len(text) - 3)) // 2
    for index, char in enumerate(text):
        for y, row in enumerate(gen_ui.glyph(char)):
            for x, on in enumerate(row):
                if on:
                    pixels[SUBTITLE_TOP + y][left + 8 * index + x] = color
    return pixels


def build_screen():
    screen = gen_ui.Screen()
    screen.names[:] = b" " * len(screen.names)  # the Stick draws text over text
    column = (gen_ui.SCREEN_COLUMNS - 2 * len(LOGO_TEXT)) // 2
    for index, char in enumerate(LOGO_TEXT):
        if char != " ":
            screen.picture(column + 2 * index, LOGO_ROW, gen_ui.big_letter(char))
    screen.picture(0, SUBTITLE_ROW, font_text(SUBTITLE, 8 * gen_ui.SCREEN_COLUMNS, LOGO_BLUE))
    screen.picture(gen_ui.CREDIT_COLUMN, CREDIT_ROW,
                   gen_ui.small_text(gen_ui.CREDIT_TEXT, 8 * gen_ui.CREDIT_TILES, LOGO_BLUE))
    screen.palette_rows(0, LOGO_LAST_ROW, gen_ui.PALETTE_LOGO)
    screen.text(tester.LEFT, tester.STATE_ROW, WAITING)
    return screen


def palette_data():
    data = bytearray()
    for colors in gen_ui.PALETTES:
        data += bytes((gen_ui.BACKDROP,) + colors)
    return bytes(data)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("out_dir", help="directory for chr.bin, screen.bin and palette.bin")
    parser.add_argument("--preview", help="also write the opening screen as a PNG")
    args = parser.parse_args(argv)
    screen = build_screen()
    os.makedirs(args.out_dir, exist_ok=True)
    gen_ui.write_if_changed(os.path.join(args.out_dir, "chr.bin"), screen.chr())
    gen_ui.write_if_changed(os.path.join(args.out_dir, "screen.bin"), screen.nametable())
    gen_ui.write_if_changed(os.path.join(args.out_dir, "palette.bin"), palette_data())
    if args.preview:
        gen_ui.write_png(args.preview, gen_ui.render(screen.chr(), screen.nametable()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
