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
BOOT_TICKS = TITLE_FRAMES       # to the title, for a session to start from
LIVES = 9                       # what the tests keep both players' lives at
CHOSEN_FRAMES = 300
SELECTED_FRAMES = 200


def title_script(players=2):
    """To a level for two, or for one: on the netplay ROM with no session,
    2 TURTLES is the netplay's menu."""
    return ([(0, 0)] * TITLE_FRAMES
            + [(PAD_SELECT if players == 2 else 0, 0)] * 2 + [(0, 0)] * 5
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


def play_ticks(nes, game, digest=None):
    """Run the game a tick at a time: each tick's buttons are on the
    controllers when the game reads them (CTRL_READ_SAFE), so a lag frame
    does not move them to another tick. The digest at the start of each
    read, before it: nes.state(), or digest(nes)."""
    read = nes.labels["CTRL_READ_SAFE"]
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


# The title's letters: 0 to 9, A to Z, its full stop and a blank; and the
# line under a tile that the menu marks the letter being edited with.
TILES = {0x00: " ", 0x3F: ".", 0xF0: "-"}
TILES.update((0x01 + digit, str(digit)) for digit in range(10))
TILES.update((0x0B + letter, chr(ord("A") + letter)) for letter in range(26))

# The title's marker for the line picked: two 8x16 sprites, the second the
# first turned round, 8 pixels before the line and 4 above it.
MARK_TILE = 0x11
PPUMASK_SPRITES = 0x10


def screen_row(console, row):
    """A row of the screen as text, with ? for any other tile."""
    return "".join(TILES.get(tile, "?") for tile in console.tiles(0x2000 + 32 * row, 32))


def screen_text(console):
    return "\n".join(screen_row(console, row) for row in range(30))


def marker_row(console, column):
    """The row of the screen that the title's marker is beside, its line
    beginning at `column`; None with no marker shown."""
    if not console.mask & PPUMASK_SPRITES:
        return None
    rows = set()
    for sprite in range(64):
        y, tile, attributes, x = console.oam[4 * sprite:4 * sprite + 4]
        if y < 0xEF:
            assert tile == MARK_TILE
            assert (x, attributes & 0x40) in ((column * 8 - 24, 0), (column * 8 - 16, 0x40))
            rows.add((y + 4) // 8)
    if not rows:
        return None
    assert len(rows) == 1
    return rows.pop()
