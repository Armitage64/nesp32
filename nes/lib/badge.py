"""The Bluetooth keyboard's badge: the rune in white on a round badge whose
colour says how the keyboard stands (nes/lib/badge.inc). The cartridge's
menu and the setup ROM both show it, at the top right.

It is 16 x 16, four sprites in sprite palette 1, and the same upside down,
so two tiles are all it needs: the bottom two sprites are the top two
flipped. X is the palette's colour 1, # its colour 3.
"""

TOP = (
    "....XXXXXXXX....",
    "..XXXXXXXXXXXX..",
    ".XXXXXX#XXXXXXX.",
    ".XXXXXX##XXXXXX.",
    "XXXXXXX#X#XXXXXX",
    "XXXX#XX#XX#XXXXX",
    "XXXXX#X#X#XXXXXX",
    "XXXXXX###XXXXXXX",
)
PICTURE = TOP + TOP[::-1]

# Tiles that no text or picture has: the font's DEL and its DEL in the
# second colour (gen_screen.py's font is $20 to $7E).
TILES = (0x7F, 0xFF)

X, Y = 224, 16                      # tile column 28, row 2: inside a TV's picture

COLORS = {                          # colour 1, by how the keyboard stands
    "GREY": 0x00,                   # paired, and not connected
    "YELLOW": 0x28,                 # the pairing failed, or the nesp32 does not answer
    "BLUE": 0x21,                   # connected, and connecting, flashing with
    "BLUE_DIM": 0x01,               # this
}
PALETTE = (COLORS["BLUE"], 0x10, 0x30)


def tiles():
    """The two tiles' pixels, the left half's and the right's, as rows of
    colour numbers."""
    pixels = [[{"X": 1, "#": 3}.get(char, 0) for char in row] for row in TOP]
    return [[row[8 * half:8 * half + 8] for row in pixels] for half in (0, 1)]


def constants():
    """(name, value) for the ROM's include."""
    out = [("BADGE_X", X), ("BADGE_Y", Y),
           ("BADGE_TILE_LEFT", "$%02X" % TILES[0]), ("BADGE_TILE_RIGHT", "$%02X" % TILES[1])]
    out += [("BADGE_" + name, "$%02X" % color) for name, color in COLORS.items()]
    return out
