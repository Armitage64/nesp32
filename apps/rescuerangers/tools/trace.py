#!/usr/bin/env python3
"""Run the game on the simulated console and note where its code is.

    trace.py BASEROM ENTRIES [--seen=PATH]

Waits at the title, and plays games for one and for two at random
(tests/drive.py), with the pause now and then, noting the bank and
address of every instruction run. tools/convert.py follows the code from
where it begins, and places first the instructions the game ran, which
ENTRIES holds as runs of them one after another: run B:ADDR LAST. The
addresses are the game's; none of its bytes.

With --seen=PATH, also writes every instruction run there, a bank and an
address a line.

Only the first level is reached so far: the levels after it, the zone
map and the end are to be added, as Bubble Bobble's trace pokes in a
round.
"""

import multiprocessing
import os
import sys
from itertools import islice

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "tests"))

from console import Console  # noqa: E402
from convert import BANK_SIZE, BANKS, FIXED, HEADER, decode, find_code  # noqa: E402
from drive import PAD_START, moves, press, title_script  # noqa: E402

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


def game(args):
    """A game for one or two, played at random, with the pause."""
    rom, players, seed = args
    traced = Traced(rom)
    traced.play(title_script(players))
    play = moves(seed)
    for chunk in range(PLAY_FRAMES // 1000):
        traced.play(list(islice(play, 1000)))
        if chunk % 5 == 2:
            traced.play(press(PAD_START, rest=60) + press(PAD_START, rest=10))
    return traced.seen


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
    games = [(rom_path, players, seed) for players in (1, 2) for seed in range(1, 5)]
    seen = set()
    with multiprocessing.Pool() as pool:
        single = pool.apply_async(title, (rom_path,))
        for result in pool.imap_unordered(game, games):
            seen |= result
        seen |= single.get()
    if seen_path:
        with open(seen_path, "w") as out:
            out.write("".join("%d %d\n" % key for key in sorted(seen)))
    runs = runs_of(prg, seen)
    code = find_code(prg, runs)
    # Instructions run that overlap others run: the BIT that skips the next
    # two bytes, which are an instruction to another path. The converter
    # writes the first of each as it is, and the bytes inside it as its.
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
