#!/usr/bin/env python3
"""How long Jackal's frames of the game take, on the simulated console.

    bench.py ROM DBG [--levels 1,2,4] [--seeds 3] [--ticks 1500] [--jobs 8]

A game for two (by the title's 2 PLAYERS, or on the netplay ROM by its
menu's LOCAL GAME), both players kept in lives, from the start of a level:
the level is written where the game keeps it before the level loads. What
is timed is each tick of play: from the NMI that begins it to the game's
return to its idle loop, with the jeeps down and the picture on. A tick
longer than a frame has no NMI of its own at the next vblank, and the game
stands still a frame (a lag frame). In a session each tick also has the
exchange with the nesp32, which is not made here: a tick longer than a
frame less the exchange is one a session lags on.

The same seeds on any ROM are the same buttons, and the original and the
netplay ROM with no session are the same game (tests/test_console.py), so
two ROMs are compared tick for tick.
"""

import argparse
import os
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from itertools import islice

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tests"))

from console import Console, FRAME_CYCLES  # noqa: E402
from drive import (GAME_PLAYING, MODE_PLAYING, keep_lives, local_script, moves,  # noqa: E402
                   title_script)

FRAME = 29780
# A session's exchange: the TICKS request and its reply, with the reads of
# the controller (nesp32's docs/PROTOCOL.md), less the game's own double
# read of both controllers that it replaces. At the session's own rate of
# 14 cycles a bit (PEER's RATE) it is some 2500 cycles; at the link's 21,
# some 3150.
EXCHANGE = 2500 - 700
MASK_SHOWN = 0x18


class Bench(Console):
    """A console that times each tick of the game."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tick_start = None
        self.ticks = []
        self.frame_logic = self.labels["GameFrameLogicInProgress"]

    def _vblank(self):
        if self.ctrl & 0x80 and not self.ram[self.frame_logic] and self.tick_start is None:
            self.tick_start = self.mpu.processorCycles
        super()._vblank()

    def _wait(self, limit):
        if self.mpu.pc == self.idle and self.tick_start is not None:
            playing = (self.byte("GameControlState") == GAME_PLAYING
                       and self.byte("GamePlayMode") == MODE_PLAYING
                       and self.mask & MASK_SHOWN)
            if playing:
                self.ticks.append(self.mpu.processorCycles - self.tick_start)
            self.tick_start = None
        super()._wait(limit)


def run(rom, dbg, level, seed, ticks):
    nes = Bench(rom, dbg)
    netplay = "net_mode" in nes.labels
    script = (local_script() if netplay else title_script()) + list(islice(moves(seed), ticks))
    level_at = nes.labels["CurrentLevel"]
    poked = False
    played = 0

    def on_vblank(console):
        nonlocal poked, played
        if not console.ctrl & 0x80 or console.ram[console.frame_logic]:
            return
        if (not poked and console.byte("GameControlState") == GAME_PLAYING
                and console.byte("GamePlayMode") <= 1):
            console.ram[level_at] = level - 1
            poked = True
        keep_lives(console)
        if played < len(script):
            console.pads = list(script[played])
        played += 1

    nes.on_vblank = on_vblank
    while played < len(script):
        nes.run(1)
    return nes.ticks


def summary(ticks):
    ticks = sorted(ticks)
    over = sum(1 for tick in ticks if tick > FRAME)
    over_net = sum(1 for tick in ticks if tick > FRAME - EXCHANGE)
    return (len(ticks), int(statistics.median(ticks)), ticks[int(0.9 * (len(ticks) - 1))],
            100.0 * over / len(ticks), 100.0 * over_net / len(ticks))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("rom")
    parser.add_argument("dbg")
    parser.add_argument("--levels", default="1,2,3,4,5,6")
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--ticks", type=int, default=1500)
    parser.add_argument("--jobs", type=int, default=os.cpu_count())
    args = parser.parse_args()
    levels = [int(level) for level in args.levels.split(",")]
    jobs = [(level, seed) for level in levels for seed in range(1, args.seeds + 1)]
    with ProcessPoolExecutor(args.jobs) as pool:
        results = list(pool.map(run, *zip(*[(args.rom, args.dbg, level, seed, args.ticks)
                                             for level, seed in jobs])))
    print("%s: ticks of play, two players, %d seeds" % (os.path.basename(args.rom), args.seeds))
    print("level  ticks  median    90%%  over a frame  over a session's (-%d)" % EXCHANGE)
    for level in levels:
        ticks = [tick for (lv, _), result in zip(jobs, results) if lv == level for tick in result]
        if not ticks:
            print("%5d  none" % level)
            continue
        count, median, p90, over, over_net = summary(ticks)
        print("%5d  %5d  %6d  %5d  %11.1f%%  %21.1f%%" % (level, count, median, p90, over, over_net))


if __name__ == "__main__":
    main()
