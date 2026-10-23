"""Playing a Console by the game's frames rather than the picture's.

Contra Force reads the controllers once for each frame of the game, in an
NMI that finds the last one's work done. A frame of the game that overruns
takes two of the picture's, and on which frames that happens is a matter
of cycles, so two ROMs are compared frame of the game for frame of the
game: a tick. `play` holds each tick's buttons from before the NMI that
reads them, and keeps a digest of the game's memory as each tick finds it.
"""

import random

from console import PAD_A, PAD_B, PAD_DOWN, PAD_LEFT, PAD_RIGHT, PAD_START, PAD_UP, PPUCTRL_NMI

SCRIPT_HI, SCRIPT_LO = 0x20, 0x44   # ram_script_hi, ram_script_lo
GAMEPLAY = 3                        # con_0020_gameplay
SELECT, PLAYING = 1, 4              # script_lo: the players' choice, and play
CHOICES = 0x21                      # each player's character, 0 none
STAGE = 0x75                        # ram_stage
LIVES = 0xB3                        # ram_lives, one for each character
CHARACTERS = 4


def playing(nes):
    return nes.ram[SCRIPT_HI] == GAMEPLAY and nes.ram[SCRIPT_LO] == PLAYING


def menu_pads(nes, tick, two_players):
    """The buttons that take the title and the players' choice to a game:
    Start on the title, player 1 Right (and player 2 Left) to a character,
    then Start. They answer what the screen shows, so any ROM that is the
    same game gets the same."""
    on = tick % 8 < 2
    if nes.ram[SCRIPT_HI] == GAMEPLAY and nes.ram[SCRIPT_LO] == SELECT:
        if nes.ram[CHOICES] == 0:
            return (PAD_RIGHT if on else 0, 0)
        if two_players and nes.ram[CHOICES + 1] == 0:
            return (0, PAD_LEFT if on else 0)
        return (PAD_START if on else 0, 0)
    return (PAD_START if tick % 80 < 2 else 0, 0)


def moves(seed, two_players=True):
    """An endless run of (pad 1, pad 2), a new pair every tick: players who
    mostly run right and shoot."""
    rng = random.Random(seed)
    while True:
        pads = []
        for _ in range(2 if two_players else 1):
            pad = PAD_RIGHT
            if rng.random() < 0.6:
                pad |= PAD_B
            if rng.random() < 0.06:
                pad |= PAD_A
            if rng.random() < 0.1:
                pad |= rng.choice((PAD_UP, PAD_DOWN))
            if rng.random() < 0.05:
                pad ^= PAD_RIGHT | PAD_LEFT
            pads.append(pad)
        yield tuple(pads) if two_players else (pads[0], 0)


class Player:
    """Plays a console tick by tick: to a game through the menu, at a stage
    written while the players choose, and then from `moves`. Each tick's digest of the game's memory is kept in
    `states`, and how many cycles it took in `ticks` (from its NMI to the
    idle loop, the lag frames' NMIs within it included)."""

    def __init__(self, nes, two_players=True, seed=1, immortal=True, stage=0):
        self.nes = nes
        self.stage = stage          # 0-4: stage 1 to stage 5
        self.two_players = two_players
        self.moves = moves(seed, two_players)
        self.immortal = immortal
        self.states = []
        self.tick_frames = []       # for each tick, the frames it began
        self.played = []            # for each tick, whether it was of play
        nes.on_vblank = self._on_vblank

    def _on_vblank(self, nes):
        # An NMI that finds ram_nmi_flag_3 set is a lag frame: it reads
        # nothing. With the NMI off there is no frame of the game at all.
        if not nes.ctrl & PPUCTRL_NMI or nes.ram[nes.labels["ram_nmi_flag_3"]]:
            return
        tick = len(self.states)
        if nes.ram[SCRIPT_HI] == GAMEPLAY and nes.ram[SCRIPT_LO] in (SELECT, SELECT + 1, SELECT + 2):
            nes.ram[STAGE] = self.stage     # the stage that the choice leads to
        if playing(nes):
            if self.immortal:
                for character in range(CHARACTERS):
                    nes.ram[LIVES + character] = 5
            nes.pads = list(next(self.moves))
        else:
            nes.pads = list(menu_pads(nes, tick, self.two_players))
        self.states.append(nes.state())
        self.played.append(playing(nes))
        # The frame this NMI begins is the one after the frame it ends.
        self.tick_frames.append(len(nes.frames) + 1)

    def run(self, ticks):
        """Run until this many more ticks have begun."""
        target = len(self.states) + ticks
        while len(self.states) < target:
            self.nes.run(1)

    def to_play(self, limit=3000):
        """Run until the players are in control of a game."""
        while not playing(self.nes):
            if len(self.states) > limit:
                raise AssertionError("no game after %d ticks" % limit)
            self.nes.run(1)

    def tick_cycles(self):
        """The cycles of each finished tick: the busy cycles of the frame it
        began in and of the lag frames after it."""
        frames = self.nes.frames
        starts = self.tick_frames
        costs = []
        for first, after in zip(starts, starts[1:]):
            costs.append(sum(frame.busy for frame in frames[first:after]))
        return costs
