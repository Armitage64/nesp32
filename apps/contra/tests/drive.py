"""Playing a Console by the game's frames rather than the picture's.

Contra reads the controllers once for each frame of the game. A frame of
the game that overruns takes two of the picture's, and on which frames that
happens is a matter of cycles, so two consoles are compared frame of the
game for frame of the game: a tick. `play` holds each tick's buttons from
before the NMI that reads them, and keeps a digest of the game's memory as
each tick finds it.
"""

import random

from console import (PAD_A, PAD_B, PAD_DOWN, PAD_LEFT, PAD_RIGHT, PAD_SELECT, PAD_START, PAD_UP,
                     PPUCTRL_NMI)

BOOT_TICKS = 60
ROUTINE_LEVEL = 5               # GAME_ROUTINE_INDEX while a level is played
LEVEL_PLAYING = 4               # LEVEL_ROUTINE_INDEX with the players in control
LIVES = 9


def title_script(two_players=True):
    """The buttons, tick by tick, from power-on to the start of a game:
    Start ends the title's scroll, Select moves to 2 PLAYERS, Start begins."""
    script = [(0, 0)] * BOOT_TICKS
    presses = [PAD_START, PAD_SELECT, PAD_START] if two_players else [PAD_START, PAD_START]
    for pad in presses:
        script += [(pad, 0)] * 3 + [(0, 0)] * 10
    return script


def moves(seed):
    """An endless run of (pad 1, pad 2), a new pair every tick: two players
    who mostly run right and shoot."""
    rng = random.Random(seed)
    while True:
        pads = []
        for _ in range(2):
            pad = PAD_RIGHT
            if rng.random() < 0.5:
                pad |= PAD_B
            if rng.random() < 0.08:
                pad |= PAD_A
            if rng.random() < 0.1:
                pad |= rng.choice((PAD_UP, PAD_DOWN))
            if rng.random() < 0.05:
                pad ^= PAD_RIGHT | PAD_LEFT
            pads.append(pad)
        yield tuple(pads)


def play(console, script, immortal=True):
    """Play a list of each tick's buttons from where the console is. It
    returns the digest of the game's memory before each tick. `immortal`
    keeps both players in lives, so that a long script is a long game."""
    labels = console.labels
    nmi_check, lives = labels["NMI_CHECK"], labels["P1_NUM_LIVES"]
    routine = labels["GAME_ROUTINE_INDEX"]
    states = []

    def on_vblank(nes):
        # An NMI that finds NMI_CHECK set is a lag frame: it reads nothing.
        # And with the NMI off there is no frame of the game at all, as
        # while the reset is under way, however many vblanks it takes.
        if not nes.ctrl & PPUCTRL_NMI or nes.ram[nmi_check] or len(states) > len(script):
            return
        if immortal and nes.ram[routine] == ROUTINE_LEVEL:
            nes.ram[lives] = nes.ram[lives + 1] = LIVES
        states.append(nes.state())
        if len(states) <= len(script):
            nes.pads = list(script[len(states) - 1])

    console.on_vblank = on_vblank
    while len(states) <= len(script):
        console.run(1)
    console.on_vblank = None
    return states[1:]


# The title's letters are ASCII by number, with its blank tile for a space
# and its full stop where @ would be; the menu draws two marks of its own.
TILES = dict((code, chr(code)) for code in list(range(0x30, 0x3A)) + list(range(0x41, 0x5B)))
TILES.update({0x00: " ", 0x40: ".", 0xFE: "-", 0xFF: ">"})


def screen_row(console, row):
    """A row of the screen as text, with ? for any other tile."""
    return "".join(TILES.get(tile, "?") for tile in console.tiles(0x2000 + 32 * row, 32))


def screen_text(console):
    return "\n".join(screen_row(console, row) for row in range(30))
