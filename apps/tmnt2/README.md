# TMNT II, two consoles

A netplay build of Teenage Mutant Ninja Turtles II: The Arcade Game
(US, NES): a two-player game on two consoles, each with a
[nesp32](../..) on controller port 2, meeting by a room's code as
[Contra](../contra), [Dr. Mario](../drmario) and [Tetris](../tetris) do.
nesp32's [`docs/MULTIPLAYER.md`](../../docs/MULTIPLAYER.md) has what the
netplay games share, TMNT II among them.

The session and its menu are done and tested in the simulation: 2
TURTLES at the title is the menu, HOST GAME and JOIN GAME meet by a room's
code or by an address, and the two consoles play one game, kept the same
by their buttons. On hardware too (2026-10-22): a session plays on a real
NES, with no frame wrong at the digest since that was fixed (README's
"The exchange"), and the menu's marker shows beside its lines. And with
the faster sprite pass ("The frame rate", below) the game runs at its
own speed in a session on hardware, level 7 for two too.

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

`tools/convert.py` makes ca65 source of the two in `build/gen`. Every byte
is the ROM's: the listing says which bytes are instructions and which are
data, and gives the names and the comments. An operand is written as the
listing's name where its address has one that the assembler can be
trusted with, and as a number otherwise (75 of some 35,000 instructions,
mostly calls into a bank other than the caller's pair). The CHR ROM is cut
out of `baserom.nes`.

Some of the game's pointers are still numbers, so its code must not move.
Two things in the converted source see to that. Every label asserts its
address, which ld65 checks: a change that moves any of the game does not
link. And each run of 32 bytes of $FF or more that nothing is listed in is
a label of its own, `FREE_bb_oooo`, which a netplay build can fill with a
macro (`net/fill.inc`); a macro that does not fit does not assemble.

The source is copied to `build/src`, and `patches/` puts the netplay's few
lines into the copy, all under `.ifdef NETPLAY` and each the same length
as the line it replaces, or a label alone. The original is built from the
patched source too, and `make verify` says it is still the ROM.

```sh
git submodule update --init third_party/TMNT2-NES-Reverse-Engineered
make            # build/tmnt2.nes, the original, and build/tmnt2_net.nes
make verify     # the original matches its SHA-512
make test       # the simulation's tests (needs requirements-dev.txt)
make patches    # patches/ again, from what has been changed in build/src
make bps        # dist/'s patches again, for players ("The patch", below)
```

Needs cc65 (`ca65`, `ld65`), Python 3, `patch`, and a C compiler: the
tests run the ROM against nesp32's firmware built for this computer.

## The patch, for players

To play, there is no need to build anything. `dist/tmnt2_net.bps` is the
netplay ROM as a patch to the US release: apply it to your own copy of the
game with any BPS patcher (Floating IPS, or RomPatcher.js in a browser),
and put the ROM it makes on a flash cartridge. A BPS patch knows the ROM
it is for, and a patcher refuses any other: the US release with its iNES
header, 524304 bytes, CRC32 `C9FFBBDB`, as `make verify` knows it.
`dist/tmnt2_net.ips` is the same for a patcher that takes only IPS, which
checks nothing: it has to be applied to that file.

The patches hold none of the game: 6642 bytes in 46 places, all of them
the netplay's. Nothing of the game moves in the netplay build, every
change being the length of what it replaces, so what differs is its
header (2 bytes), its code in bank 29 (6416, all $FF in the game) and in
the fixed banks' free bytes (200, all $FF too), and the instructions that
call it: 24 bytes in ten places, none longer than four. `tools/gen_patch.py`
(at the top of this repository) refuses to write a patch with sixteen
bytes in a row that are found anywhere in the game, which once caught the
sprite pass writing a hidden tile in the game's own order (`invalid`, in
`net/sprites.inc`); and `tests/test_patch.py` holds the patches in `dist/`
to the ROM this tree builds: after a change to the netplay, `make bps`
writes them again.

## The cartridge

An MMC3 with 256 KB of PRG ROM in 32 banks of 8 KB, and 256 KB of CHR ROM.
The game always switches its PRG banks in pairs, an even bank at $8000 and
the odd one after it at $A000; banks 30 and 31 are fixed at $C000 and
$E000. `tmnt2.cfg` links each bank at its address. Bank 29 is unused
(all $FF), and banks 05, 17 and 21 have 5 to 6 KB free each.

## How the netplay works

As in every netplay game (nesp32's
[`docs/MULTIPLAYER.md`](../../docs/MULTIPLAYER.md)): both consoles run the
whole game, only the buttons cross, a byte a tick, and a console takes a
tick only when it has both players' buttons for it. All of TMNT II's game
runs in its NMI, as Contra's does, so the netplay is Contra's (its
`net/net.inc`), in bank 29 (`net/net.asm`), with what has to be in the
fixed bank in the 187 bytes the game leaves at the end of bank 31, and the
64 at the start of bank 30 (`net/fill.inc`).

