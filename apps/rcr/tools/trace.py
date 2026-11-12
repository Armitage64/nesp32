#!/usr/bin/env python3
"""Run the game on the simulated console and note where its code is.

    trace.py BASEROM ENTRIES [--seen=PATH]

Waits at the title, plays a game for one and games for two at random
(tests/drive.py) with the pause's screens opened now and then, noting the
bank and address of every instruction run. tools/convert.py follows the
code from where it begins, and places first the instructions the game
ran, which ENTRIES holds as runs of them one after another: run B:ADDR
LAST. The addresses are the game's; none of its bytes.

With --seen=PATH, also writes every instruction run there, a bank and an
address a line.
"""

import multiprocessing
import os
import random
import sys
from itertools import islice

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "tests"))

from console import Console  # noqa: E402
from convert import BANK_SIZE, BANKS, FIXED, HEADER, decode, find_code  # noqa: E402
from drive import (PAD_A, PAD_B, PAD_DOWN, PAD_SELECT, PAD_START, PAD_UP,  # noqa: E402
                   moves, press, two_players)

PLAY_FRAMES = 20000


class Traced:
    """A console that notes every instruction it runs."""

    def __init__(self, rom):
        self.nes = Console(rom)
        self.seen = set()
        nes = self.nes
        step = nes.mpu.step
        seen = self.seen

        def stepped():
            pc = nes.mpu.pc
            if pc >= 0x8000:
                seen.add((nes.bus.bank_at(pc), pc))
            step()
        nes.mpu.step = stepped

    def play(self, script):
        for pads in script:
            self.nes.run(1, pads=pads)


def title(rom):
    traced = Traced(rom)
    traced.play([(0, 0)] * 4000)
    return traced.seen


def one_player(rom):
    traced = Traced(rom)
    traced.play([(0, 0)] * 400 + press(PAD_START) + [(0, 0)] * 260 + press(PAD_START)
                + [(0, 0)] * 260 + press(PAD_START) + [(0, 0)] * 400)
    traced.play([(pads[0], 0) for pads in islice(moves(11), PLAY_FRAMES)])
    return traced.seen


def two_players_at_random(rom, seed):
    """A game for two, with the pause's screens opened now and then: Start,
    a choice at random, A, a while, B and Start back."""
    if True:
        traced = Traced(rom)
        traced.play(two_players())
        rng = random.Random(seed)
        play = moves(seed)
        while len(traced.nes.frames) < PLAY_FRAMES:
            traced.play(list(islice(play, 1200)))
            player = rng.randrange(2)
            traced.play(press(PAD_START, player, rest=60))
            for _ in range(rng.randrange(4)):
                traced.play(press(rng.choice((PAD_UP, PAD_DOWN)), player, rest=20))
            traced.play(press(PAD_A, player, rest=200))
            for buttons in (PAD_DOWN, PAD_A, PAD_UP, PAD_A, PAD_B, PAD_SELECT):
                traced.play(press(buttons, player, rest=40))
            traced.play(press(PAD_B, player, rest=60) + press(PAD_START, player, rest=60))
        return traced.seen


def run(job):
    return job[0](*job[1:])


def runs_of(prg, seen):
    """The instructions run, as runs of them one after another: (bank,
    first address, last instruction's address)."""
    runs = []
    for bank, address in sorted(seen):
        size = decode(prg, bank, address - (0xC000 if bank == FIXED else 0x8000))[2]
        if runs and runs[-1][0] == bank and runs[-1][3] == address:
            runs[-1] = (bank, runs[-1][1], address, address + size)
        else:
            runs.append((bank, address, address, address + size))
    return [run[:3] for run in runs]


def main(rom_path, entries_path, seen_path=None):
    with open(rom_path, "rb") as handle:
        rom = handle.read()
    prg = rom[HEADER:HEADER + BANKS * BANK_SIZE]
    jobs = [(title, rom_path), (one_player, rom_path)]
    jobs += [(two_players_at_random, rom_path, seed) for seed in range(1, 7)]
    seen = set()
    with multiprocessing.Pool() as pool:
        for result in pool.imap_unordered(run, jobs):
            seen |= result
    if seen_path:
        with open(seen_path, "w") as out:
            out.write("".join("%d %d\n" % key for key in sorted(seen)))
    runs = runs_of(prg, seen)
    code = find_code(prg, runs)
    # Instructions run that overlap others run (a BIT that skips the next
    # two bytes, an instruction of another path).
    inside = sorted((bank, address) for bank, address in seen
                    if (bank, address - (0xC000 if bank == FIXED else 0x8000)) not in code.code)
    with open(entries_path, "w") as out:
        out.write("# Made by tools/trace.py: the instructions the game was seen to run, as\n")
        out.write("# runs of them one after another, bank:first last.\n")
        for bank, first, last in runs:
            out.write("run %d:%04X %04X\n" % (bank, first, last))
    print("%d instructions run, in %d runs; %d inside another: %s" % (
        len(seen), len(runs), len(inside),
        " ".join("%d:%04X" % key for key in inside)))


if __name__ == "__main__":
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    seen = [arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--seen=")]
    main(*args, seen_path=seen[0] if seen else None)
