#!/usr/bin/env python3
"""What each of the faster ROM's passes saves, by taking it out.

    ablate.py BUILD [--ticks N]

For each pass, a faster ROM is built in BUILD/ablate/<pass> with that one
pass's call to it put back as the game's (its .ifdef FAST made another
name's), or, for the probe's helpers, with tools/probe.py leaving the
calls. Each ROM, the full faster ROM and the original then play the same
game from the same buttons, and what is counted is a tick's own work: the
cycles in its NMI, less the lag frames' NMIs and the IRQs that break into
it, which run to the picture's clock. A pass saves what the ROM without it
takes more than the full one, with the others in.

In the stages that scroll up the game reads the PPU's second buffer,
which the IRQ sends once a frame (tests/test_fast.py), so each ROM is
given the full ROM's buffer where one has sent it and the other not, and
plays the same game.
"""

import argparse
import os
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "tests"))

# Each pass: the source and the line after its .ifdef FAST, a description,
# and whether it is the probe's helpers (tools/probe.py --no-inline).
PASSES = [
    ("bankswitch", [("bank_FF.asm", "; The switch from the PRG RAM (fast/bankswitch.inc)."),
                    ("bank_FF.asm", "    JMP fast_switch_pair")]),
    ("probe", [("bank_04.asm", "; The background's test from the PRG RAM, with no switch")]),
    ("probe_inline", None),
    ("sprites", [("bank_FF.asm", "; The sprite pass from the PRG RAM (fast/sprites.inc).")]),
    ("pads", [("bank_FF.asm", "; The controllers read from the PRG RAM (fast/pads.inc).")]),
    ("boxes", [("bank_FF.asm", "; The clearing in line, from the PRG RAM (fast/loops.inc).")]),
    ("zeros", [("bank_FF.asm", "; From the PRG RAM, in line (fast/loops.inc).")]),
    ("columns", [("bank_FF.asm", "; The tiles written from the PRG RAM (fast/columns.inc).")]),
]
RUNS = [(False, 1, 0), (False, 3, 2), (True, 2, 0)]     # (two players, seed, stage)
BUFFER_INDEX = 0x39
BUFFER = [BUFFER_INDEX, 0x56] + list(range(0x160, 0x1C0))


def build(build_dir, name, sites):
    out = os.path.join(build_dir, "ablate", name)
    if os.path.isdir(out):
        shutil.rmtree(out)
    make = ["make", "-s", "BUILD=%s" % out]
    subprocess.run(make + ["all"], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    if sites is None:
        subprocess.run([sys.executable, os.path.join(HERE, "probe.py"), _pristine(),
                        os.path.join(out, "probe_game.inc"), "--no-inline"], check=True)
        os.utime(os.path.join(out, "probe_game.inc"))
    else:
        for source, marker in sites:
            path = os.path.join(out, "upstream", source)
            with open(path, encoding="latin-1") as handle:
                text = handle.read()
            block = ".ifdef FAST\n" + marker
            assert text.count(block) == 1, (name, marker)
            text = text.replace(block, ".ifdef FAST_TAKEN_OUT\n" + marker)
            with open(path, "w", encoding="latin-1") as handle:
                handle.write(text)
    # make takes file times to the second, so what was just edited may look
    # no newer than what was built from it: the faster ROM is made again.
    for stale in ["prepare.stamp", "contraforce_fast.nes"]:
        os.remove(os.path.join(out, stale))
    shutil.rmtree(os.path.join(out, "fast"))
    subprocess.run(make + ["all"], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    return out


def _pristine():
    nesp32 = os.path.abspath(os.path.join(ROOT, "..", ".."))
    return os.path.join(nesp32, "third_party", "NES-Games-Disassembly", "Contra Force",
                        "bank_FF.asm")


def play(rom_dir, rom, run, ticks, reference=None):
    """Each tick of play's own work, and the RAM before each tick."""
    from console import Console
    from drive import Player
    two_players, seed, stage = run
    nes = Console(os.path.join(rom_dir, rom + ".nes"), os.path.join(rom_dir, rom + ".dbg"))
    player = Player(nes, two_players, seed, stage=stage)
    rams = []
    hook = nes.on_vblank
    flag = nes.labels["ram_nmi_flag_3"]

    def vblank(console):
        tick = len(player.states)
        if reference is not None and console.ctrl & 0x80 and not console.ram[flag] \
                and tick < len(reference):
            theirs = reference[tick]
            if (theirs[BUFFER_INDEX] == 0) != (console.ram[BUFFER_INDEX] == 0):
                for address in BUFFER:
                    console.ram[address] = theirs[address]
        before = len(player.states)
        hook(console)
        if len(player.states) > before:
            rams.append(bytes(console.ram))
    nes.on_vblank = vblank
    work = {}
    mpu = nes.mpu
    step = mpu.step

    def counted():
        if nes.interrupts == ["nmi"]:
            before = mpu.processorCycles
            step()
            tick = len(player.states)
            work[tick] = work.get(tick, 0) + mpu.processorCycles - before
        else:
            step()
    mpu.step = counted
    player.to_play()
    player.run(30)
    first = len(player.states)
    player.run(ticks)
    played = [t for t in range(first, len(player.states) - 1) if player.played[t]]
    return [work.get(t + 1, 0) for t in played], rams


def measure(job):
    rom_dir, rom, run, ticks, reference = job
    costs, _ = play(rom_dir, rom, run, ticks, reference)
    return sum(costs) / len(costs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("build")
    parser.add_argument("--ticks", type=int, default=400)
    args = parser.parse_args()
    build_dir = os.path.abspath(args.build)
    subprocess.run(["make", "-s", "BUILD=%s" % build_dir, "all"], cwd=ROOT, check=True,
                   stdout=subprocess.DEVNULL)
    dirs = {"full": build_dir}
    for name, sites in PASSES:
        dirs[name] = build(build_dir, name, sites)
    references = {}
    with ProcessPoolExecutor() as pool:
        refs = list(pool.map(play, [build_dir] * len(RUNS), ["contraforce_fast"] * len(RUNS),
                             RUNS, [args.ticks] * len(RUNS)))
    for run, (_, rams) in zip(RUNS, refs):
        references[run] = rams
    jobs = []
    for run in RUNS:
        jobs.append((build_dir, "contraforce", run, args.ticks, references[run]))
        for name in ["full"] + [n for n, _ in PASSES]:
            jobs.append((dirs[name], "contraforce_fast", run, args.ticks, references[run]))
    with ProcessPoolExecutor() as pool:
        means = list(pool.map(measure, jobs))
    table = {}
    for (rom_dir, rom, run, _, _), mean in zip(jobs, means):
        name = "original" if rom == "contraforce" else next(
            n for n, d in dirs.items() if d == rom_dir)
        table[(name, run)] = mean
    heads = ["1P stage %d" % (s + 1) if not two else "2P stage %d" % (s + 1)
             for two, _, s in RUNS]
    print("a tick's own work, cycles (mean of %d ticks of play)" % args.ticks)
    print("%-14s" % "" + "".join("%14s" % h for h in heads))
    for name in ["original", "full"]:
        print("%-14s" % name + "".join("%14.0f" % table[(name, run)] for run in RUNS))
    print("saved by each, with the others in:")
    for name, _ in PASSES:
        print("%-14s" % name + "".join("%14.0f" % (table[(name, run)] - table[("full", run)])
                                       for run in RUNS))


if __name__ == "__main__":
    main()
