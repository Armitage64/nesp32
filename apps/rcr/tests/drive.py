"""Playing River City Ransom on the simulated console: the buttons for the
title's choices, and play at random.

The title's first screen chooses 1P PLAY or 2P PLAY (Down, then Start);
the next its message speed and skill level (Start takes NORMAL and
NOVICE); then Slick's letter, which Start passes over, and the game's
title, which goes on by itself into Cross Town High.
"""

import random

PAD_A, PAD_B, PAD_SELECT, PAD_START = 0x80, 0x40, 0x20, 0x10
PAD_UP, PAD_DOWN, PAD_LEFT, PAD_RIGHT = 0x08, 0x04, 0x02, 0x01

# The frames of the script for a game for two, from the power on: Down at
# the first screen, Start, Start at the second, Start at the letter, and
# the title's time.
TWO_PLAYER_SCRIPT = ((250, 255, PAD_DOWN), (400, 405, PAD_START), (700, 705, PAD_START),
                     (1000, 1005, PAD_START))
TWO_PLAYER_FRAMES = 1450


def two_players():
    """Player 1's buttons for each frame from the power on to a game for
    two in Cross Town High."""
    script = []
    for frame in range(TWO_PLAYER_FRAMES):
        buttons = 0
        for first, last, pressed in TWO_PLAYER_SCRIPT:
            if first <= frame <= last:
                buttons = pressed
        script.append((buttons, 0))
    return script


def press(buttons, player=0, hold=4, rest=30):
    """A press of a button by one player, and a rest after it."""
    pads = [0, 0]
    pads[player] = buttons
    return [tuple(pads)] * hold + [(0, 0)] * rest


def play_buttons(rng):
    """One player's buttons for a while: walking (mostly right), up and
    down the street, punching, kicking and jumping."""
    buttons = 0
    roll = rng.random()
    if roll < 0.55:
        buttons |= PAD_RIGHT
    elif roll < 0.70:
        buttons |= PAD_LEFT
    roll = rng.random()
    if roll < 0.2:
        buttons |= PAD_UP
    elif roll < 0.4:
        buttons |= PAD_DOWN
    roll = rng.random()
    if roll < 0.3:
        buttons |= PAD_B
    elif roll < 0.55:
        buttons |= PAD_A
    return buttons


def moves(seed, hold=8):
    """Both players' buttons, a frame at a time, forever: each player's
    held for `hold` frames, then others."""
    rng = random.Random(seed)
    while True:
        pads = (play_buttons(rng), play_buttons(rng))
        for _ in range(hold):
            yield pads


# --- reading the screen -------------------------------------------------------------

# The first screen's font (its CHR bank 126): capitals, small letters,
# digits and a few signs. The menu draws with it too, and the mark under the
# letter it edits is the font's line at the top of a tile ($AC), read here
# as a dash.
TILES = {0x00: " ", 0xB4: "-", 0xB6: ".", 0xAC: "-"}
TILES.update((0xC0 + n, chr(ord("A") + n)) for n in range(26))
TILES.update((0xDA + n, chr(ord("a") + n)) for n in range(26))
TILES.update((0xF4 + n, chr(ord("0") + n)) for n in range(10))


def screen_row(console, row):
    """A row of the first nametable as text, with ? for any other tile."""
    return "".join(TILES.get(tile, "?") for tile in console.tiles(0x2000 + 32 * row, 32))


def screen_text(console):
    return "\n".join(screen_row(console, row) for row in range(30))


MARKER_TILE = 0xBB - 0x80       # the menu's arrow, from its CHR bank at $1000
HIDDEN = 0xEF


def marker_row(console):
    """The row of text the menu's arrow is beside, or None with none shown."""
    for sprite in range(64):
        y, tile = console.oam[4 * sprite], console.oam[4 * sprite + 1]
        if tile == MARKER_TILE and y < HIDDEN:
            return (y + 1) // 8
    return None


def moves_with_pauses(seed, every=600):
    """moves, and now and then one player's Start: the pause's screens, a
    choice there at random, A, B back and Start again."""
    rng = random.Random(seed)
    play = moves(seed)
    while True:
        for _ in range(every):
            yield next(play)
        player = rng.randrange(2)
        script = press(PAD_START, player, rest=60)
        for _ in range(rng.randrange(4)):
            script += press(rng.choice((PAD_UP, PAD_DOWN)), player, rest=20)
        script += press(PAD_A, player, rest=120) + press(PAD_B, player, rest=40)
        script += press(PAD_B, player, rest=40) + press(PAD_START, player, rest=60)
        for pads in script:
            yield pads
