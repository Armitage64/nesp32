#!/usr/bin/env python3
"""How near the Gallery's pictures are to the photographs they are made from.

    tools/quality.py photo.jpg ... [--montage out.png]
    tools/quality.py --fetch dir [words ...]

Each photograph is made into a picture by the nesp32's own code (COMMONS's,
built for this computer), and the two compared as an eye a little way off
sees them: both blurred a little (which takes dithering for the colour it
makes), then the distance between them in the converter's colour space
(luma, and the two colour differences counted 1.5 times), averaged over the
lines a picture may use. Lower is better. "Blotches" is the share of
pixels more than 40 off: a wrong colour, not just a coarse one.

--montage draws each photograph beside its picture. --fetch saves the
first thumbnail Commons finds for each of some words into a directory, as
COMMONS would fetch it, to compare on; Commons answers too many requests
in a row with 429, so it waits between them. The photographs are their
authors', under their licences: keep them out of the repository.

Used to choose picture.c's figures, on twelve photographs: from 12.5 to
9.3 with tiles compared as the eye sees them, places choosing their tiles
from the image, and colour counting more.
"""

import argparse
import json
import math
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from picture import render, write_png  # noqa: E402
from stick import nesp  # noqa: E402

WIDTH, HEIGHT = 256, 240
TOP, BOTTOM = 8, 232            # the lines a picture may use
SIGMA = 1.0
FAR = 40.0
TOPICS = ("red fox", "portrait", "sunset", "strawberries", "night city", "parrot",
          "mountain lake", "cat", "fireworks", "lighthouse", "star trails", "forest")


def space(r, g, b):
    y = 0.299 * r + 0.587 * g + 0.114 * b
    return (y, 1.5 * (-0.168736 * r - 0.331264 * g + 0.5 * b),
            1.5 * (0.5 * r - 0.418688 * g - 0.081312 * b))


def blurred(rows):
    """Rows of (r, g, b) blurred by a Gaussian, as rows of colours in space()."""
    radius = 3
    kernel = [math.exp(-x * x / (2 * SIGMA * SIGMA)) for x in range(-radius, radius + 1)]
    total = sum(kernel)
    kernel = [k / total for k in kernel]
    height, width = len(rows), len(rows[0])
    image = [[space(*pixel) for pixel in row] for row in rows]

    def along(get, length, at):
        out = [0.0, 0.0, 0.0]
        for offset, k in enumerate(kernel):
            v = get(min(max(at + offset - radius, 0), length - 1))
            out[0] += k * v[0]
            out[1] += k * v[1]
            out[2] += k * v[2]
        return out

    across = [[along(lambda x, row=row: row[x], width, x) for x in range(width)] for row in image]
    return [[along(lambda y, x=x: across[y][x], height, y) for x in range(width)]
            for y in range(height)]


def score(target, picture):
    """(mean distance, share of blotches in percent)."""
    a, b = blurred(target), blurred(picture)
    distances = [math.dist(a[y][x], b[y][x]) for y in range(TOP, BOTTOM) for x in range(WIDTH)]
    return (sum(distances) / len(distances),
            100.0 * sum(1 for d in distances if d > FAR) / len(distances))


def fetch(directory, words):
    os.makedirs(directory, exist_ok=True)
    agent = {"User-Agent": "nesp32-gallery-quality/0.1"}
    for each in words:
        url = nesp.commons_url(each.encode())
        with urllib.request.urlopen(urllib.request.Request(url, headers=agent)) as reply:
            pages = sorted(json.load(reply).get("query", {}).get("pages", []),
                           key=lambda page: page["index"])
        if not pages:
            print("%s: nothing found" % each)
            continue
        thumb = pages[0]["imageinfo"][0]["thumburl"].split("?")[0]
        with urllib.request.urlopen(urllib.request.Request(thumb, headers=agent)) as reply:
            data = reply.read()
        path = os.path.join(directory, each.replace(" ", "_") + ".jpg")
        with open(path, "wb") as handle:
            handle.write(data)
        print("%s: %s" % (path, pages[0]["title"]))
        time.sleep(3)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("files", nargs="*")
    parser.add_argument("--montage", help="a PNG of each photograph beside its picture")
    parser.add_argument("--fetch", help="save Commons's first thumbnail for each word here")
    args = parser.parse_args(argv)
    if args.fetch:
        fetch(args.fetch, args.files or TOPICS)
        return 0
    stick = nesp.Stick()
    scores = []
    montage = []
    for path in args.files:
        with open(path, "rb") as handle:
            data = handle.read()
        made = stick.picture(data)
        if made is None:
            print("%s: cannot be read" % path)
            continue
        flat = stick.picture_target(data)
        target = [[tuple(flat[(y * WIDTH + x) * 3:(y * WIDTH + x) * 3 + 3]) for x in range(WIDTH)]
                  for y in range(HEIGHT)]
        picture = render(made)
        distance, blotches = score(target, picture)
        scores.append(distance)
        print("%-30s %6.2f   blotches %5.2f%%" % (os.path.basename(path)[:30], distance, blotches))
        if args.montage:
            montage += [t + [(255, 255, 255)] * 4 + p for t, p in zip(target, picture)]
            montage += [[(255, 255, 255)] * (2 * WIDTH + 4)] * 4
    if scores:
        print("mean %.2f over %d" % (sum(scores) / len(scores), len(scores)))
    if args.montage and montage:
        write_png(args.montage, montage, scale=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
