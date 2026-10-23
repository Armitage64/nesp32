# Contra Force

Contra Force (US, NES), first made faster for one console, and then, if
that leaves room enough in a frame, a netplay build for two consoles with
a [nesp32](../..) on each, as [Contra](../contra) and [TMNT II](../tmnt2)
are.

**Status (October 2026): a faster ROM for one console, in the simulation
only.** The original builds byte for byte. The faster ROM runs eight of
the game's passes from the PRG RAM (part 1, below) and plays the same
game tick by tick; a tick of one player's play is 11% to 22% shorter at
the median, which takes most of the slowdown out of stages 1 to 4 and
some of it out of stage 5, but leaves two players far from the room a
netplay session needs ("What part 1 has measured"). Not yet tried on
hardware. Netplay is left for another time.

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
of its own (`fast/`). Where the faster code is the game's own with its
calls in line, it is made from the disassembly at build time
(`tools/probe.py`, `tools/columns.py`), so none of the game's code is kept
here. The tests hold the faster ROM to the original tick by tick in
stages 1, 3 and 5: the same buttons give the same RAM before every tick,
less what runs to the picture's clock rather than the game's (the music's,
and some counters; `tests/console.py`'s `LEFT_OUT`); and each pass to the
game's on memory taken from play and then shaken.

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
5. **The controllers** (`fast/pads.inc`): `sub_FFC8`'s loop in line, a
   button's bit 0 or bit 1 taken by AND and CMP. Done.
6. **The background test's helpers in line**, `sub_F066` to `sub_F0AD`,
   where it calls them (`tools/probe.py`). Done.
7. **Two loops** (`fast/loops.inc`): the clearing of the objects' boxes
   (`sub_F994`) a run of stores, and `sub_DEBD`'s zeros into the PPU's
   second buffer with no call for each. Done.
8. **A metatile's tiles** as the screen scrolls (`fast/columns.inc`):
   `$EC26` to the end of `sub_ECE7` from the PRG RAM, with its call for
   each tile in line (`tools/columns.py`). Done.
9. **Measure it.** Done in the simulation ("What part 1 has measured").
   Then on hardware, which has to have an MMC3 with PRG RAM and 128 KB of
   CHR ROM. Not yet.

What is left is spread thin: the game's own logic for the players, the
enemies and the bullets (some 2,000, 1,100 an enemy and 1,600 a bullet), the
scroll's building of a column (some 5,000 a tick in stages 3 and 5, its
own logic), and the music (some 1,500 a frame); none of it a loop that
being faster would change by much. The one cheap thing left is the IRQ
handlers' waits for a line's end, most of all the status bar's split
(`ofs_irq_handler_F847_00`), which waits some 300 cycles a frame for a
later line where a second IRQ could come instead: some 250 a frame, but a
change to the picture's timing that only hardware can say is right.

### What part 1 has measured

In the simulation, both ROMs playing the same game from the same buttons
(`make bench`: each stage from its start, two seeds, 500 ticks of play
each). The cycles of a tick, its lag frames' NMIs among them, and the
ticks over a frame, which stand the game still for one:

| Stage | Original, median | Faster, median | Ticks over a frame, original | Faster |
|---|---|---|---|---|
| 1 | 28,901 | 24,526 | 39.0% | 5.8% |
| 2 | 21,220 | 17,882 | 6.5% | 0.5% |
| 3 | 34,532 | 27,076 | 74.9% | 14.3% |
| 4 | 25,741 | 22,710 | 28.6% | 10.8% |
| 5 | 38,742 | 34,487 | 92.0% | 65.4% |

That is for one player. For two, after steps 2 to 4 alone, a tick was
still 38,550 cycles at the median in stage 1 and 45,587 in stage 5, where
a session needs it under about 26,700.

Against the estimates, for two players in stage 1 (`make profile`), steps
2 to 4 saved about half what was estimated: 4,700 of 9,600.

| | Estimated | Measured |
|---|---|---|
| The bank switch | 1,500 | 1,700 |
| The background test | 5,600 | 2,100 to 2,600 |
| The sprite pass | 2,500 | 900 to 1,000 |

The background test's own body is some 450 cycles a call, not the 200 the
estimate took, once it has to leave every temporary as the game's does;
and most of the sprite pass's cycles are an object's and a group's, not a
tile's.

**The game depends on the picture's clock.** The IRQ at line 190 sends
the PPU's second buffer and empties it, once a frame, and the scroll reads
the buffer's index and waits while it is full. So a tick that finds the
buffer sent or not, by how long the last one took, plays otherwise: the
original against itself with longer frames is another game within some
60 ticks of stage 3. The tests give the faster ROM the original's buffer
where one has sent it and the other not. For two consoles this is a
second thing, after the random number, that has to be made the same on
both.

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
5. **The PPU's second buffer**, sent by the IRQ at line 190 once a frame,
   which the scroll reads ("What part 1 has measured"): sent at a point
   in the tick, or the same on both consoles some other way.
6. **The lockstep tests** on two simulated consoles, and then hardware.

## To do

- The faster ROM on hardware.
- The status bar's IRQ: a second IRQ in place of its wait, tried on
  hardware.
- Part 2, another time.
