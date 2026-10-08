"""Getting a Console to where a test starts, and playing it from there."""

import random

from console import PAD_A, PAD_B, PAD_DOWN, PAD_LEFT, PAD_RIGHT, PAD_START

GAME_SCRIPT = 0x46              # ram_game_script
PLAYERS = 0x0727                # ram_plr_counter
SCRIPT_LOGO, SCRIPT_OPTIONS = 0, 1
BOOT_FRAMES = 120
MOVES = (0, 0, PAD_LEFT, PAD_RIGHT, PAD_DOWN, PAD_A, PAD_B)


def press(console, pad1=0, pad2=0, hold=3, rest=10):
    console.run(hold, pads=(pad1, pad2))
    console.run(rest, pads=(0, 0))


def to_title(console):
    console.run(BOOT_FRAMES)
    assert console.ram[GAME_SCRIPT] == SCRIPT_LOGO


def to_two_player_game(console, menu=False):
    """From power-on to a two-player game on the options' defaults. The
    netplay ROM has its menu on the way (menu=True): LOCAL GAME is taken."""
    to_title(console)
    press(console, PAD_DOWN)
    assert console.ram[PLAYERS] == 2
    press(console, PAD_START, rest=60)
    if menu:
        assert console.ram[GAME_SCRIPT] == SCRIPT_LOGO
        press(console, PAD_DOWN)
        press(console, PAD_DOWN)
        press(console, PAD_A, rest=60)
    assert console.ram[GAME_SCRIPT] == SCRIPT_OPTIONS
    press(console, PAD_START, rest=120)


def moves(seed):
    """An endless run of (pad 1, pad 2), a new pair every frame."""
    rng = random.Random(seed)
    while True:
        yield rng.choice(MOVES), rng.choice(MOVES)


# The menu's font: the tiles of the game's options screen.
TILES = dict((index, character) for index, character in
             enumerate("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
TILES.update({0x24: "-", 0x27: ">", 0x2A: ".", 0x2B: " "})


def screen_row(console, row):
    """A row of the menu's screen as text, with ? for any other tile."""
    return "".join(TILES.get(tile, "?") for tile in console.tiles(0x2000 + 32 * row, 32))


def screen_text(console):
    return "\n".join(screen_row(console, row) for row in range(30))
