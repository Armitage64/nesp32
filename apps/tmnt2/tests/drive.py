"""Playing the game on the simulated console: from the title to a game for
two, and moves after it.

A game is a list of the buttons held on the two controllers, a tick at a
time. `play` runs one through and keeps the digest of the game at every
frame.
"""

import random

PAD_A, PAD_B, PAD_SELECT, PAD_START = 0x80, 0x40, 0x20, 0x10
PAD_UP, PAD_DOWN, PAD_LEFT, PAD_RIGHT = 0x08, 0x04, 0x02, 0x01

# STATE_SWITCH_INITIAL_MENUS, the game's own state before its levels.
STATE_TITLE = 1
STATE_TURTLE_SELECT = 4
STATE_LEVELS = 5

# From power-on: the Konami logo and the story run to the title in about
# 260 frames. Select moves the title's cursor to 2 PLAYERS, Start picks it,
# and the turtle select comes some 130 frames later. A on each controller
# picks a turtle, and the level starts when the select's timer runs out.
TITLE_FRAMES = 280
CHOSEN_FRAMES = 300
SELECTED_FRAMES = 200


def title_script():
    return ([(0, 0)] * TITLE_FRAMES
            + [(PAD_SELECT, 0)] * 2 + [(0, 0)] * 5
            + [(PAD_START, 0)] * 2 + [(0, 0)] * CHOSEN_FRAMES
            + [(PAD_A, PAD_A)] * 2 + [(0, 0)] * SELECTED_FRAMES)


MOVES = (PAD_RIGHT, PAD_LEFT, PAD_RIGHT | PAD_B, PAD_LEFT | PAD_B, PAD_B, PAD_A,
         PAD_UP | PAD_RIGHT, PAD_DOWN | PAD_RIGHT, PAD_A | PAD_B)


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
