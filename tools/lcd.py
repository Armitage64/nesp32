#!/usr/bin/env python3
"""Pictures of the nesp32's own screen, for trying a layout before flashing it.

    tools/lcd.py out

Draws what firmware/main/main.cpp's draw() would put on the 240x135 LCD for
each program, with the font M5GFX uses (FreeSans9pt7b, from the firmware's
managed components: build the firmware once to have them) and by its rules
for placing and cutting off text. Writes a PNG of each screen, and all.png
with every one of them.

The screens are examples written out below, not the firmware run: change
SCREENS, and line() and split(), along with main.cpp.
"""

import os
import re
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(HERE, "..", "firmware", "managed_components", "m5stack__m5gfx", "src", "lgfx",
                    "Fonts", "GFXFF", "FreeSans9pt7b.h")

WIDTH, HEIGHT, SCALE = 240, 135, 3
BLACK, WHITE, TITLE_BLUE, BEZEL = (0, 0, 0), (255, 255, 255), (0x40, 0xA0, 0xFF), (40, 40, 40)

TITLE = "NESP32 0.1.0"
WIFI = "Wifi: Home Network"
ADDRESS = "192.168.1.77"
REQ = "req: 48213"
PLAYING = ("late frames: 0.2%", REQ + ", ping: 12")

# Each screen's lines under the title. One that is a list is a service's
# single line, which runs on into the next if it is too long.
SCREENS = {
    "waiting": ("NES: waiting", WIFI, ADDRESS, "req: 0"),
    "waiting-no-wifi": ("NES: waiting", "Wifi: not set up", "", "req: 0"),
    "setup": ("NES: Setup", WIFI, ADDRESS, REQ),
    "wiki": ("NES: Wikipedia", WIFI, ADDRESS, REQ),
    "jukebox-long": ("NES: Jukebox", WIFI, ["3/12 Mega Man 2 - Dr. Wily Stage 1"], REQ),
    "jukebox-short": ("NES: Jukebox", WIFI, ["7/12 Contra - Jungle"], REQ),
    "throughput": ("NES: Throughput", WIFI, ADDRESS, REQ),
    "contra-hosting": ("NES: Contra", WIFI, ADDRESS, "Waiting for player 2", REQ),
    "contra-playing": ("NES: Contra", WIFI, "Player 1") + PLAYING,
    "drmario-joining": ("NES: Dr. Mario", WIFI, ADDRESS, "Joining the game", REQ),
    "drmario-playing": ("NES: Dr. Mario", WIFI, "Player 2") + PLAYING,
    "drmario-lost": ("NES: Dr. Mario", WIFI, "Player 2: peer disconnected", PLAYING[0], REQ),
    "converting": ("Converting 3/12",),
    "usb-waiting": ("NES: Setup", WIFI, "USB drive", "Plug into a computer", REQ),
    "usb-mounted": ("NES: Setup", WIFI, "USB drive", "Eject it when done", REQ),
}


class Font:
    """An Adafruit GFX font from its header, with the metrics M5GFX takes from it."""

    def __init__(self, path):
        source = open(path).read()
        bitmaps = source[source.index("Bitmaps[]"):source.index("Glyphs[]")]
        self.bits = bytes(int(byte, 16) for byte in re.findall(r"0x([0-9A-Fa-f]{2})", bitmaps))
        # offset, width, height, advance, x offset, y offset
        self.glyphs = [tuple(int(value) for value in glyph) for glyph in re.findall(
            r"\{\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(-?\d+),\s*(-?\d+)\s*\}", source)]
        self.first = int(re.search(r"0x([0-9A-Fa-f]+),\s*0x[0-9A-Fa-f]+,\s*\d+\s*\};",
                                   source).group(1), 16)
        self.above = max(-glyph[5] for glyph in self.glyphs)
        self.height = self.above + max(glyph[2] + glyph[5] for glyph in self.glyphs)

    def glyph(self, character):
        return self.glyphs[ord(character) - self.first]

    def width(self, text):
        return sum(self.glyph(character)[3] for character in text)


class Screen:
    def __init__(self, font):
        self.font = font
        self.pixels = [[BLACK] * WIDTH for _ in range(HEIGHT)]

    def fill(self, left, top, width, height, colour):
        for y in range(max(top, 0), min(top + height, HEIGHT)):
            for x in range(max(left, 0), min(left + width, WIDTH)):
                self.pixels[y][x] = colour

    def line(self, row, text):
        """main.cpp's line(): the top one is the title, in blue with a rule under it."""
        font = self.font
        height = font.height + 4
        colour = TITLE_BLUE if row == 0 else WHITE
        x, y = 2, row * height + 2
        for character in text:
            offset, width, rows, advance, x_offset, y_offset = font.glyph(character)
            bit = offset * 8
            for i in range(rows):
                for j in range(width):
                    if font.bits[bit >> 3] & (0x80 >> (bit & 7)):
                        self.fill(x + x_offset + j, y + font.above + y_offset + i, 1, 1, colour)
                    bit += 1
            x += advance
        if row == 0:
            self.fill(0, height - 2, WIDTH, 1, TITLE_BLUE)


def split(font, text):
    """main.cpp's split(): a line too long for the screen, as two."""
    fits = len(text)
    while fits > 0 and font.width(text[:fits]) > WIDTH - 2:
        fits -= 1
    if fits == len(text):
        return [text, ""]
    cut = next((at for at in range(fits, 0, -1) if text[at] == " "), fits)
    return [text[:cut], text[cut + (text[cut] == " "):]]


def draw(font, lines):
    screen = Screen(font)
    rows = [TITLE]
    for line in lines:
        rows += split(font, line[0]) if isinstance(line, list) else [line]
    for row, text in enumerate(rows):
        screen.line(row, text)
    return screen


def write_png(path, screens):
    """The screens one above another, each in a grey bezel, scaled up."""
    pad = 8
    width = WIDTH * SCALE + 2 * pad
    edge = bytes(BEZEL) * width
    rows = []
    for screen in screens:
        rows += [edge] * pad
        for line in screen.pixels:
            row = bytes(BEZEL) * pad + b"".join(bytes(pixel) * SCALE for pixel in line) \
                + bytes(BEZEL) * pad
            rows += [row] * SCALE
    rows += [edge] * pad

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    with open(path, "wb") as out:
        out.write(b"\x89PNG\r\n\x1a\n"
                  + chunk(b"IHDR", struct.pack(">IIBBBBB", width, len(rows), 8, 2, 0, 0, 0))
                  + chunk(b"IDAT", zlib.compress(b"".join(b"\0" + row for row in rows), 9))
                  + chunk(b"IEND", b""))


def main(argv):
    if len(argv) != 2:
        sys.exit(__doc__)
    out = argv[1]
    os.makedirs(out, exist_ok=True)
    font = Font(FONT)
    screens = []
    for name, lines in SCREENS.items():
        screens.append(draw(font, lines))
        write_png(os.path.join(out, name + ".png"), screens[-1:])
    write_png(os.path.join(out, "all.png"), screens)


if __name__ == "__main__":
    main(sys.argv)
