#!/usr/bin/env python3
"""A netplay game for two in two headless Mesens, random buttons on both.

    mesen_soak.py GAME ROM [--frames N] [--seed S ...] [--out DIR]

Each seed is a pair of Mesens, all at once: one hosts by address and the
other joins 127.0.0.1, each with its own bridge (tools/mesen_run.py
--bridge), UDP port and folder, the rooms at host/rendezvous.py's stand-in
on this computer, so nothing reaches the real rendezvous. From the session
on, both consoles' buttons are pressed at random from the seed. The ROM's
own digest check (every 256 ticks) and its DUMP find a desync with no help
from here: a pair passes if neither bridge loses the other before the end
and neither has a dump. The end of a run is not a loss: whichever Mesen
finishes first leaves, and the other's bridge says LOST then.

    tools/mesen_soak.py superbowl apps/superbowl/build/superbowl_net.nes \\
        --frames 70000 --seed 1 --seed 2 --seed 3 --seed 4

70,000 frames, a whole Tecmo Super Bowl game at full-length quarters,
took 341 s for four pairs on a 10-core Mac (November 2026). Needs Mesen
(MESEN, as tools/mesen_run.py) and `make host`. A starting point: only
the games in GAMES have their way to a session, and docs/TODO.md ("A
soak of every netplay game") has what is still to do.
"""

import argparse
import os
import random
import re
import subprocess
import sys
import time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "host"))
from rendezvous import FakeRendezvous  # noqa: E402

# Each game's way from power-on to a session, as mesen_run.py presses
# (FRAME:BUTTONS:LENGTH), and the frame its random play may begin at.
GAMES = {
    # The intro's Start, NETWORK GAME on the title, then HOST GAME and
    # Select (by address), or JOIN GAME, Select (by address: the bridge's
    # peer-last is 127.0.0.1) and Start. A session begins at the main menu.
    "superbowl": {
        "start": ["300:start:3", "600:down:3", "700:a:3"],
        "host": ["1450:a:3", "1550:select:3"],
        "join": ["1450:down:3", "1500:a:3", "1560:select:3", "1750:start:3"],
        "play_from": 3000,
    },
}
BUTTONS = ["a", "b", "start", "up", "down", "left", "right", "a+right", "b+left", "up+a", "down+b"]
STOPPED = re.compile(r"peer: (LOST|CLOSED|FAILED)|dump of|GAMES|STOPPED")


def presses(seed, first, last):
    """Buttons at random, held 2 to 20 frames, from `first` to `last`."""
    rng = random.Random(seed)
    out, frame = [], first
    while frame < last:
        length = rng.choice([2, 4, 8, 20])
        out += ["--press", "%d:%s:%d" % (frame, rng.choice(BUTTONS), length)]
        frame += length + rng.randint(2, 30)
    return out


def start_pair(game, rom, out, frames, seed, url):
    port = 40000 + seed * 10            # the UDP port this pair's game is hosted on
    folder = os.path.join(out, "pair%d" % seed)
    guest_data = os.path.join(folder, "guestdata")
    os.makedirs(guest_data, exist_ok=True)
    with open(os.path.join(guest_data, "peer-last"), "wb") as handle:
        handle.write(bytes((127, 0, 0, 1)))
    common = [sys.executable, os.path.join(ROOT, "tools", "mesen_run.py"), os.path.abspath(rom),
              "--bridge", "--frames", str(frames), "--timeout", str(max(600, frames // 10)),
              "--shot", str(frames // 2), "--shot", str(frames - 10),
              "--bridge-arg=--rendezvous", "--bridge-arg=" + url,
              "--bridge-arg=--peer-port", "--bridge-arg=%d" % port]
    for spec in game["start"]:
        common += ["--press", spec]
    last = frames - 100
    sides = {
        "host": common + ["--bridge-data", os.path.join(folder, "hostdata")]
        + sum((["--press", spec] for spec in game["host"]), [])
        + presses(seed * 2, game["play_from"], last),
        "guest": common + ["--bridge-data", guest_data]
        + sum((["--press", spec] for spec in game["join"]), [])
        + presses(seed * 2 + 1, game["play_from"], last),
    }
    procs = []
    for side, command in sides.items():
        log = open(os.path.join(folder, side + ".log"), "w")
        procs.append(subprocess.Popen(command + ["--out", os.path.join(folder, side)],
                                      stdout=log, stderr=subprocess.STDOUT, cwd=ROOT))
    return procs


def verdict(out, seed):
    """What each side's bridge said of the session: (stopped early, lines)."""
    folder = os.path.join(out, "pair%d" % seed)
    early, said = False, []
    for side in ("host", "guest"):
        path = os.path.join(folder, side, "bridge.log")
        lines = open(path).read().splitlines() if os.path.exists(path) else []
        left = next((line[:8] for line in lines if "Mesen disconnected" in line), None)
        for line in lines:
            if STOPPED.search(line):
                said.append("%s: %s (its Mesen left at %s)" % (side, line[:120], left))
                # A loss within the last few seconds is the other Mesen ending.
                if "dump of" in line or "GAMES" in line or (left and _seconds(left) - _seconds(line[:8]) > 5):
                    early = True
        if not lines:
            early = True
            said.append("%s: no bridge log" % side)
    return early, said


def _seconds(clock):
    hours, minutes, seconds = (int(part) for part in clock.split(":"))
    return hours * 3600 + minutes * 60 + seconds


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("game", choices=sorted(GAMES))
    ap.add_argument("rom")
    ap.add_argument("--frames", type=int, default=70000)
    ap.add_argument("--seed", type=int, action="append")
    ap.add_argument("--out", default=os.path.join(ROOT, "build", "mesen-soak"))
    args = ap.parse_args()
    seeds = args.seed or [1]
    began = time.time()
    with FakeRendezvous() as server:
        procs = []
        for seed in seeds:
            procs += start_pair(GAMES[args.game], args.rom, args.out, args.frames, seed, server.url)
        for proc in procs:
            proc.wait()
    print("%d pairs, %d frames each: %d s" % (len(seeds), args.frames, time.time() - began))
    failed = 0
    for seed in seeds:
        early, said = verdict(args.out, seed)
        failed += early
        print("pair %d: %s" % (seed, "STOPPED EARLY" if early else "to the end"))
        for line in said:
            print("   ", line)
    print("shots and logs in", os.path.abspath(args.out))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
