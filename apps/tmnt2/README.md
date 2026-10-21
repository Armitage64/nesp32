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
```

Needs cc65 (`ca65`, `ld65`) and Python 3.

## The cartridge

An MMC3 with 256 KB of PRG ROM in 32 banks of 8 KB, and 256 KB of CHR ROM.
The game always switches its PRG banks in pairs, an even bank at $8000 and
the odd one after it at $A000; banks 30 and 31 are fixed at $C000 and
$E000. `tmnt2.cfg` links each bank at its address. Bank 29 is unused
(all $FF), and banks 05, 17 and 21 have 5 to 6 KB free each.

## To do

1. **The simulation.** Contra's console on py65, with an MMC3: its PRG
   banks, and its scanline IRQ on the clock of cycles.
2. **What the netplay needs to know of the game**: how many IRQ splits
   each level has and where; free RAM; which banks are in place where the
   NMI reads the controllers; the title's 2-player choice and the turtle
   select; the sound engine's RAM; where the game's state is, for the
   digest; the font, for the menu.
3. **The netplay**, from Contra's: the idle loop's random number
   (`INF_LOOP_COUNTER`, $22) stirred once a tick instead; the exchange in
   `CTRL_READ_SAFE`; the NMI's stall; the reset and the session. The
   exchange has to fit beside the status bar's IRQ, which the NMI lets in
   (`CLI`) before it reads the controllers.
4. **The menu**, by room code and by address, from Contra's.
5. **Tests**, then hardware.

Code is to be added in free space, and the game's own changed in place by
lines of the same length: inserting into a bank moves what follows, and
some of its pointers are still numbers.
