# Contra Force

Contra Force (US, NES), first made faster for one console, and then, if
that leaves room enough in a frame, a netplay build for two consoles with
a [nesp32](../..) on each, as [Contra](../contra) and [TMNT II](../tmnt2)
are.

**Status (October 2026): a faster ROM for one console, in the simulation
only.** The original builds byte for byte. The faster ROM has its bank
switch, its background test and its sprite pass from the PRG RAM, and
plays the same game tick by tick; it is about 10% faster, which takes most
of the slowdown out of one player's game but leaves two players far from
the room a netplay session needs ("What part 1 has measured"). Not yet
tried on hardware. No netplay.

**The game is not in this repository.** What is here is the faster
passes, their tests, and a few lines to be put into the game's own code.
The rest, the game's code, graphics and samples, is the `Contra Force`
directory of
[NES-Games-Disassembly](https://github.com/cyneprepou4uk/NES-Games-Disassembly),
cyneprepou4uk's disassemblies, a submodule at
`third_party/NES-Games-Disassembly` (Dr. Mario's too).

```sh
git submodule update --init third_party/NES-Games-Disassembly
make            # build/contraforce.nes (the original) and build/contraforce_fast.nes
make verify     # the original still matches its SHA-512
make test       # the simulation's tests (needs requirements-dev.txt)
make profile    # where the cycles of a tick go, in both
make bench      # how long ticks of play take in both, every stage
make patches    # patches/ again, from what has been changed in build/upstream
```

Needs cc65 (`ca65`, `ld65`), Python 3 and `patch`.

## The game, and why it is slow

All of the game runs in its NMI, as Contra's does: a frame of the game (a
*tick*) that is not done by the next vblank is broken into by an NMI that
only plays the music and sets up the picture's split (a lag frame), and
the tick goes on in the next frame. The board is an MMC3, 128 KB of PRG
ROM and 128 KB of CHR ROM, no PRG RAM. The picture is split by the MMC3's
scanline IRQ, whose handlers wait in loops for a line's end.

In the simulation, both players holding right and firing most of the time
in stage 1 (`make profile`), a tick takes as a median 28,800 cycles for
one player (28% of frames lag) and 43,800 for two (50%), against a frame's
29,780. A netplay session needs about 3,100 of those for the exchange, so a
tick has to fit in about 26,700. Where the cycles of a two-player tick go:

| What | Cycles a tick | |
|---|---|---|
| The background's test (script 00, `EE54`), ~9.5 a tick | 7,500 | half of it two bank switches round it |
| Bank switches (`F34C`/`F362`), ~47 a tick | 4,400 | with `execute_script`'s |
| The sprite pass (`D2D1`) | 6,400 | a JSR a tile, 23 cycles an empty place |
| The bullets (`0x008142`) | 6,700 | ~3.3 live |
| The scroll's columns (`0A:96C9`, every other tick) | 1,700 | |
| The music (every frame) | 1,750 a frame | |
| The IRQ's handlers (every frame) | 1,000 a frame | waits for the line's end |

## The plan

### Part 1: faster for one console (`contraforce_fast.nes`)

Each change is to the game's own code only where the game calls the
faster code, the length of what it replaces, under `.ifdef FAST`; the
faster code runs from the PRG RAM, copied there at the reset from a bank
of its own (`fast/`). The tests hold the faster ROM to the original tick
by tick: the same buttons give the same RAM before every tick, less what
runs to the picture's clock rather than the game's (the music's, and two
counters; `tests/console.py`'s `LEFT_OUT`).

1. **The build and the simulation.** Done: the original byte for byte; the
   faster ROM on an MMC3 with 256 KB of PRG ROM and 8 KB of PRG RAM; the
   simulation (`tests/console.py`, nes-contra's) with the MMC3's scanline
   IRQ, and its tick-by-tick driver (`tests/drive.py`).
2. **The bank switch from the PRG RAM**, in line (`fast/bankswitch.inc`):
   about 36 cycles fewer a switch. Done.
3. **The background's test with no switch** (`fast/probe.inc`): the
   stage's metatiles copied to the PRG RAM at a stage's first test, the
   test called directly rather than through `execute_script`. The test
   itself is the game's, made from the disassembly at build time
   (`tools/probe.py`), so none of the game's code is kept here. Done.
4. **The sprite pass from the PRG RAM** (`fast/sprites.inc`), as Contra's:
   what each tile works out again worked out once an object and written
   into the tile loops, the empty objects passed in two runs, and the
   empty places hidden by a run of stores. Done.
5. **Measure it.** Done in the simulation ("What part 1 has measured").
   Then on hardware, which has to have an MMC3 with PRG RAM and 128 KB of
   CHR ROM. Not yet.
6. If two players are to fit: the background test's own body (inline its
   helpers, `F0A4`, `F0AD`, `F098`), the bullets, the scroll's columns and
   their scripts, and the IRQ handlers' waits.

### What part 1 has measured

In the simulation, both ROMs playing the same game from the same buttons
(`make bench`: each stage from its start, two seeds, 500 ticks of play
each). The cycles of a tick, its lag frames' NMIs among them:

| Players | Stage | Original, median | Faster, median | Ticks over a frame, original | Faster |
|---|---|---|---|---|---|
| 1 | 1 | 28,901 | 25,381 | 39.0% | 11.2% |
| 1 | 2 | 21,220 | 18,748 | 6.5% | 1.5% |
| 1 | 3 | 34,532 | 27,981 | 74.9% | 19.8% |
| 1 | 4 | 25,741 | 23,400 | 28.6% | 12.2% |
| 1 | 5 | 38,742 | 35,732 | 92.0% | 75.4% |
| 2 | 1 | 43,288 | 38,550 | 99.8% | 94.7% |
| 2 | 2 | 28,703 | 25,333 | 46.2% | 26.4% |
| 2 | 3 | 48,150 | 43,488 | 99.9% | 99.9% |
| 2 | 4 | 35,366 | 29,763 | 64.1% | 49.9% |
| 2 | 5 | 49,449 | 45,587 | 100.0% | 99.8% |

Against the estimates, for two players in stage 1 (`make profile`), the
three saved about half what was estimated: 4,700 of 9,600.

| | Estimated | Measured |
|---|---|---|
| The bank switch | 1,500 | 1,700 |
| The background test | 5,600 | 2,100 to 2,600 |
| The sprite pass | 2,500 | 900 to 1,000 |

The background test's own body is some 450 cycles a call, not the 200 the
estimate took, once it has to leave every temporary as the game's does;
and most of the sprite pass's cycles are an object's and a group's, not a
tile's. A session needs a tick under about 26,700 cycles: two players are
over that by 12,000 to 19,000 cycles at the median in stages 1, 3 and 5.

### Part 2: two consoles

As Contra's netplay ROM, from what it has learned:

1. **The random number**, stirred in the idle loop with the frame counter
   (`loc_FD62_infinite_loop`), so by how long each tick took: stirred once
   a tick instead, from the frame counter and both players' buttons.
2. **The exchange in the NMI**, before the game's work and before the
   picture's first split: the first IRQ is at line 29, some 5,700 cycles
   after the NMI, and the exchange is 3,112 with the interrupts off.
3. **The menu**: 2 PLAYERS on the title for HOST GAME, JOIN GAME and LOCAL
   GAME; the session and nesp32's library in the PRG RAM, which the
   metatiles' 4 KB share, or in a bank of their own.
4. **The controllers** read once, with the drum samples' double read where
   a sample plays (nesp32's `docs/PHANTOM-RIGHT.md`).
5. **The lockstep tests** on two simulated consoles, and then hardware.

## To do

- The faster ROM on hardware.
- Part 1, step 6, if part 2 is to be tried.
- Part 2.
