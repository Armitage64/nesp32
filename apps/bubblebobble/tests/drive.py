"""Playing the game on the simulated console: from the title to a game for
two, and moves after it.

A game is a list of the buttons held on the two controllers, a tick at a
time. `play` runs one through and keeps the digest of the game at every
frame.
"""

import random

PAD_A, PAD_B, PAD_SELECT, PAD_START = 0x80, 0x40, 0x20, 0x10
PAD_UP, PAD_DOWN, PAD_LEFT, PAD_RIGHT = 0x08, 0x04, 0x02, 0x01

# The title's choices, in the order Select goes through them.
TITLE_1P_START, TITLE_2P_START, TITLE_1P_CONTINUE, TITLE_2P_CONTINUE, TITLE_PASSWORD = range(5)

# From power-on: the copyright and the logo are up in some 200 frames, and
# Start shows the title's choices. Select moves the cursor down one, Start
# picks; a continue's Start shows its round, and a second Start plays it.
# The round is under way some 420 frames after.
BOOT_FRAMES = 300
LIVES = 5                       # what the tests keep both players' lives at
CHOICES_FRAMES = 60
CURSOR_FRAMES = 15
ROUND_FRAMES = 450


def press(buttons, frames=2, rest=CURSOR_FRAMES, other=0):
    """Buttons on controller 1 for a few frames, and then none for a while."""
    return [(buttons, other)] * frames + [(0, 0)] * rest


def title_script(choice=TITLE_2P_START, boot=True):
    """From power-on, or from the title as a game over leaves it, to a
    round: Start for the choices, Select down to `choice`, and Start."""
    script = [(0, 0)] * BOOT_FRAMES if boot else []
    script += press(PAD_START, rest=CHOICES_FRAMES)
    for _ in range(choice):
        script += press(PAD_SELECT)
    if choice in (TITLE_1P_CONTINUE, TITLE_2P_CONTINUE):
        script += press(PAD_START)
    script += press(PAD_START, rest=ROUND_FRAMES)
    return script


MOVES = (PAD_RIGHT, PAD_LEFT, PAD_RIGHT | PAD_B, PAD_LEFT | PAD_B, PAD_B, PAD_A,
         PAD_A | PAD_RIGHT, PAD_A | PAD_LEFT, PAD_UP, 0)


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


# The game's letters: 0 to 9, A to Z, its full stop and a blank; and the
# line from the logo's tiles that the menu marks the letter being edited
# with, in the row below it.
TILES = {0x26: " ", 0x2A: ".", 0xE8: "-"}
TILES.update((digit, str(digit)) for digit in range(10))
TILES.update((0x0A + letter, chr(ord("A") + letter)) for letter in range(26))


def screen_row(console, row, nametable=0x2000):
    """A row of the screen as text, with ? for any other tile."""
    return "".join(TILES.get(tile, "?") for tile in console.tiles(nametable + 32 * row, 32))


def screen_text(console, nametable=0x2000):
    return "\n".join(screen_row(console, row, nametable) for row in range(30))


# The title's marker for the line picked: two 8x16 sprites side by side,
# the first two, 7 pixels above the line. (The game's NMI turns the picture
# off for its first writes, so what PPUMASK has at a moment says little.)
MARK_TILES = (0x26, 0x28)


def marker_row(console):
    """The row of the screen that the title's marker is beside; None with
    no marker shown."""
    y, tile = console.oam[0], console.oam[1]
    if y >= 0xEF or tile not in MARK_TILES:
        return None
    assert console.oam[4] == y and console.oam[5] in MARK_TILES
    return (y + 7) // 8
