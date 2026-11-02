#!/usr/bin/env python3
"""Generate the lobby sample's tiles, its session screen and the table of
where each button's sprites go.

    tools/gen_chr.py build
    tools/gen_chr.py build --preview docs/screen.png

Writes into the output directory:

    chr.bin       8 KB of CHR ROM. Tile 0 is blank, $20-$7F are the font at
                  their ASCII codes (the jukebox's 5 x 7 font, in
                  ../../apps/jukebox/tools/gen_ui.py), and $80 on are the
                  controller's. Background and sprites share the one table.
    session.bin   the session screen's nametable and attributes: a title,
                  and a controller for each player with its label
    layout.inc    for nes/pads.inc: each button's sprites, and where the
                  ROM writes "YOU"

The controller is drawn here as a picture: its outline, the buttons in
dark grey, and their names. Each button is whole tiles, the same tiles a
sprite lights in red when it is pressed. So the layout is in this file
alone: move a button here and the ROM's sprites move with it.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "apps", "jukebox", "tools"))
import gen_ui  # noqa: E402

COLUMNS, ROWS = 32, 30
TILE_BLANK = 0x00
TILE_FIRST = 0x80               # the controller's tiles, as many as it needs

TITLE_ROW = 2
TITLE = "NESP32 LOBBY SAMPLE"
# Each player's controller, by its top left tile, with a label above it
# and "YOU" after the label on the console that player is at.
PADS = ((4, 7), (4, 19))        # (column, row) of player 1's, then player 2's
LABEL_ROWS_ABOVE = 2
YOU_COLUMN = 13
PAD_COLUMNS, PAD_ROWS = 24, 6

# The buttons, in the order the controller is read (bit 7 first), each as
# the tiles it covers, (column, row) inside the controller. No scanline
# may cross more than 8 sprites: B, A and the D-pad's middle row make 6.
BUTTONS = (
    ("A", ((21, 1), (22, 1), (21, 2), (22, 2))),
    ("B", ((18, 1), (19, 1), (18, 2), (19, 2))),
    ("SELECT", ((8, 3), (9, 3))),
    ("START", ((14, 3), (15, 3))),
    ("UP", ((3, 1),)),
    ("DOWN", ((3, 3),)),
    ("LEFT", ((2, 2),)),
    ("RIGHT", ((4, 2),)),
)
DPAD_MIDDLE = (3, 2)            # dark, and never lit
LABEL_ROW = 4                   # the names under the buttons
LABELS = ("A", "B", "SELECT", "START")

# Colours: 1 the buttons (dark grey, red as a sprite), 2 the outline, 3
# the names and the font.
DARK, OUTLINE, WHITE = 1, 2, 3
BACKGROUND_PALETTE = (0x00, 0x10, 0x30)
SPRITE_PALETTE = (0x16, 0x27, 0x30)
BACKDROP = 0x0F


def blank(width, height):
    return [[0] * width for _ in range(height)]


def fill_cell(pixels, column, row, shape):
    """One 8 x 8 cell of a button, from rows of '#' and '.'."""
    for y, line in enumerate(shape):
        for x, char in enumerate(line):
            if char == "#":
                pixels[8 * row + y][8 * column + x] = DARK


SQUARE = ["########"] * 8
PILL = ["................", "................", ".##############.", "################",
        "################", ".##############.", "................", "................"]


def round_button(pixels, cells):
    """A circle across a button's 2 x 2 cells."""
    left = 8 * min(column for column, _ in cells)
    top = 8 * min(row for _, row in cells)
    for y in range(16):
        for x in range(16):
            if (x - 7.5) ** 2 + (y - 7.5) ** 2 <= 7.2 ** 2:
                pixels[top + y][left + x] = DARK


def pill(pixels, cells):
    """A rounded bar across a button's 1 x 2 cells."""
    column, row = cells[0]
    for y, line in enumerate(PILL):
        for x, char in enumerate(line):
            if char == "#":
                pixels[8 * row + y][8 * column + x] = DARK


def outline(pixels):
    """The controller's edge: a rounded rectangle two pixels thick."""
    width, height, radius = len(pixels[0]), len(pixels), 6
    for y in range(height):
        for x in range(width):
            dx = max(radius - x, x - (width - 1 - radius), 0)
            dy = max(radius - y, y - (height - 1 - radius), 0)
            distance = (dx * dx + dy * dy) ** 0.5
            if radius - 2 < distance <= radius or (dx == 0 and (y < 2 or y >= height - 2)) \
                    or (dy == 0 and (x < 2 or x >= width - 2)):
                pixels[y][x] = OUTLINE


def label(pixels, text, middle, row):
    """A button's name in the 5 x 7 font, centred under it to the pixel."""
    left = middle - (6 * len(text) - 1) // 2
    for index, char in enumerate(text):
        for y, line in enumerate(gen_ui.glyph(char)):
            for x, on in enumerate(line):
                if on:
                    pixels[8 * row + 1 + y][left + 6 * index + x] = WHITE


def controller():
    pixels = blank(8 * PAD_COLUMNS, 8 * PAD_ROWS)
    outline(pixels)
    fill_cell(pixels, *DPAD_MIDDLE, SQUARE)
    for name, cells in BUTTONS:
        if len(cells) == 4:
            round_button(pixels, cells)
        elif len(cells) == 2:
            pill(pixels, cells)
        else:
            fill_cell(pixels, *cells[0], SQUARE)
        if name in LABELS:
            middle = 4 * (min(c for c, _ in cells) + max(c for c, _ in cells)) + 4
            label(pixels, name, middle, LABEL_ROW)
    return pixels


