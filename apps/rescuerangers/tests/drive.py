"""Playing the game on the simulated console: from the title to a game for
two, and moves after it.

A game is a list of the buttons held on the two controllers, a tick at a
time. `play` runs one through and keeps the digest of the game at every
frame.
"""

import random

PAD_A, PAD_B, PAD_SELECT, PAD_START = 0x80, 0x40, 0x20, 0x10
PAD_UP, PAD_DOWN, PAD_LEFT, PAD_RIGHT = 0x08, 0x04, 0x02, 0x01

# From power-on: the title is up in some 200 frames, with 1 PLAYER and
# 2 PLAYERS on line 17. Select moves the cursor to the other; Start picks,
# and the story's text comes up. Start again skips it, and the first level
# is under way some 100 frames after. In a level, Start pauses.
BOOT_FRAMES = 300
CURSOR_FRAMES = 30
STORY_FRAMES = 100
LEVEL_FRAMES = 200


def press(buttons, frames=3, rest=CURSOR_FRAMES, other=0):
    """Buttons on controller 1 for a few frames, and then none for a while."""
    return [(buttons, other)] * frames + [(0, 0)] * rest


def title_script(players=2, boot=True):
    """From power-on to the first level, for one player or two."""
    script = [(0, 0)] * BOOT_FRAMES if boot else []
    if players == 2:
        script += press(PAD_SELECT)
    script += press(PAD_START, rest=STORY_FRAMES)
    script += press(PAD_START, rest=LEVEL_FRAMES)
    return script


MOVES = (PAD_RIGHT, PAD_LEFT, PAD_RIGHT | PAD_A, PAD_LEFT | PAD_A, PAD_B, PAD_A,
         PAD_DOWN | PAD_B, PAD_RIGHT | PAD_B, PAD_UP, 0)


def moves(seed, hold=8):
    """Both players' buttons, changed every `hold` ticks, for ever."""
    rng = random.Random(seed)
    while True:
        pads = (rng.choice(MOVES), rng.choice(MOVES))
        for _ in range(hold):
            yield pads


def play(nes, game):
    """Run the game a frame at a time. The digest after each."""
    states = []
    for pads in game:
        nes.run(1, pads=pads)
        states.append(nes.state())
    return states


def play_ticks(nes, game, digest=None):
    """Run the game a tick at a time: each tick's buttons are on the
    controllers when the game reads them (CTRL_READ), so a frame that
    overran does not move them to another tick. The digest at the start of
    each read, before it: nes.state(), or digest(nes)."""
    read = nes.labels["CTRL_READ"]
    states = []
    step = nes.mpu.step

    def stepped():
        if nes.mpu.pc == read and len(states) < len(game):
            nes.pads = list(game[len(states)])
            states.append(digest(nes) if digest else nes.state())
        step()
    nes.mpu.step = stepped
    try:
        while len(states) < len(game):
            nes.run(1)
    finally:
        nes.mpu.step = step
    return states


# The game's letters: 0 to 9 from $80, A to Z from $8A; $00 and $A4 are
# blanks.
TILES = {0x00: " ", 0xA4: " "}
TILES.update((0x80 + digit, str(digit)) for digit in range(10))
TILES.update((0x8A + letter, chr(ord("A") + letter)) for letter in range(26))


def screen_row(console, row, nametable=0x2000):
    """A row of the screen as text, with ? for any other tile."""
    return "".join(TILES.get(tile, "?") for tile in console.tiles(nametable + 32 * row, 32))


def screen_text(console, nametable=0x2000):
    return "\n".join(screen_row(console, row, nametable) for row in range(30))


# The title's cursor: sprite 0, at x 40 beside 1 PLAYER and 136 beside
# 2 PLAYERS.
CURSOR_X_1P, CURSOR_X_2P = 40, 136


def cursor_players(console):
    """The title's choice the cursor is at: 1, 2, or None."""
    return {CURSOR_X_1P: 1, CURSOR_X_2P: 2}.get(console.oam[3])