**What had to change in the game**, by `patches/`:

- **The random number.** The idle loop added to `INF_LOOP_COUNTER` for as
  long as the CPU had nothing to do, so two consoles given the same
  buttons did not play the same game. The netplay ROM's idle loop does
  nothing, and the number is stirred once a tick (`net_stir`), in a game
  on one console too.
- **The exchange, and the controller read with it**, where the NMI has set
  up the scanline counter (`net_nmi_irq`), before the IRQs are let in: the
  setup's `CLI` comes after them. The first split is never sooner than
  5794 cycles after, and the exchange takes some 3100, so no IRQ breaks
  into the serial routines and no split comes late. The digest, once in
  256 ticks, takes some 5800 more, and is taken with the IRQs let in
  (`net_digest_irqs`): held off for it, the first split came 28 lines late
  and put the rest of the screen out with it, a frame wrong every five
  seconds or so on hardware. The IRQs change none of what it reads, and
  their handlers are in the fixed bank and switch only the CHR.
- **The NMI's read of the controllers** (`net_ctrl`): in a session, both
  players' buttons for the tick, as the game's read leaves them; with
  none, the game's read, and OUT0 back to mark after it.
- **The NMI itself** (`net_nmi`). An NMI after one that stalled is the
  game's own for a frame that overran, with the exchange, and goes on into
  the game if the buttons came.
- **The sprite pass**: its loop over an object's tiles
  (`SPRITE_CREATE_FROM_PTR`) and its sort of the objects jump to
  `net/sprites.inc`, which runs from the PRG RAM, so that the exchange
  costs no frames ("The frame rate", below).
- **The reset**, which turns the PRG RAM on, copies the sprite pass's
  loop into it, sets OUT0 to mark, and starts a session if one was asked
  for, at the turtle select.
- **The title's Start** with 2 TURTLES chosen (`net_title_start`), which
  is the menu's from then on; and the NMI, which is the menu's while it has
  the console.

**The menu** is Contra's (`net/menu.inc`), in bank 29, its memory in the
PRG RAM. What it keeps of text is ASCII, as the codes and addresses cross
the link, and becomes the title's tiles only as it goes to the PPU. The
title's letters have no cursor and no dash: the cursor is the title's own
marker for the line picked (object $74, two 8x16 sprites of tile $11 in
CHR bank $C4, sent from a page of the PRG RAM), and the letter being
edited is underlined with a line from the logo's tiles. LOCAL GAME goes on to the turtle
select, as the title's Start would have.

**The netplay's memory** is the 8 KB of PRG RAM at $6000 that an MMC3
cartridge can have, which the netplay ROM's NES 2.0 header asks for: the
game uses all of its own 2 KB and clears it at the reset. The link's
serial routines need six bytes of zero page, which no level writes.

**A stall** ends the NMI with the PPU's buffer of writes sent and left
empty, so the next tick's writes are the only ones in it. The countdown
the NMI keeps before it lets the picture on (`DISABLE_RENDERING_X_FRAMES`)
goes by ticks, not frames: the game reads it, to let Start skip a cutscene.

**What keeps the frames' time**, and is left out of the digest and of
what the tests compare: the sound engine's memory, as in every netplay
game, and what the IRQs keep. Their handlers run in every frame, a
stall's too, and step the background's animation in some levels (level
0's flames, `_612_STEP_UNK` and the CHR bank it picks); the game reads
nothing of it.

## The frame rate

**Why a session would drop frames.** All of TMNT II's game runs in its
NMI, and the exchange of buttons is made there too: some 3100 cycles of
cycle-timed serial with the nesp32, of a frame's 29780. A frame whose
work does not end before the next NMI overruns, and the game stands
still for a frame. Most levels have the room, but level 7's frames for two
are nearly full already (25190 cycles as a median), and with the
exchange 26 in 100 of them would overrun, against 2 in 100 without it:
level 7 would play slowly, in a session only.

**Where the time goes.** Building the sprites (`DISPLAY_OBJECTS_ROUTINE`)
is about half of level 7's frame. Its loop over an object's tiles works
out again for every tile what is the same for the whole object: whether
it is flipped either way, whether the tile moves to player 2's sheet ($40
on), the palette, and which side of the screen a tile has to be on to be
shown. That is some 160 cycles a tile, and level 7 has some 45 tiles a
frame. Then the objects are put in order by their X with a bubble sort,
every pass of it, every frame.

**What the netplay ROM does instead** (`net/sprites.inc`):

- **The tiles' loop** works all of that out once an object and writes it
  into its own instructions: the object's place as the immediates the
  tile's Y and X are added to, the flip as the immediate the attributes
  are EORed with, the $40 as an addition and a branch, the palette as a
  compare and a branch, the side of the screen as an addition and a
  limit. A flip is a subtraction in place of an addition, so there is a
  loop for each of the four ways of flipping; and each comes plain, for an
  object with no $40 and no palette of its own, which is 9 tiles in 10,
  and full. A tile takes some 105 cycles in level 7, its object's own
  work shared out among its tiles, in place of some 160.
