#!/usr/bin/env python3
"""Run the game on the simulated console and note where its code is.

    trace.py BASEROM ENTRIES

Plays the title and its demo, the password screen, a game for one that a
second player joins, every round from 1 to 100 for two, and a game for two
to its end and a continue (tests/drive.py), noting the bank and address of
every instruction run. tools/convert.py follows the code from where it
begins, and places first the instructions the game ran, which ENTRIES
holds as runs of them one after another: run B:ADDR LAST.
The addresses are the game's; none of its bytes.

With --measure, also prints the NMI's length in each round; with
--seen=PATH, writes every instruction run there, a bank and an address a
line.
"""

import multiprocessing
import os
import sys
from itertools import islice

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "tests"))

from console import Console  # noqa: E402
from convert import BANK_SIZE, FIXED, HEADER, decode, find_code  # noqa: E402
from drive import (PAD_A, PAD_B, PAD_DOWN, PAD_LEFT, PAD_RIGHT, PAD_SELECT,  # noqa: E402
                   PAD_START, PAD_UP, TITLE_1P_START, TITLE_2P_CONTINUE, TITLE_2P_START,
                   TITLE_PASSWORD, BOOT_FRAMES, moves, press, screen_text, title_script)

ROUND = 0x0401          # the round, which a continue starts at
ROUNDS = 100
ROUND_TICKS = 900


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
            if pc >= 0xC000:
                seen.add((FIXED, pc))
            elif pc >= 0x8000:
                seen.add((nes.bus.bank_at(pc), pc))
            step()
        nes.mpu.step = stepped

    def play(self, script):
        for pads in script:
            self.nes.run(1, pads=pads)


def title_demo(rom):
    traced = Traced(rom)
    traced.play([(0, 0)] * 4000)
    return traced.seen, None


def password(rom):
    traced = Traced(rom)
    traced.play(title_script(TITLE_PASSWORD))
    for buttons in (PAD_UP, PAD_RIGHT, PAD_DOWN, PAD_A, PAD_LEFT, PAD_B, PAD_A, PAD_RIGHT,
                    PAD_UP, PAD_A, PAD_A, PAD_A, PAD_START):
        traced.play(press(buttons))
    traced.play([(0, 0)] * 600)
    return traced.seen, None


def joined(rom):
    traced = Traced(rom)
    traced.play(title_script(TITLE_1P_START))
    traced.play([(pads[0], 0) for pads in islice(moves(5), 1500)])
    traced.play([(0, PAD_START)] * 4)
    traced.play(list(islice(moves(6), 2000)))
    # A pause, and on.
    traced.play(press(PAD_START, rest=120) + press(PAD_START, rest=60))
    return traced.seen, None


def to_the_end(rom):
    """Two players to a game over, its screens, and a continue."""
    traced = Traced(rom)
    traced.play(title_script(TITLE_2P_START))
    play = moves(7)
    for _ in range(40000):
        traced.nes.run(1, pads=next(play))
        if len(traced.nes.frames) % 64 == 0 and "GAME OVER" in screen_text(traced.nes):
            break
    # The game over's screen, then Start for the title's choices.
    traced.play([(0, 0)] * 120 + press(PAD_START, rest=200))
    for _ in range(TITLE_2P_CONTINUE):
        traced.play(press(PAD_SELECT))
    traced.play(press(PAD_START) + press(PAD_START, rest=300))
    traced.play(list(islice(moves(8), 2000)))
    return traced.seen, None


def one_round(args):
    rom, number = args
    traced = Traced(rom)
    nes = traced.nes
    traced.play([(0, 0)] * BOOT_FRAMES)
    nes.ram[ROUND] = number
    traced.play(title_script(TITLE_2P_CONTINUE, boot=False))
    start = len(nes.frames)
    traced.play(list(islice(moves(100 + number), ROUND_TICKS)))
    frames = nes.frames[start:]
    cycles = sorted(frame.nmi_cycles for frame in frames if frame.nmi_cycles)
    return traced.seen, (number, cycles, sum(frame.lag for frame in frames))


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


def main(rom_path, entries_path, measure=False, seen_path=None):
    with open(rom_path, "rb") as handle:
        rom = handle.read()
    prg = rom[HEADER:HEADER + 8 * BANK_SIZE]
    jobs = [(title_demo, rom_path), (password, rom_path), (joined, rom_path),
            (to_the_end, rom_path)]
    rounds = [(rom_path, number) for number in range(1, ROUNDS + 1)]
    seen = set()
    rows = []
    with multiprocessing.Pool() as pool:
        singles = [pool.apply_async(job, (arg,)) for job, arg in jobs]
        for result, row in pool.imap(one_round, rounds):
            seen |= result
            rows.append(row)
        for single in singles:
            seen |= single.get()[0]
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
    if measure:
        for number, cycles, lags in rows:
            if not cycles:
                continue
            print("round %3d  NMI median %5d  p90 %5d  p99 %5d  max %6d  frames with no NMI %d" % (
                number, cycles[len(cycles) // 2], cycles[int(len(cycles) * 0.9)],
                cycles[int(len(cycles) * 0.99)], cycles[-1], lags))


if __name__ == "__main__":
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    seen = [arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--seen=")]
    main(*args, measure="--measure" in sys.argv, seen_path=seen[0] if seen else None)
