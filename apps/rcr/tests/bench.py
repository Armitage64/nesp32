"""The netplay ROM's speed, for comparing builds: a session of two simulated
consoles whose buttons follow each console's own tick from the session's
start, so that two builds play the same game tick for tick and only their
speed differs. Buttons held by the frame, as the tests' are, make a quicker
build play another game, which is as likely to be busier.

Player 1's Start now and then until the game for two begins, then
drive.moves(seed), three ticks a pair of buttons, from 30 ticks later.
Prints the ticks a second over that play, and the digest of the game
(console.py's state) at its last tick, which two builds have to share for
their speeds to be compared.

    python3 tests/bench.py SEED TICKS [BUILD_DIR]
"""

import itertools
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
CALLED_FROM = pathlib.Path.cwd()
sys.path.insert(0, str(HERE))
os.chdir(HERE)

import conftest  # noqa: F401  (nesp32's host side, built for the tests)
from console import FRAME_CYCLES, PAD_START, Console
from drive import moves
from netplay import Table
from wire import SLICE, ms

PLAY_AFTER = 30         # ticks from the game's first pass to the play's buttons


def bench(build, seed, ticks):
    def make(**options):
        return Console(str(build / "rcr_net.nes"), str(build / "rcr_net.dbg"), **options)
    table = Table(make, delay=ms(5))
    table.start()
    script = list(itertools.islice(moves(seed, hold=3), ticks + 50))
    first = table.consoles[0]
    play_at = began = None

    def pads(side, tick):
        if play_at is None:
            return PAD_START if side == 0 and tick % 40 < 3 else 0
        return script[tick - play_at][side] if tick >= play_at else 0

    while began is None or table.ticks(0) < play_at + ticks:
        table.now += SLICE
        for side, console in enumerate(table.consoles):
            console.run_until(table.now + table.offsets[side],
                              pads=(pads(side, table.ticks(side)), 0))
            table.ticks(side)
            table.sticks[side].poll()
        table.lan.poll()
        if play_at is None and first.calls_of("MAIN_LOOP"):
            play_at = table.ticks(0) + PLAY_AFTER
        if began is None and play_at is not None and table.ticks(0) >= play_at:
            began = table.now
    frames = (table.now - began) / FRAME_CYCLES
    table.same_game()
    last = max(set(table.traces[0]) & set(table.traces[1]))
    return ticks / frames * 60, table.delays(), last, table.traces[0][last][:8]


if __name__ == "__main__":
    seed, ticks = int(sys.argv[1]), int(sys.argv[2])
    build = (CALLED_FROM / sys.argv[3]).resolve() if len(sys.argv) > 3 else HERE.parent / "build"
    rate, delays, last, digest = bench(build, seed, ticks)
    print("seed %d: %.2f ticks a second over %d ticks of play; delays %s; the game at tick %d: %s"
          % (seed, rate, ticks, delays, last, digest))