class Screen:
    """The tile set and the session screen's nametable."""

    def __init__(self):
        self.tiles = {TILE_BLANK: gen_ui.tile_bytes(gen_ui.empty_tile())}
        for code in range(0x21, 0x80):
            self.tiles[code] = gen_ui.tile_bytes(gen_ui.font_tile(chr(code)))
        self.tiles[0x20] = self.tiles[TILE_BLANK]
        self.index = {}             # tile bytes -> tile number, for the picture
        self.names = bytearray([TILE_BLANK]) * (COLUMNS * ROWS)

    def text(self, column, row, text):
        for offset, char in enumerate(text):
            self.names[row * COLUMNS + column + offset] = ord(char)

    def picture(self, column, row, pixels):
        for dy, tiles in enumerate(gen_ui.cut_tiles(pixels)):
            for dx, tile in enumerate(tiles):
                data = gen_ui.tile_bytes(tile)
                if data == self.tiles[TILE_BLANK]:
                    continue
                if data not in self.index:
                    number = TILE_FIRST + len(self.index)
                    if number > 0xFF:
                        raise ValueError("out of tiles")
                    self.index[data] = number
                    self.tiles[number] = data
                self.names[(row + dy) * COLUMNS + column + dx] = self.index[data]

    def tile_at(self, column, row):
        return self.names[row * COLUMNS + column]

    def chr(self):
        data = bytearray(0x2000)
        for number, tile in self.tiles.items():
            data[16 * number:16 * number + 16] = tile
        return bytes(data)

    def nametable(self):
        return bytes(self.names) + bytes(64)    # one palette for all of it


def build():
    screen = Screen()
    screen.text((COLUMNS - len(TITLE)) // 2, TITLE_ROW, TITLE)
    pixels = controller()
    for player, (column, row) in enumerate(PADS):
        screen.text(column, row - LABEL_ROWS_ABOVE, "PLAYER %d" % (player + 1))
        screen.picture(column, row, pixels)
    return screen


def sprites(screen):
    """Player 1's sprites, a row each: (the button's bit, x, OAM's y, tile)."""
    column, row = PADS[0]
    out = []
    for bit, (_, cells) in zip(range(7, -1, -1), BUTTONS):
        for dx, dy in cells:
            tile = screen.tile_at(column + dx, row + dy)
            out.append((1 << bit, 8 * (column + dx), 8 * (row + dy) - 1, tile))
    return out


def layout_include(screen):
    rows = sprites(screen)
    lines = ["; Generated by tools/gen_chr.py. Do not edit.", "",
             "PAD_SPRITES = %d               ; a controller's" % len(rows),
             "PAD2_DY = %d                   ; pixels from player 1's to player 2's"
             % (8 * (PADS[1][1] - PADS[0][1])), ""]
    for player, (column, row) in enumerate(PADS):
        place = 0x2000 + (row - LABEL_ROWS_ABOVE) * COLUMNS + YOU_COLUMN
        lines.append("YOU_%d = $%04X                  ; where \"YOU\" goes" % (player + 1, place))
    lines.append("")
    lines.append("; Player 1's sprites, by the button that lights each. OAM's y is the")
    lines.append("; line above the sprite's first.")
    for name, index in (("pad_mask", 0), ("pad_x", 1), ("pad_y", 2), ("pad_tile", 3)):
        lines.append("%s: .byte %s" % (name, ", ".join("$%02X" % row[index] for row in rows)))
    lines.append("")
    lines.append("background_palette: .byte $%02X, %s" % (
        BACKDROP, ", ".join("$%02X" % colour for colour in BACKGROUND_PALETTE)))
    lines.append("sprite_palette: .byte $%02X, %s" % (
        BACKDROP, ", ".join("$%02X" % colour for colour in SPRITE_PALETTE)))
    return "\n".join(lines) + "\n"


def preview(screen, path, lit=("A", "UP")):
    """The session screen as a PNG, with a few of player 1's buttons lit."""
    rgb = dict(gen_ui.NES_RGB)
    rgb.setdefault(0x27, (228, 92, 16))
    palettes = (BACKGROUND_PALETTE,) * 4
    rows = gen_ui.render(screen.chr(), screen.nametable(), palettes=palettes, backdrop=BACKDROP)
    chr_data = screen.chr()
    column, row = PADS[0]
    for name, cells in BUTTONS:
        if name not in lit:
            continue
        for dx, dy in cells:
            tile = screen.tile_at(column + dx, row + dy)
            planes = chr_data[16 * tile:16 * tile + 16]
            for y in range(8):
                for x in range(8):
                    colour = (planes[y] >> (7 - x) & 1) | (planes[8 + y] >> (7 - x) & 1) << 1
                    if colour:
                        rows[8 * (row + dy) + y][8 * (column + dx) + x] = \
                            rgb[SPRITE_PALETTE[colour - 1]]
    gen_ui.write_png(path, rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("out_dir", help="directory for chr.bin, session.bin and layout.inc")
    parser.add_argument("--preview", help="also write the session screen as a PNG")
    args = parser.parse_args(argv)
    screen = build()
    os.makedirs(args.out_dir, exist_ok=True)
    gen_ui.write_if_changed(os.path.join(args.out_dir, "chr.bin"), screen.chr())
    gen_ui.write_if_changed(os.path.join(args.out_dir, "session.bin"), screen.nametable())
    gen_ui.write_if_changed(os.path.join(args.out_dir, "layout.inc"),
                            layout_include(screen).encode("ascii"))
    if args.preview:
        preview(screen, args.preview)
    return 0


if __name__ == "__main__":
    sys.exit(main())
