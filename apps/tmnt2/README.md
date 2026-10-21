# TMNT II, two consoles

To be a netplay build of Teenage Mutant Ninja Turtles II: The Arcade Game
(US, NES): a two-player game on two consoles, each with a
[nesp32](../..) on controller port 2, meeting by a room's code as
[Contra](../contra), [Dr. Mario](../drmario) and [Tetris](../tetris) do.
nesp32's [`docs/MULTIPLAYER.md`](../../docs/MULTIPLAYER.md) has what the
netplay games share.

So far this builds the original, byte for byte. The netplay is still to
come (the To do below).

**The game is not in this repository.** The build takes it from two places:

- [TMNT2-NES-Reverse-Engineered](https://github.com/AaronBottegal/TMNT2-NES-Reverse-Engineered),
  Aaron Bottegal's disassembly of the game, a submodule at
  `third_party/TMNT2-NES-Reverse-Engineered`. It is a work in progress and
  a listing to read rather than a source to build: its names have
  characters no assembler takes, many are used more than once, and in a
  few places it reads data as code.
- `baserom.nes`, a copy of the game, which whoever builds puts in this
  directory (or says where it is with `BASEROM=`). It is the US release:
  `make verify` checks what is built against its SHA-512.

`tools/convert.py` makes ca65 source of the two in `build/src`. Every byte
is the ROM's: the listing says which bytes are instructions and which are
data, and gives the names and the comments. An operand is written as the
listing's name where its address has one that the assembler can be
trusted with, and as a number otherwise (75 of some 35,000 instructions,
mostly calls into a bank other than the caller's pair). The CHR ROM is cut
out of `baserom.nes`.

```sh
git submodule update --init third_party/TMNT2-NES-Reverse-Engineered
make            # build/tmnt2.nes, the original
make verify     # it matches its SHA-512
make test       # the simulation's tests (needs requirements-dev.txt)
```

Needs cc65 (`ca65`, `ld65`) and Python 3.

## The cartridge

An MMC3 with 256 KB of PRG ROM in 32 banks of 8 KB, and 256 KB of CHR ROM.
The game always switches its PRG banks in pairs, an even bank at $8000 and
the odd one after it at $A000; banks 30 and 31 are fixed at $C000 and
$E000. `tmnt2.cfg` links each bank at its address. Bank 29 is unused
(all $FF), and banks 05, 17 and 21 have 5 to 6 KB free each.

## The simulation

`tests/console.py` is Contra's console on py65 with TMNT II's cartridge:
the MMC3's PRG banks, and its scanline counter clocked by the picture's
lines and by the game's own writes to PPUADDR, raising an IRQ that is
taken when the CPU's I flag lets it. `tests/drive.py` plays from the title
to a game for two. The title's codes reach every level for the
measurements: Down five times, Right seven, B, A gives the level select,
where Right picks and A starts.

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
make test
```

## What the simulation measured

Each level by the level select, two players pressing at random, 1500
frames. A level here is the game's number for it (`LEVEL_SCREEN_ON`: 0,
then 2 to 10, the select passing over 1), not the stage the player is
told of. A frame is 29780 cycles; lines are the picture's, -1 the
pre-render line and below it the vblank.

**The splits.** Every level has its IRQ at line 47 (45 in level 2) for the
foot of the status bar, and most have more further down: level 0 four
(47, 188, 199, 202), level 2 four (45, 53, 57, 234), levels 4 and 6 three
(47, 77, 222), level 7 three (47, 109, 226), and 8 to 10 two (47, 224).
The original takes each on the line it was raised on.

**Where the exchange can go.** The NMI sets up the counter
(`IRQ_UPDATING_RTN`), lets the IRQs in (`CLI`), runs the sound engine and
only then reads the controllers (`CTRL_READ_SAFE`), at line 2 to 11 as a
median and as late as line 54. From there an exchange of 3112 cycles,
Contra's, would not be over before the first split in 6 to 13 frames in
100, and the split would come late in those, or the exchange be broken
into. From the end of the counter's setup, which is in the vblank but for
the rare frame (line 6 at the latest), the first split is never less than
5794 cycles away. So the exchange goes there, with the controller read
with it and the `CLI` after it: it has some 2700 cycles to spare, and the
splits stay where they are.

**What the exchange costs.** The share of frames that would overrun, and
so stand still, with an exchange of 3112 cycles added: level 7 34 in
100, against 4 in the original; levels 5 and
10 4 and 5; the others 2 at the most. Level 7 would play slowly. A faster
exchange (nesp32's `docs/MULTIPLAYER.md`, To do) would help it most.

**Free RAM.** Bytes no level wrote, from the reset on: $0385 to $03BF
(59 bytes, past the end of the PPU's buffer of writes at $0300, whose
writers keep it under $50 bytes and a packet), and in zero page $1A, $26,
$2C, $35-$37, $EB, $F1-$F4. Not written is not the same as not used: the
endings, the game over and the continues were not played.

**The sound engine** keeps $E0-$EF and parts of $0100-$01B3, by the
listing's names; what exactly is still to be found, for the digest.

## To do

1. **The rest of what the netplay needs to know of the game**: the sound
   engine's RAM; where the game's state is, for the digest; which banks
   are in place in the NMI after the counter's setup; the font, for the
   menu.
2. **The netplay**, from Contra's: the idle loop's random number
   (`INF_LOOP_COUNTER`, $22) stirred once a tick instead; the controller
   read and the exchange after the counter's setup, with the `CLI` after
   them; the NMI's stall; the reset and the session. Its code in bank 29.
3. **The menu**, by room code and by address, from Contra's, at the
   title's Start with 2 PLAYERS chosen (`_18_1_SUBSTATE_TITLE_SELECT`).
4. **Tests**, then hardware.

Code is to be added in free space, and the game's own changed in place by
lines of the same length: inserting into a bank moves what follows, and
some of its pointers are still numbers.
