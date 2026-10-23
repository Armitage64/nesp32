#!/usr/bin/env python3
"""How long a tick of play takes in the original and the faster ROM.

    bench.py BUILD [--ticks N] [--seeds 1,2] [--stages 0,1,2,3,4] [--players 1,2]

For each stage, number of players and seed, both ROMs play the same game
from the same buttons (tests/drive.py), from the start of the stage, and
each tick of play is timed: from its NMI to the idle loop, its lag frames'
NMIs within it. Printed: the median, the tenth that are heaviest, and the
ticks that took more than a frame, and more than a frame less the netplay
exchange's 3112 cycles (Contra's).
"""

import argparse
import os
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tests"))

from console import Console  # noqa: E402
from drive import Player  # noqa: E402

FRAME = 29780
EXCHANGE = 3112


def ticks(build, name, stage, players, seed, count):
    nes = Console(os.path.join(build, name + ".nes"), os.path.join(build, name + ".dbg"))
    player = Player(nes, players == 2, seed, stage=stage)
    player.to_play()
    player.run(30)
    first = len(player.states)
    player.run(count + 1)
    costs = player.tick_cycles()[first:]
    played = player.played[first:first + len(costs)]
    return [cost for cost, play in zip(costs, played) if play]


def summary(costs):
    ranked = sorted(costs)
    return (statistics.median(ranked), ranked[int(0.9 * len(ranked))],
            100 * sum(c > FRAME for c in ranked) / len(ranked),
            100 * sum(c > FRAME - EXCHANGE for c in ranked) / len(ranked))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("build")
    parser.add_argument("--ticks", type=int, default=500)
    parser.add_argument("--seeds", default="1,2")
    parser.add_argument("--stages", default="0,1,2,3,4")
    parser.add_argument("--players", default="1,2")
    args = parser.parse_args()
    seeds = [int(s) for s in args.seeds.split(",")]
    stages = [int(s) for s in args.stages.split(",")]
    jobs = [(name, stage, players, seed)
            for players in (int(p) for p in args.players.split(","))
            for stage in stages for seed in seeds
            for name in ("contraforce", "contraforce_fast")]
    with ProcessPoolExecutor() as pool:
        results = list(pool.map(ticks, *zip(*[(args.build, n, st, p, se, args.ticks)
                                              for n, st, p, se in jobs])))
    table = {}
    for (name, stage, players, seed), costs in zip(jobs, results):
        table.setdefault((players, stage, name), []).extend(costs)
    print("ticks of play, %d a run, seeds %s" % (args.ticks, args.seeds))
    print("players stage  ROM        median   9 in 10   > frame  > frame less the exchange")
    for (players, stage, name), costs in sorted(table.items()):
        median, tenth, over, over_net = summary(costs)
        print("%7d %5d  %-9s %7.0f %9.0f %8.1f%% %8.1f%%" % (
            players, stage + 1, "original" if name == "contraforce" else "faster",
            median, tenth, over, over_net))


if __name__ == "__main__":
    main()
