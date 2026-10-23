#!/usr/bin/env python3
"""Where a tick's cycles go, in the original and the faster ROM.

    profile.py BUILD [--ticks N] [--seed S] [--players 1|2] [--top N]

Both ROMs play the same game from the same buttons (tests/drive.py), from
the start of stage 1, and every instruction's cycles are counted against
the routine it is in (exclusive) and every routine that called it and has
not returned (inclusive), by JSR and RTS. A routine is named by the label
the disassembly's listing gives the code it is in, or, in the PRG RAM, the
faster ROM's own. Only ticks of play are counted; the cycles are each one's
own, a tick's lag frames' NMIs among them. An interrupt's handler is
counted as its own, "IRQ" or "NMI", and not in what it broke into.
"""

import argparse
import bisect
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tests"))

from console import Console, load_labels  # noqa: E402
from drive import Player  # noqa: E402

BANKS = ["00", "02", "03", "04", "05", "06", "07", "08", "0A", "0C", "FF"]
LINE = re.compile(r"^[-C D0-9I]{12}0x([0-9A-F]{6}) ")
LABEL = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):")
INES = 0x10
ORIGINAL_FIXED = 0x1C000            # the fixed bank's place in the original's PRG
JSR, RTS, RTI = 0x20, 0x60, 0x40
KEY = [
    "FF:sub_CFF9", "FF:sub_D2D1", "FF:sub_FEAA_update_sound_engine", "FF:sub_FF97",
    "04:sub_0x0080C6", "04:sub_80F9", "04:sub_0x008142", "04:sub_8161", "04:sub_0x008FD0",
    "05:sub_A4A3", "FF:sub_F3B3_execute_script", "FF:sub_F34C_prg_bankswitch",
    "FF:sub_D9AC", "0A:sub_96C9", "FF:sub_F994",
    "fast:fast_probe", "fast:fast_sprites", "IRQ", "NMI",
]


def listing_names(upstream):
    """PRG offset in the original: the routine's name, from the listing's
    file offsets. A label of a branch's or a loop's is its routine's."""
    starts, names = [], []
    for bank in BANKS:
        pending = []
        with open(os.path.join(upstream, "bank_%s.asm" % bank), encoding="latin-1") as source:
            for line in source:
                label = LABEL.match(line)
                if label:
                    pending.append(label.group(1))
                    continue
                tagged = LINE.match(line)
                if not tagged:
                    continue
                routine = [name for name in pending if not name.startswith(("bra_", "loc_"))]
                pending = []
                if routine:
                    starts.append(int(tagged.group(1), 16) - INES)
                    names.append("%s:%s" % (bank, routine[0]))
    order = sorted(range(len(starts)), key=starts.__getitem__)
    return [starts[i] for i in order], [names[i] for i in order]


