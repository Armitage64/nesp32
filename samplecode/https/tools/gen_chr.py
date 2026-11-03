#!/usr/bin/env python3
"""Generate the HTTPS sample's tiles: the font, each character at its ASCII
code, so the ROM writes text as it is.

    tools/gen_chr.py build

Writes chr.bin into the output directory: 8 KB of CHR ROM. Tile 0 is
blank, and $20-$7F are the jukebox's 5 x 7 font
(../../apps/jukebox/tools/gen_ui.py), whose lowercase letters are its
capitals. Only the first 4 KB, the background's, is used.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "apps", "jukebox", "tools"))
import gen_ui  # noqa: E402


def chr_data():
    data = bytearray(0x2000)
    for code in range(0x21, 0x80):
        data[16 * code:16 * code + 16] = gen_ui.tile_bytes(gen_ui.font_tile(chr(code)))
    return bytes(data)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("out_dir", help="directory for chr.bin")
    args = parser.parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)
    gen_ui.write_if_changed(os.path.join(args.out_dir, "chr.bin"), chr_data())
    return 0


if __name__ == "__main__":
    sys.exit(main())
