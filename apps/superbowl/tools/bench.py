#!/usr/bin/env python3
"""How Tecmo Super Bowl's frames go, the original against a session, on the
simulated consoles.

    bench.py ROM DBG NET_ROM NET_DBG [--seeds 4] [--frames 1500] [--delay 10]

A preseason game for two, MAN VS MAN, Buffalo against Cleveland, from its
kickoff: on the original by its own menus, on one console with both
controllers; on the netplay ROM in a session, two consoles each with
nesp32's firmware and a network between (tests/netplay.py), player 1 on the
first and player 2 on the second. Then `--frames` frames of both players'
buttons at random (test_lockstep.py's), the same for each seed on both.

Each NMI from the kickoff on is one of:

  a lag     it found a task at work (or one woken and not yet run): the
            frame before it was not enough for the tick before it. In the
            original the NMI breaks into the task and the game goes on in
            the middle of it; in a session the NMI does no more than the
            screen's splits, and the game is a frame behind.
  a tick    every task asleep, and the NMI ran them (NMI_UPDATE_RANDOM_NUMS).
  a stall   every task asleep, and in a session the other console's
            buttons not yet there: the tasks are not run.

and a frame with the NMI off (the game turns it off to draw a scene) is
counted on its own.

A tick's length is from its vblank to the main thread back in the idle
loop with every task asleep; the part of it before the tasks (the NMI's
writes to the PPU, the sound, the read, and in a session the exchange and
what it keeps) is the NMI's own. A tick longer than a frame is a lag.

The two ROMs are not the same game once a session is in (a lag in a
session takes a frame from the game, and in the original it does not), so
they are compared over seeds, not tick for tick.
"""

import argparse
import functools
import os
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tests"))
# The nesp32's firmware built for this computer, as the Makefile has it.
NESP32 = os.environ.get("NESP32", os.path.join(HERE, "..", "..", ".."))
NESP_BUILD = os.environ.get("NESP_BUILD", os.path.join(HERE, "..", "build", "nesp"))
os.environ["NESP_BUILD"] = os.path.abspath(NESP_BUILD)
sys.path.insert(0, os.path.abspath(NESP_BUILD))
sys.path.insert(0, os.path.join(os.path.abspath(NESP32), "host"))

from console import Console  # noqa: E402
from drive import INTRO_FRAMES, PAD_A, PAD_DOWN, PAD_RIGHT, PAD_START, TITLE_FRAMES  # noqa: E402
from drive import marker_row  # noqa: E402
from test_lockstep import moves  # noqa: E402

FRAME = 29780.5
TASKS = (0x02, 0x07, 0x0C, 0x11, 0x16, 0x1B, 0x20, 0x25)
TASK_RUNNING = 0x12             # RUNNING, WAITING and CREATED are this or more
# The main menu to the kickoff (tests/netplay.py's Table.to_game): each a
# wait, then three frames of a button on player 1's or player 2's.
TO_GAME = [(90, 0, PAD_A), (100, 0, PAD_DOWN), (40, 0, PAD_A), (150, 0, PAD_A),
           (60, 1, PAD_RIGHT), (40, 1, PAD_A)]
# And past the kickoff's own wait for the screens and the kick, with no
# buttons, so that what is timed is the game.
SETTLE = 120
# The title's Start, tried this many times for the main menu.
MENU_TRIES = 8
# P1_TEAM and P2_TEAM at the kickoff: Buffalo and Cleveland.
TEAMS = (0x00, 0x06)


