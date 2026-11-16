"""Playing a Console by the game's frames rather than the picture's.

Jackal reads the controllers once for each frame of the game. A frame of
the game that overruns takes two or more of the picture's, and on which
frames that happens is a matter of cycles, so two consoles are compared
frame of the game for frame of the game: a tick. `play` holds each tick's
buttons from before the NMI that reads them, and keeps a digest of the
game's memory as each tick finds it.
"""

import random

from console import (PAD_A, PAD_B, PAD_DOWN, PAD_LEFT, PAD_RIGHT, PAD_SELECT, PAD_START, PAD_UP,
                     PPUCTRL_NMI)

BOOT_TICKS = 60
GAME_PLAYING = 5                # GameControlState while a level is played
MODE_PLAYING = 3                # GamePlayMode with the jeeps in the players' hands
# GamePlayMode with the jeeps down: the helicopter that dropped them on its
# way off (8 to 10), and then the level under way (3).
JEEPS_DOWN = (3, 8, 9, 10)
TITLE = 1                       # GameControlState at the title, waiting for a press
LIVES = 5
FRAME_LOGIC = "GameFrameLogicInProgress"


def title_script(two_players=True):
    """The buttons, tick by tick, from power-on to the start of a game:
    Select moves to 2 PLAYERS, Start begins."""
    script = [(0, 0)] * BOOT_TICKS
    presses = [PAD_SELECT, PAD_START] if two_players else [PAD_START]
    for pad in presses:
        script += [(pad, 0)] * 3 + [(0, 0)] * 10
    return script


MENU_FRAMES = 48                # from Start at 2 PLAYERS to the menu's first screen up


def local_script():
    """The same on the netplay ROM, where Start at 2 PLAYERS is its menu's:
    LOCAL GAME, the menu's third line, goes on to the game for two. Each of
    the menu's frames takes a pair of buttons too."""
    script = [(0, 0)] * BOOT_TICKS + [(PAD_SELECT, 0)] * 3 + [(0, 0)] * 10
    script += [(PAD_START, 0)] * 3 + [(0, 0)] * MENU_FRAMES
    for pad in (PAD_DOWN, PAD_DOWN, PAD_A):
        script += [(pad, 0)] * 3 + [(0, 0)] * 6
    return script


def moves(seed):
    """An endless run of (pad 1, pad 2), a new pair every tick: two players
    who mostly drive up the screen, and fire."""
    rng = random.Random(seed)
    while True:
        pads = []
        for _ in range(2):
            pad = PAD_UP
            if rng.random() < 0.5:
                pad |= PAD_B
            if rng.random() < 0.15:
                pad |= PAD_A
            if rng.random() < 0.2:
                pad |= rng.choice((PAD_LEFT, PAD_RIGHT))
            if rng.random() < 0.05:
                pad ^= PAD_UP | PAD_DOWN
            pads.append(pad)
        yield tuple(pads)


def keep_lives(console):
    """Both players in lives, so that a long script is a long game."""
    labels = console.labels
    if console.ram[labels["GameControlState"]] == GAME_PLAYING:
        for name in ("Jeep1LifeCount", "Jeep2LifeCount"):
            if console.ram[labels[name]]:
                console.ram[labels[name]] = LIVES


def play(console, script, immortal=True):
    """Play a list of each tick's buttons from where the console is. It
    returns the digest of the game's memory before each tick. `immortal`
    keeps both players in lives."""
    frame_logic = console.labels[FRAME_LOGIC]
    states = []

    def on_vblank(nes):
        # An NMI that finds the last frame's work under way is a lag frame:
        # it reads nothing. And with the NMI off there is no frame of the
        # game at all, as while the reset or a scene's load is under way,
        # however many vblanks it takes.
        if not nes.ctrl & PPUCTRL_NMI or nes.ram[frame_logic] or len(states) > len(script):
            return
        if immortal:
            keep_lives(nes)
        states.append(nes.state())
        if len(states) <= len(script):
            nes.pads = list(script[len(states) - 1])

    console.on_vblank = on_vblank
    while len(states) <= len(script):
        console.run(1)
    console.on_vblank = None
    return states[1:]


# The title's letters: its digits from $01 and its letters from $11, its
# blank tile, full stop and dash.
TILES = dict((0x01 + digit, str(digit)) for digit in range(10))
TILES.update((0x11 + letter, chr(0x41 + letter)) for letter in range(26))
TILES.update({0x00: " ", 0x0E: ".", 0x0D: "-"})


def screen_row(console, row):
    """A row of the screen as text, with ? for any other tile."""
    return "".join(TILES.get(tile, "?") for tile in console.tiles(0x2000 + 32 * row, 32))


def screen_text(console):
    return "\n".join(screen_row(console, row) for row in range(30))


MARKER_TILE = 0x11              # the little jeep's first sprite, beside the line chosen
HIDDEN = 0xEF


def marker_row(console):
    """The row of text the title's or the menu's little jeep is beside, or
    None with none shown."""
    for sprite in range(64):
        y, tile = console.oam[4 * sprite], console.oam[4 * sprite + 1]
        if tile == MARKER_TILE and y < HIDDEN:
            return (y + 6) // 8
    return None
