"""Playing the game on the simulated console: from the title to a game for
two, and moves after it."""

import random

PAD_A, PAD_B, PAD_SELECT, PAD_START = 0x80, 0x40, 0x20, 0x10
PAD_UP, PAD_DOWN, PAD_LEFT, PAD_RIGHT = 0x08, 0x04, 0x02, 0x01

# OPER_MODE, the game's mode, and in a game its task (the byte after).
MODE_TITLE = 0
MODE_GAME = 1
TASK_PLAYING = 3                # the level under way; 1 its screen of lives

# From power-on the title is up in a few frames; a session starts there.
TITLE_FRAMES = 100
BOOT_TICKS = TITLE_FRAMES
LIVES = "LIVES"                 # Mario's lives, and Luigi's after
KEEP_LIVES = 2                  # what the tests keep them at, and what a game begins with

MOVES = (PAD_RIGHT, PAD_RIGHT | PAD_B, PAD_RIGHT | PAD_A, PAD_RIGHT | PAD_B | PAD_A,
         PAD_LEFT, PAD_LEFT | PAD_A, PAD_A, PAD_B, PAD_DOWN, 0)


def keep_alive(console):
    """Both players kept in lives, so that a long run is not a game over."""
    if console.byte("OPER_MODE") == MODE_GAME:
        lives = console.labels[LIVES]
        console.ram[lives] = console.ram[lives + 1] = KEEP_LIVES


def moves(seed, hold=8):
    """Both players' buttons, changed every `hold` ticks, for ever."""
    rng = random.Random(seed)
    while True:
        pads = (rng.choice(MOVES), rng.choice(MOVES))
        for _ in range(hold):
            yield pads


def playing(console):
    return (console.byte("OPER_MODE") == MODE_GAME
            and console.bus[console.labels["OPER_MODE"] + 1] == TASK_PLAYING)


# The game's letters: 0 to 9, A to Z, its blank, dash and full stop, and the
# title's mushroom.
TILES = {0x24: " ", 0x28: "-", 0xAF: ".", 0xCE: "*"}
TILES.update((digit, str(digit)) for digit in range(10))
TILES.update((0x0A + letter, chr(ord("A") + letter)) for letter in range(26))


def screen_row(console, row):
    """A row of the screen as text, with ? for any other tile."""
    return "".join(TILES.get(tile, "?") for tile in console.tiles(0x2000 + 32 * row, 32))


def screen_text(console):
    return "\n".join(screen_row(console, row) for row in range(30))
