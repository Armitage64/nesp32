"""nesp32's logo, for the headers of the programs that show it.

The Wi-Fi mark over the controller port and the word, NESP in navy banded
with cyan, 32 in red, all outlined in white: PICTURE, a pixel a character.
'.' is the backdrop, and the rest are colours of two palettes: '1' navy,
'2' cyan and '3' white in the logo's, PALETTE; 'r' red, colour 1 of the
other, whose colour 3 must be white too. The two meet between the P and
the 3, where an attribute's edge is: the red palette is right of RED_LEFT,
over the screen's first RED_ROWS rows.

From the logo art, cut down to 90 x 32. A program's header has it at
ROW, LEFT pixels in, and what the program is under it, at TITLE_ROW in
the logo's cyan.
"""

PICTURE = (
    "............2222222.......................................................................",
    "..........22222222222.....................................................................",
    "........22222.....2222....................................................................",
    ".......2222.........222...................................................................",
    ".......222....222....222..................................................................",
    "......222..22222222...22..................................................................",
    ".......2..2222...2222.....................................................................",
    ".........222.......22.....................................................................",
    ".333333......2222...2.....................................................................",
    "33333333....222222........................................................................",
    "33....333...22...22.......................................................................",
    "33..3..333....22..........................................................................",
    "33.3.3..333...22..........................................................................",
    "33..3....3333.............................................................................",
    "33........3333333...333333.33333333333...33333333..33333333333..33333333333...3333333333..",
    "33.........3333133..3111133311111111133.3111111133331111111113333rrrrrrrrr33333rrrrrrrr33.",
    "33..3...3..33331133.31111133111111111133111111111133111111111133rrrrrrrrrrr333rrrr3rrrrr33",
    "33.3.3.3.3.33331113331111133111131111131111133111133111113111113rrrrr33rrrr333rrrr33rrrr33",
    "33..3...3..33331111331111133111131111131111133111133111113111113rrrrr33rrrr333rrrr33rrrrr3",
    "33.........333311111311111331111331113311111333111331111131111133rrrr33rrrr333rrr333rrrrr3",
    "33.........333311111131111331111333333311111333333331111131111133333333rrrr333333333rrrrr3",
    "33..3...3..33332222322322233222233333.33222223333..3222223222223.3rrrrrrrr33...3333rrrrr33",
    "33.3.3.3.3.33332222332222233222222223..33222222233.3222223222223.3rrrrrrrr33..33rrrrrrr33.",
    "33..3...3..33332222332222233222222223...333332222333222222222233.333333rrr33333rrrr33333..",
    "33.........33332222332222233222233333....3333322223322222233333..333333rrrr333rrrr33333...",
    "33.........333322223322221332222333333333333332222331222233....333333.3rrrr33rrrrr33333333",
    "33..3...3..33331111331111133111133111131111133111133111113.....3rrrr333rrrr33rrrrr33rrrrr3",
    "33.3.3.3.3.33331111331111133111131111131111133111133111113.....3rrrrr33rrrr33rrrrr33rrrrr3",
    "33..3...3..33331111331111133111131111131111131111133111113.....3rrrrr33rrrr33rrrrr33rrrrr3",
    "33.........33331111331111133111111111131111111111333111113.....33rrrr3rrrr333rrrrrrrrrrr33",
    "33333333333333311113311113331111111113331111111133.3111133......33rrrrrrr33.33rrrrrrrrr33.",
    ".333333333333.333333333333.33333333333.3333333333..333333........333333333...33333333333..",
)
WIDTH, HEIGHT = len(PICTURE[0]), len(PICTURE)

ROW, ROWS = 1, 4                # rows of tiles: the picture is all four high
LEFT = 81                       # pixels from the left: the word centered
RED_LEFT = 144                  # pixels from the left that the red palette starts
RED_ROWS = 6                    # and the rows of tiles it covers, from the top
TITLE_ROW = 6
NAVY, CYAN, WHITE, RED = 1, 2, 3, 1     # the colours, in their palettes
PALETTE = (0x01, 0x2C, 0x30)

assert all(len(row) == WIDTH for row in PICTURE) and HEIGHT == 8 * ROWS
assert RED_LEFT % 16 == 0 and RED_ROWS % 2 == 0


def is_red(row, column):
    """Whether a tile of the screen is under the red palette."""
    return row < RED_ROWS and 8 * column >= RED_LEFT


def pixels(width=256):
    """The picture as rows of colours, `width` pixels wide and placed LEFT
    pixels in: ROWS tiles high from ROW."""
    out = [[0] * width for _ in range(HEIGHT)]
    for y, row in enumerate(PICTURE):
        for x, char in enumerate(row):
            if char == ".":
                continue
            if char in "2r" and (char == "r") != is_red(ROW + y // 8, (LEFT + x) // 8):
                raise ValueError("the logo's %s at (%d, %d) is under the other palette"
                                 % ("red" if char == "r" else "cyan", x, y))
            out[y][LEFT + x] = RED if char == "r" else int(char)
    return out