class Bench(Console):
    """A console that sorts its NMIs into lags, ticks and stalls, and times
    its ticks, once `timing` is set."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rom_name = os.path.basename(args[0])
        self.timing = False
        self.lags = self.stalls = self.off = 0
        self.ticks = []             # each tick's length, in cycles
        self.heads = []             # each tick's NMI to its tasks, in cycles
        self._vblank_at = None
        self._tick_start = None
        self._idle = (self.labels["CHECK_TASKS"], self.labels["UPDATE_CURRENT_TASK"])
        self.watch("NMI_UPDATE_RANDOM_NUMS", Bench._tasks_run)
        self.watch("CHECK_TASKS", Bench._at_idle)

    def watch(self, name, function):
        """As Console's, but another watch at the same place is kept, and
        runs first (the table's, and the console's own at CHECK_TASKS)."""
        address = self.labels.get(name, name)
        before = self.watches.get(address)
        if before is None:
            self.watches[address] = function
            return

        def both(console):
            before(console)
            function(console)
        self.watches[address] = both

    def _asleep(self):
        return all(self.ram[task] < TASK_RUNNING for task in TASKS)

    def _vblank(self):
        if self.timing and not self.ctrl & 0x80:
            self.off += 1           # the game has turned its NMI off: a frame lost too
        elif self.timing:
            pc = self.mpu.pc
            if self._tick_start is not None or not (
                    self._idle[0] <= pc < self._idle[1] and self._asleep()):
                self.lags += 1
                self._vblank_at = None
            else:
                self._vblank_at = self.mpu.processorCycles
        super()._vblank()

    @staticmethod
    def _tasks_run(console):
        if console._vblank_at is not None:
            console.heads.append(console.mpu.processorCycles - console._vblank_at)
            console._tick_start = console._vblank_at
            console._vblank_at = None

    def _at_idle(self):
        if self._vblank_at is not None and self._asleep():
            self.stalls += 1        # an NMI at idle that did not run the tasks
            self._vblank_at = None
        if self._tick_start is not None and self._asleep():
            self.ticks.append(self.mpu.processorCycles - self._tick_start)
            self._tick_start = None


def to_game(nes):
    """From the main menu to the kickoff, as Table.to_game, with both
    players' presses on the one console's two controllers; and past it."""
    for wait, side, button in TO_GAME:
        nes.run(wait, (0, 0))
        pads = [0, 0]
        pads[side] = button
        nes.run(3, tuple(pads))
    nes.run(SETTLE, (0, 0))
    check_game(nes)


def check_game(nes):
    teams = (nes.byte("P1_TEAM"), nes.byte("P2_TEAM"))
    if teams != TEAMS:
        raise RuntimeError("%s: teams %02X and %02X, not Buffalo and Cleveland"
                           % (nes.rom_name, *teams))


def original(rom, dbg, seed, frames):
    nes = Bench(rom, dbg)
    nes.run(INTRO_FRAMES)
    nes.run(3, (PAD_START, 0))
    nes.run(TITLE_FRAMES, (0, 0))
    # The title's Start, until the main menu's arrow is up: where a session
    # begins. (The menu's words are pictures, not the font.)
    for _ in range(MENU_TRIES):
        nes.run(3, (PAD_START, 0))
        for _ in range(TITLE_FRAMES // 10):
            nes.run(10, (0, 0))
            if marker_row(nes) is not None:
                break
        else:
            continue
        break
    else:
        raise RuntimeError("the original never came to its main menu")
    to_game(nes)
    nes.timing = True
    pads = moves(seed)
    for _ in range(frames):
        nes.run(1, next(pads))
    return nes.lags, nes.stalls, nes.ticks, nes.heads, nes.off


def session(rom, dbg, seed, frames, delay):
    from netplay import Table
    from wire import ms
    table = Table(functools.partial(Bench, rom, dbg), delay=ms(delay))
    table.start()
    table.to_game()
    table.run(SETTLE)
    for console in table.consoles:
        check_game(console)
        console.timing = True
    table.play(frames, moves(seed))
    table.same_game()
    return [(console.lags, console.stalls, console.ticks, console.heads, console.off)
            for console in table.consoles]


def report(name, runs):
    lags = sum(run[0] for run in runs)
    stalls = sum(run[1] for run in runs)
    ticks = sorted(tick for run in runs for tick in run[2])
    heads = [head for run in runs for head in run[3]]
    off = sum(run[4] for run in runs)
    frames = lags + stalls + len(ticks) + off
    over = sum(1 for tick in ticks if tick > FRAME)
    print("%-22s %6d  %5.1f%%  %5.1f%%  %5.1f%%  %5.1f fps  %6d  %6d  %6d  %5.1f%%" % (
        name, frames, 100.0 * off / frames, 100.0 * lags / frames, 100.0 * stalls / frames,
        60.0988 * len(ticks) / frames, int(statistics.median(heads)) if heads else 0,
        int(statistics.median(ticks)) if ticks else 0,
        ticks[int(0.99 * (len(ticks) - 1))] if ticks else 0,
        100.0 * over / len(ticks) if ticks else 0))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("rom")
    parser.add_argument("dbg")
    parser.add_argument("net_rom")
    parser.add_argument("net_dbg")
    parser.add_argument("--seeds", type=int, default=4)
    parser.add_argument("--frames", type=int, default=1500)
    parser.add_argument("--delay", type=float, default=10,
                        help="the network's delay each way, in ms (default 10)")
    parser.add_argument("--jobs", type=int, default=os.cpu_count())
    args = parser.parse_args()
    seeds = range(1, args.seeds + 1)
    with ProcessPoolExecutor(args.jobs) as pool:
        originals = [pool.submit(original, args.rom, args.dbg, seed, args.frames)
                     for seed in seeds]
        sessions = [pool.submit(session, args.net_rom, args.net_dbg, seed, args.frames,
                                args.delay) for seed in seeds]
        originals = [job.result() for job in originals]
        sessions = [job.result() for job in sessions]
    print("A preseason game for two, %d frames from the kickoff, %d seeds; a session at "
          "%g ms each way" % (args.frames, args.seeds, args.delay))
    print("%-22s %6s  %6s  %6s  %6s  %9s  %6s  %6s  %6s  %6s" % (
        "", "frames", "NMI off", "lags", "stalls", "ticks", "NMI", "tick", "99%", "over"))
    report(os.path.basename(args.rom), originals)
    for side in range(2):
        report("%s, player %d" % (os.path.basename(args.net_rom), side + 1),
               [run[side] for run in sessions])


if __name__ == "__main__":
    main()