class Profiler:
    def __init__(self, nes, upstream, dbg):
        self.nes = nes
        self.starts, self.names = listing_names(upstream)
        # The faster ROM has its fixed bank at the end of twice the PRG.
        self.fixed = len(nes.prg) - 0x4000
        ram = sorted((value, name) for name, value in load_labels(dbg).items()
                     if 0x6000 <= value < 0x8000 and name.startswith("fast_"))
        self.ram_starts = [value for value, _ in ram]
        self.ram_names = ["fast:" + name for _, name in ram]
        self.flat, self.incl = {}, {}
        self.edges = {}             # (caller, callee): [calls, inclusive cycles]
        self.shadow = []
        self.broken_into = []       # the shadow stacks the interrupts put aside
        self.counting = False
        self._cache = {}

    def name(self, address):
        bus = self.nes.bus
        if address >= 0x8000:
            offset = bus.windows[(address - 0x8000) >> 13] + (address & 0x1FFF)
            if offset >= self.fixed:
                offset += ORIGINAL_FIXED - self.fixed
            elif offset >= ORIGINAL_FIXED:
                return "fast:bank"          # the faster ROM's own bank
            cached = self._cache.get(offset)
            if cached is None:
                i = bisect.bisect_right(self.starts, offset) - 1
                cached = self._cache[offset] = self.names[i] if i >= 0 else "?"
            return cached
        if address >= 0x6000:
            i = bisect.bisect_right(self.ram_starts, address) - 1
            return self.ram_names[i] if i >= 0 else "fast:?"
        return "RAM"

    def install(self):
        mpu, bus = self.nes.mpu, self.nes.bus
        step = mpu.step

        def interrupt(kind, take):
            def taken():
                self.broken_into.append(self.shadow)
                self.shadow = [kind]
                take()
            return taken
        mpu.irq = interrupt("IRQ", mpu.irq)
        mpu.nmi = interrupt("NMI", mpu.nmi)

        def counted():
            if not self.counting:
                return step()
            pc = mpu.pc
            opcode = bus[pc]
            before = mpu.processorCycles
            here = self.name(pc)
            callee = self.name(bus[pc + 1] | bus[pc + 2] << 8) if opcode == JSR else None
            step()
            cycles = mpu.processorCycles - before
            self.flat[here] = self.flat.get(here, 0) + cycles
            for name in set(self.shadow):
                self.incl[name] = self.incl.get(name, 0) + cycles
            for pair in set(zip(self.shadow, self.shadow[1:])):
                self.edges.setdefault(pair, [0, 0])[1] += cycles
            if opcode == JSR:
                if self.shadow:
                    self.edges.setdefault((self.shadow[-1], callee), [0, 0])[0] += 1
                self.shadow.append(callee)
            elif opcode == RTS and self.shadow:
                self.shadow.pop()
            elif opcode == RTI and self.broken_into:
                self.shadow = self.broken_into.pop()
        mpu.step = counted


def run(rom, dbg, upstream, args):
    nes = Console(rom, dbg)
    player = Player(nes, two_players=args.players == 2, seed=args.seed, stage=args.stage)
    profiler = Profiler(nes, upstream, dbg)
    profiler.install()
    player.to_play()
    player.run(30)
    first = len(player.states)
    profiler.counting = True
    player.run(args.ticks)
    profiler.counting = False
    costs = player.tick_cycles()[first:]
    return profiler, costs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("build")
    parser.add_argument("--ticks", type=int, default=600)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--players", type=int, default=2, choices=(1, 2))
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--stage", type=int, default=0, help="0-4: stage 1 to 5")
    parser.add_argument("--dump", help="write the faster ROM's counts here, as JSON")
    args = parser.parse_args()
    upstream = os.path.join(args.build, "upstream")
    results = []
    for name in ("contraforce", "contraforce_fast"):
        rom = os.path.join(args.build, name + ".nes")
        results.append(run(rom, os.path.join(args.build, name + ".dbg"), upstream, args))
    (orig, orig_costs), (fast, fast_costs) = results
    print("%d players, seed %d, %d ticks of stage %d" % (args.players, args.seed, args.ticks,
                                                       args.stage + 1))
    if args.dump:
        import json
        with open(args.dump, "w") as handle:
            json.dump({"ticks": args.ticks, "flat": fast.flat, "incl": fast.incl,
                       "edges": [[a, b, n, c] for (a, b), (n, c) in fast.edges.items()],
                       "orig_flat": orig.flat, "orig_incl": orig.incl}, handle)
    for label, costs in (("original", orig_costs), ("faster", fast_costs)):
        ranked = sorted(costs)
        print("  %-9s a tick: median %6.0f, 9 in 10 under %6.0f, over 29780: %4.1f%%" % (
            label, statistics.median(ranked), ranked[int(0.9 * len(ranked))],
            100 * sum(cost > 29780 for cost in ranked) / len(ranked)))
    ticks = args.ticks
    print("\ninclusive, cycles a tick:    original   faster")
    for key in KEY:
        print("  %-30s %8.0f %8.0f" % (key, orig.incl.get(key, 0) / ticks,
                                       fast.incl.get(key, 0) / ticks))
    print("\nexclusive in the faster ROM, cycles a tick:")
    for name, cycles in sorted(fast.flat.items(), key=lambda item: -item[1])[:args.top]:
        print("  %8.0f  %s" % (cycles / ticks, name))


if __name__ == "__main__":
    main()
