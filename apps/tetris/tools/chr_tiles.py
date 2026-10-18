#!/usr/bin/env python3
"""The two-player game's tiles, put into the netplay ROM's CHR.

The two-player screen (net/twoplayer_game.nam) has a few tiles of its
own: the joins of its frames, where the original's screen has none. They
are TAUS's (github.com/ejona86/taus, MIT), and net/twoplayer.chr is its
twoplayer.chr: 16 bytes a tile. Each goes in place of a tile of the game's
tileset that the game does not use. The original's CHR is left as it is.

    chr_tiles.py TETRIS.chr TWOPLAYER.chr OUT.chr
"""

import sys

TILE = 16
GAME_TILESET = 3 * 0x1000       # the fourth 4 KB of tetris.chr: the game's
# The tile of twoplayer.chr, and the tile of the game's tileset it replaces,
# as TAUS's twoplayer-CHR-01.chr.ips.s has them (next piece at the side).
TILES = {0x00: 0x8C, 0x01: 0x8D, 0x02: 0x9C, 0x03: 0x9D, 0x04: 0x76, 0x05: 0x86}


def main():
    chr_path, tiles_path, out_path = sys.argv[1:4]
    chr_data = bytearray(open(chr_path, "rb").read())
    tiles = open(tiles_path, "rb").read()
    for source, target in TILES.items():
        at = GAME_TILESET + target * TILE
        chr_data[at:at + TILE] = tiles[source * TILE:(source + 1) * TILE]
    open(out_path, "wb").write(chr_data)


if __name__ == "__main__":
    main()
