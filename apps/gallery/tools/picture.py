#!/usr/bin/env python3
"""A picture as the Gallery shows it, from a JPEG or a PNG, without a console.

    tools/picture.py photo.jpg [more.jpg ...] [--out dir]

Each file is made into a picture by the nesp32's own code (COMMONS's,
built for this computer), and that picture drawn as the NES would draw it:
the top half from the first pattern table, the bottom from the second,
with the 2C02's colours. The PNG goes next to the file, or into --out.
"""

import argparse
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from stick import nesp, proto  # noqa: E402

# The 2C02's colours, as picture.c has them.
NES_RGB = [
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
]


def colors(picture):
    """The colour, 0 to 3, and the NES colour of every pixel: rows of
    (index, code)."""
    chr_data = picture[proto.NESP_COMMONS_CHR:proto.NESP_COMMONS_CHR + 0x2000]
    names = picture[proto.NESP_COMMONS_NAMES:proto.NESP_COMMONS_NAMES + 0x400]
    palette = picture[proto.NESP_COMMONS_PALETTE:proto.NESP_COMMONS_PALETTE + 32]
    rows = []
    for y in range(240):
        row = []
        cell_row = y // 8
        table = 0x1000 if cell_row >= proto.NESP_COMMONS_SPLIT_ROW else 0
        for x in range(256):
            tile = names[cell_row * 32 + x // 8]
            planes = chr_data[table + 16 * tile:table + 16 * tile + 16]
            bit = 7 - x % 8
            index = (planes[y % 8] >> bit) & 1 | ((planes[8 + y % 8] >> bit) & 1) << 1
            attribute = names[960 + (y // 32) * 8 + x // 32]
            which = (attribute >> (((y // 16) % 2) * 4 + ((x // 16) % 2) * 2)) & 3
            code = palette[0] if index == 0 else palette[4 * which + index]
            row.append((index, code))
        rows.append(row)
    return rows


def render(picture):
    """Rows of (r, g, b): the picture as the NES draws it."""
    return [[NES_RGB[code & 0x3F] for _, code in row] for row in colors(picture)]


def write_png(path, rows, scale=2):
    """A minimal PNG writer, so this needs no imaging library. The NES's
    pixels are 8/7 as wide as high; this draws them square."""
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("files", nargs="+")
    parser.add_argument("--out", help="directory for the PNGs")
    args = parser.parse_args(argv)
    stick = nesp.Stick()
    for path in args.files:
        with open(path, "rb") as handle:
            picture = stick.picture(handle.read())
        if picture is None:
            print("%s: cannot be read" % path)
            continue
        base = os.path.splitext(os.path.basename(path))[0] + ".nes.png"
        out = os.path.join(args.out or os.path.dirname(path), base)
        write_png(out, render(picture))
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
