#!/usr/bin/env python3
"""Write the test ROM's font and the screen it shows before a Stick answers.

    tools/gen_screen.py build

chr.bin holds the jukebox's 5 x 7 font (../tools/gen_ui.py) with each
character at its ASCII code, so the Stick sends plain text to draw. The font
has capitals only; small letters get the capitals' shapes. screen.bin is the
nametable and its attributes: the title, and a line that the Stick's first
draw replaces.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
sys.path.insert(0, os.path.join(HERE, "..", "stick"))

import gen_ui  # noqa: E402
from linktest import tester  # noqa: E402

COLUMNS, ROWS = 32, 30
TITLE = "N-ESP-32 THROUGHPUT TEST"
WAITING = "WAITING FOR THE STICK"
TITLE_PALETTE = 0x55            # palette 1 for the top four rows of tiles


def chr_data():
    data = bytearray(0x2000)
    for code in range(0x20, 0x7F):
        data[code * 16:code * 16 + 16] = gen_ui.tile_bytes(gen_ui.font_tile(chr(code)))
    return bytes(data)


def screen_data():
    tiles = bytearray(b" " * (COLUMNS * ROWS))

    def text(row, column, string):
        tiles[row * COLUMNS + column:row * COLUMNS + column + len(string)] = string.encode()

    text(tester.TITLE_ROW, (COLUMNS - len(TITLE)) // 2, TITLE)
    text(tester.STATE_ROW, tester.LEFT, WAITING)
    attributes = bytes([TITLE_PALETTE] * 8 + [0] * 56)
    return bytes(tiles) + attributes


def main(argv):
    gen_ui.write_if_changed(os.path.join(argv[1], "chr.bin"), chr_data())
    gen_ui.write_if_changed(os.path.join(argv[1], "screen.bin"), screen_data())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
