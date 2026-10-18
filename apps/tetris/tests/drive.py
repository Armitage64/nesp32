"""Getting a Console to where a test starts, and playing it from there."""

import random

from console import PAD_A, PAD_B, PAD_DOWN, PAD_LEFT, PAD_RIGHT, PAD_SELECT, PAD_START

GAME_MODE = 0xC0                # gameMode
PLAYERS = 0xBE                  # numberOfPlayers
GAME_TYPE = 0xC1                # gameType
FRAME_COUNTER = 0xB1            # frameCounter
PLAY_STATE = (0x68, 0x88)       # player1_playState, player2_playState
HELD = (0xF7, 0xF8)             # heldButtons_player1, heldButtons_player2
PLAYFIELD = (0x400, 0x500)
PLAYFIELD_SIZE = 200
EMPTY = 0xEF                    # tileEmpty
MODE_LEGAL, MODE_TITLE, MODE_TYPE_MENU, MODE_LEVEL_MENU, MODE_PLAY = range(5)
# The legal screen can be passed with Start once it has stood this long.
LEGAL_FRAMES = 270
BOOT_FRAMES = LEGAL_FRAMES + 30
MOVES = (0, 0, PAD_LEFT, PAD_RIGHT, PAD_DOWN, PAD_A, PAD_B)


def press(console, pad1=0, pad2=0, hold=3, rest=10):
    console.run(hold, pads=(pad1, pad2))
    console.run(rest, pads=(0, 0))


def to_title(console):
    console.run(LEGAL_FRAMES)
    press(console, PAD_START, rest=27)
    assert console.ram[GAME_MODE] == MODE_TITLE


def to_level_menu(console):
    """From the game type menu, on its defaults."""
    assert console.ram[GAME_MODE] == MODE_TYPE_MENU
    press(console, PAD_START, rest=30)
    assert console.ram[GAME_MODE] == MODE_LEVEL_MENU


def to_one_player_game(console):
    to_title(console)
    press(console, PAD_START, rest=30)
    to_level_menu(console)
    press(console, PAD_START, rest=30)
    assert console.ram[GAME_MODE] == MODE_PLAY


def to_two_player_game(console):
    """The netplay ROM, from power-on to a game for two on this console:
    2 PLAYERS on the title, and LOCAL GAME on the menu."""
    to_title(console)
    press(console, PAD_DOWN)
    press(console, PAD_START, rest=30)
    press(console, PAD_DOWN)
    press(console, PAD_DOWN)
    press(console, PAD_A, rest=60)
    assert console.ram[PLAYERS] == 2
    to_level_menu(console)
    press(console, PAD_START, rest=30)      # player 1's level, and then
    assert banner(console) == 2
    press(console, 0, PAD_START, rest=60)   # player 2's
    assert console.ram[GAME_MODE] == MODE_PLAY


# The level menu's top line in a game for two: "PLAYER 1" or "PLAYER 2".
BANNER = 0x20A4 + 8
PLAYER_TILES = bytes((0x19, 0x15, 0x0A, 0x22, 0x0E, 0x1B, 0xFF))


def banner(console):
    """Whose level the level menu is asking for, or None."""
    tiles = console.tiles(BANNER, 8)
    if tiles[:7] != PLAYER_TILES:
        return None
    return tiles[7]


def moves(seed):
    """An endless run of (pad 1, pad 2), a new pair every frame."""
    rng = random.Random(seed)
    while True:
        yield rng.choice(MOVES), rng.choice(MOVES)


# The menu's font: the tiles of the game's title and menus.
TILES = dict((index, character) for index, character in
             enumerate("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
TILES.update({0x24: "-", 0x27: ">", 0x6F: ".", 0xF3: " "})


def screen_row(console, row):
    """A row of the menu's screen as text, with ? for any other tile."""
    return "".join(TILES.get(tile, "?") for tile in console.tiles(0x2000 + 32 * row, 32))


def screen_text(console):
    return "\n".join(screen_row(console, row) for row in range(30))