- **The sort** is an insertion sort, which is stable as the bubble sort
  is, so the order is the same; and as the order is mostly the last
  frame's, it takes about as many compares as there are objects.
- **The PRG RAM** is where both run. The sprites' data is read through
  the banks at $8000 and $A000, wherever it is, so the loop can be in no
  switched bank; the fixed banks have no room; and code in RAM can write
  its own instructions. They are linked in bank 29, and the reset copies
  them to $6400.
- **Two hooks** in the game, each four bytes in place of four, so nothing
  else in it moves: `SPRITE_CREATE_FROM_PTR` jumps to the loop, and the
  sort's first branch to the sort.

**What it saves**, in the simulation's play:

| | the game's pass | the netplay's |
|---|---|---|
| The sprite pass, level 7 for two | 12514 cycles | 9855 |
| The sprite pass, level 7 for one | 10148 | 8062 |
| The sprite pass, level 0 for one | 4844 | 4070 |
| The sprite pass, level 3 for one | 5817 | 4737 |
| A frame, level 7 for two (median) | 25190 | 22396 |
| Frames that would overrun with the exchange, level 7 for two | 26 in 100 | 3 in 100 |

So a session now drops about as many frames as the original game does on
one console. On hardware the game runs at its own speed in a session,
level 7 for two too (2026-10-22).

**That it is the same game.** `tests/test_sprites.py` holds the netplay
ROM to `tmnt2_net_slow.nes`, the same build with the game's own pass:
3000 objects at random, and 400 passes over memory at random, leave the
same sprites and the same RAM; and levels 0, 3 and 7, for one player and
for two, are the same game tick by tick, compared as a session compares
the two consoles. It matters beyond the speed: both consoles run the
same build, but a sprite out of place would change the digest.

The original game is left as it was, its slowdown too: it has no PRG RAM
to run the loop from.

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
10 4 and 5; the others 2 at the most. Level 7 would play slowly, which
the faster sprite pass mends ("The frame rate"). A faster exchange
(nesp32's `docs/MULTIPLAYER.md`, To do) would help as well.

**Free RAM.** Bytes no level wrote, from the reset on: $0385 to $03BF
(59 bytes, past the end of the PPU's buffer of writes at $0300, whose
writers keep it under $50 bytes and a packet), and in zero page $1A, $26,
$2C, $35-$37, $EB, $F1-$F4. Not written is not the same as not used: the
endings, the game over and the continues were not played.

**The sound engine** (`SOUND_FORWARD`, once in every NMI, a lag frame's
too) keeps $E0-$F0, the bank configuration it saves at $F6, page 1 below
the stack ($0104-$01B3), $03C0-$03CF and $03E3-$03E5. The stack goes down
to $01E2 at the deepest seen. The game reads back two of the engine's
bytes: $28, which the engine sets only while it runs and always clears,
and $10E, which decides whether the game asks for sound $1B; asking only
changes the engine's memory and the banks, which are put back. So the
engine keeps to itself, as Contra's does, and the music can keep the
frames' time in a session.

**What makes two games differ.** With the idle loop skipped, two
consoles given the same buttons a tick at a time play the same game,
whatever the samples take and whenever frames overrun
(`test_without_the_idle_loop_the_game_is_the_buttons_alone`): every byte
of RAM but the sound engine's and the stack's is alike at every tick. The
idle loop's `INF_LOOP_COUNTER` is the only thing in the game that keeps
time. The digest can therefore cover any of that RAM; which of it is
worth the cycles is for the netplay.

**The banks where the exchange goes.** After the counter's setup the
banks at $8000 and $A000 are always a pair, an even bank and the one
after it, and the byte at $8000 is $20 plus the even bank's number (every
even bank begins with it, and the game's `BANK_PAIRED` reads it there).
So the netplay can switch its own bank in at $A000 for the exchange and
put the pair back from that byte. The game does map the pair 28 and 29,
and nothing in bank 28 refers to $A000-$BFFF; bank 29 is all $FF but for
its last byte ($3D).

**The font**, in the title's CHR bank: 0 to 9 at $01-$0A, A to Z at
$0B-$24, A to Z again shaded at $25-$3E, a full stop at $3F, and no dash or
colon. The title's choice is 1 TURTLE and 2 TURTLES, with a sprite beside
the one picked.

## To do

1. **The splits on every level on hardware**, through a whole game: the
   simulation has them on their lines in every level, and hardware has
   shown levels 1 and 7 so far.
2. **The original game's slowdown**, if it is wanted: the faster sprite
   pass needs somewhere to run, and the original has no PRG RAM. A build
   of the original with PRG RAM asked for in its header would do.
