#!/usr/bin/env python3
"""A tileset's PNG into NES CHR, with nothing but the standard library.

The disassembly's own encoder (tools/nes-util there) needs Pillow; this
reads the one kind of PNG its gfx/ has, 8-bit greyscale and not
interlaced, 128 pixels wide. The four greys 00, 55, AA and FF are the
colours 0 to 3, as that encoder's default palette has them.

    png2chr.py IN.png OUT.chr
"""

import struct
import sys
import zlib

GREYS = {0x00: 0, 0x55: 1, 0xAA: 2, 0xFF: 3}


def read_png(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        sys.exit("%s: not a PNG" % path)
    pos, idat = 8, b""
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, colour, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if (depth, colour, interlace) != (8, 0, 0):
                sys.exit("%s: only 8-bit greyscale, not interlaced" % path)
        elif kind == b"IDAT":
            idat += body
        pos += 12 + length
    raw = zlib.decompress(idat)
    rows, prior = [], bytearray(width)
    for y in range(height):
        line = raw[y * (width + 1):(y + 1) * (width + 1)]
        kind, row = line[0], bytearray(line[1:])
        for x in range(width):
            a = row[x - 1] if x else 0
            b = prior[x]
            c = prior[x - 1] if x else 0
            if kind == 1:
                row[x] = (row[x] + a) & 0xFF
            elif kind == 2:
                row[x] = (row[x] + b) & 0xFF
            elif kind == 3:
                row[x] = (row[x] + (a + b) // 2) & 0xFF
            elif kind == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                row[x] = (row[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 0xFF
        rows.append(row)
        prior = row
    return width, height, rows


def main():
    source, target = sys.argv[1:3]
    width, height, rows = read_png(source)
    if width != 128 or height % 8:
        sys.exit("%s: 128 pixels wide, a multiple of 8 high" % source)
    out = bytearray()
    for top in range(0, height, 8):
        for left in range(0, width, 8):
            planes = [bytearray(8), bytearray(8)]
            for y in range(8):
                for x in range(8):
                    grey = rows[top + y][left + x]
                    if grey not in GREYS:
                        sys.exit("%s: a grey that is not one of the four" % source)
                    colour = GREYS[grey]
                    for plane in range(2):
                        if colour >> plane & 1:
                            planes[plane][y] |= 0x80 >> x
            out += planes[0] + planes[1]
    with open(target, "wb") as f:
        f.write(out)


if __name__ == "__main__":
    main()
