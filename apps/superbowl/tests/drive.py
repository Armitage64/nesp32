"""What the tests need to drive the netplay ROM's menu and read its screen:
River City Ransom's (apps/rcr/tests/drive.py), with Tecmo Super Bowl's
font, whose letters, digits and full stop are at their ASCII codes."""

PAD_A, PAD_B, PAD_SELECT, PAD_START = 0x80, 0x40, 0x20, 0x10
PAD_UP, PAD_DOWN, PAD_LEFT, PAD_RIGHT = 0x08, 0x04, 0x02, 0x01

# The font's tiles as text: its space and blank as spaces, and the menus'
# top and bottom borders, which the menu uses for its marks, as dashes.
TILES = {0x00: " ", 0x20: " ", 0x2E: ".", 0x3A: ":", 0x0D: "-", 0x0F: "-"}
TILES.update((code, chr(code)) for code in range(ord("A"), ord("Z") + 1))
TILES.update((code, chr(code)) for code in range(ord("0"), ord("9") + 1))

MARKER_TILE = 0x00              # the game's menu arrow, from its CHR bank at $1000
HIDDEN = 0xEF

# From the power on: the intro's Start, and the title's.
INTRO_FRAMES = 220
TITLE_FRAMES = 200


def screen_row(console, row):
    """A row of the first nametable as text, with ? for any other tile."""
    return "".join(TILES.get(tile, "?") for tile in console.tiles(0x2000 + 32 * row, 32))


def screen_text(console):
    return "\n".join(screen_row(console, row) for row in range(30))


def marker_row(console):
    """The row of text the menu's arrow is beside, or None with none shown."""
    for sprite in range(64):
        y, tile = console.oam[4 * sprite], console.oam[4 * sprite + 1]
        if tile == MARKER_TILE and y < HIDDEN:
            return (y + 1) // 8
    return None


def sram(console, name, offset=0):
    """A byte of the save RAM, whether the game has it on or not."""
    return console.bus.prg_ram[console.labels[name] + offset - 0x6000]
