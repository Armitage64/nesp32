#!/usr/bin/env python3
"""Cut the game's graphics and sound out of baserom.nes, as build.sh does.

    extract_assets.py BASEROM ASSETS_LIST DIRECTORY

Each line of the list is a file, where it starts in the ROM and how long it
is; the files are made under the directory. A file that is already there
with the right length is left alone.
"""

import os
import sys


def main(rom_path, list_path, root):
    with open(rom_path, "rb") as handle:
        rom = handle.read()
    with open(list_path) as handle:
        for line in handle:
            if not line.strip():
                continue
            name, start, length = line.split()
            path = os.path.join(root, *name.split("\\"))
            start, length = int(start), int(length)
            if os.path.isfile(path) and os.path.getsize(path) == length:
                continue
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as out:
                out.write(rom[start:start + length])


if __name__ == "__main__":
    main(*sys.argv[1:])
