#!/usr/bin/env python3
"""Which pixels of two screenshots differ, as mesen_run.py saves them.

    png_diff.py A.png B.png [--out DIFF.png]

Prints how many pixels differ and the box round them; exits 1 if any do.
--out writes A in gray with the differing pixels in red. Only the Python
standard library: 8-bit RGB or RGBA PNGs, not interlaced, as Mesen writes.
"""

import argparse
import struct
import sys
import zlib


def load(path):
    """(width, height, rows of (r, g, b) tuples) of a PNG."""
    data = open(path, "rb").read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path}: not a PNG")
    i, idat = 8, b""
    while i < len(data):
        n, kind = struct.unpack(">I4s", data[i:i + 8])
        chunk = data[i + 8:i + 8 + n]
        i += 12 + n
        if kind == b"IHDR":
            w, h, depth, colour, _, _, interlace = struct.unpack(">IIBBBBB", chunk)
            if depth != 8 or colour not in (2, 6) or interlace:
                raise ValueError(f"{path}: only 8-bit RGB or RGBA, not interlaced")
        elif kind == b"IDAT":
            idat += chunk
    bpp = 3 if colour == 2 else 4
    raw, stride = zlib.decompress(idat), w * bpp
    rows, prev = [], bytearray(stride)
    for y in range(h):
        kind = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if kind == 1:
                line[x] = (line[x] + a) & 0xFF
            elif kind == 2:
                line[x] = (line[x] + b) & 0xFF
            elif kind == 3:
                line[x] = (line[x] + (a + b) // 2) & 0xFF
            elif kind == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 0xFF
        rows.append([tuple(line[x * bpp:x * bpp + 3]) for x in range(w)])
        prev = line
    return w, h, rows


def diff(a, b):
    """The (x, y) where two loaded pictures differ."""
    if a[:2] != b[:2]:
        raise ValueError(f"sizes differ: {a[0]}x{a[1]} and {b[0]}x{b[1]}")
    return [(x, y) for y, (ra, rb) in enumerate(zip(a[2], b[2]))
            for x, (pa, pb) in enumerate(zip(ra, rb)) if pa != pb]


def save(path, w, h, rows):
    raw = b"".join(b"\0" + bytes(c for px in row for c in px) for row in rows)

    def chunk(kind, body):
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body)))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--out")
    args = ap.parse_args()
    a, b = load(args.a), load(args.b)
    pts = diff(a, b)
    if pts:
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        print(f"{len(pts)} pixels differ, in x {min(xs)}-{max(xs)}, y {min(ys)}-{max(ys)}")
    else:
        print("the same")
    if args.out:
        red = set(pts)
        rows = [[(255, 0, 0) if (x, y) in red else (sum(px) // 9,) * 3
                 for x, px in enumerate(row)] for y, row in enumerate(a[2])]
        save(args.out, a[0], a[1], rows)
    sys.exit(1 if pts else 0)


if __name__ == "__main__":
    main()
