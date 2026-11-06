# Jackal, two consoles

A netplay build of Jackal (US, NES): a two-player game on two consoles,
each with a [nesp32](../..) on controller port 2, meeting by a room's code
as [Contra](../contra), [Dr. Mario](../drmario), [Tetris](../tetris),
[TMNT II](../tmnt2) and [Bubble Bobble](../bubblebobble) do. nesp32's
[`docs/MULTIPLAYER.md`](../../docs/MULTIPLAYER.md) has what the netplay
games share.

The session and its menu are done and tested in the simulation: Start at
the title with 2 PLAYERS chosen is the menu, HOST GAME and JOIN GAME meet
by a room's code or by an address, and the two consoles play one game,
kept the same by their buttons. A session lasts past a game over: its
continue screen and the title are part of it, and player 1's Start there
begins another game for two. On hardware (November 2026): sessions on two consoles connect, start in
the game for two, and play levels 1, 2 and 4, their line at 14 cycles a
bit, with a StickS3 or a StickC Plus2. Level 4 slows in its busiest
moments ("The frame rate").
The first ROM had the music and no picture in a session ("What had to
change in the game", the reset).

The netplay ROM is on another cartridge than the game's: an MMC3 (mapper
4) with 8 KB of PRG RAM and 8 KB of CHR RAM, where the game's own is a
UxROM, as for Contra ("The cartridge", below). A flash cartridge or an
emulator has to take that.

**The game is not in this repository.** What is here is the netplay code,
its tests, and a few lines to be put into the game's own code. The build
takes the rest from two places:

- [NES-Jackal_Disassembly_Fully_Commented](https://github.com/RayofJay/NES-Jackal_Disassembly_Fully_Commented),
  RayofJay's disassembly of the game, a submodule at
  `third_party/NES-Jackal_Disassembly_Fully_Commented`. It is for ASM6, and
  leaves out the graphics.
- `baserom.nes`, a copy of the game, which whoever builds puts in this
  directory (or says where it is with `BASEROM=`). It is the US release:
  `make verify` checks what is built against its SHA-512.

`tools/convert.py` makes ca65 source of the disassembly in `build/gen`:
each bank a file of its own, at its address (`.org`), and what the
disassembly leaves out (its `.PAD`s: the graphics, and the free space) an
`.incbin` of the same bytes of `baserom.nes`, which asserts where it ends.
ASM6 and ca65 differ in a few things the source uses, which the converter
deals with: its anonymous labels (a run of `-` or `+`), labels with no
colon, `(expression),Y` that is not on the zero page, an equate given
twice. The source is copied to `build/src`, and `patches/` puts the
netplay's few lines into the copy, all under `.ifdef NETPLAY` and each the
same length as what it replaces, or a label alone: none of the game moves.
The original is built from the patched source too, and `make verify` says
it is still the ROM.

```sh
git submodule update --init third_party/NES-Jackal_Disassembly_Fully_Commented
make            # build/jackal.nes, the original, build/jackal_net.nes, and
                # build/jackal_net_slow.nes, with the game's own routines, for the tests
make verify     # the original matches its SHA-512
make test       # the simulation's tests (needs requirements-dev.txt)
make bench      # how long the frames of the game take, each ROM and level
make patches    # patches/ again, from what has been changed in build/src
make bps        # dist/'s patch again, for players
make BUILD=build-level4 NET_START_LEVEL=4   # a netplay ROM whose every game begins
                # at level 4, for trying a level on hardware; not for players
```

The game has no level select and no passwords: a new game begins at level
1, and only a cleared level, or a continue, leads anywhere else. A ROM made
with `NET_START_LEVEL` writes the level as each game sets up its players,
in the same tick on both consoles, so a session of it is one game as any
is; both consoles have to have the same ROM.

Needs cc65 (`ca65`, `ld65`), Python 3, `patch`, and a C compiler: the
tests run the ROM against nesp32's firmware built for this computer.

## The patch, for players

`dist/jackal_net.bps` is the netplay ROM as a patch to the US release:
apply it to your own copy of the game with any BPS patcher (Floating IPS,
or RomPatcher.js in a browser), and put the ROM it makes on a flash
cartridge. A BPS patch knows the ROM it is for, and a patcher refuses any
other: the US release with its iNES header, 131088 bytes, CRC32
`2E52D091`, as `make verify` knows it. The ROM it makes has an NES 2.0
header.

The patch holds none of the game. Nothing of the game moves in the netplay
build, so what differs is its header, the netplay's banks, its code in the
fixed bank's free space, and the instructions that call it; what the patch
has of the game, it copies from the player's own ROM.
`tests/test_patch.py` holds the patch in `dist/` to the ROM this tree
builds: after a change to the netplay, `make bps` writes it again.

## Playing

Choose 2 PLAYERS at the title with Select, and press Start. A menu comes
up, with the title's letters and its little jeep beside the line chosen:

| | |
|---|---|
| HOST GAME | the nesp32 opens a room, and the screen shows its code, which player 2 has to enter |
| JOIN GAME | a room's code to edit, and Start joins that room |
| LOCAL GAME | the game as it always was, for a second controller on port 2 |

Select on HOST GAME's screen or JOIN GAME's meets by address instead.
When the two are connected both consoles go straight into a game for two,
with no title, and from there they are one game. Player 1 is the console
that hosted. Only player 1 can pause, and only player 1 answers the
continue screen, as in the original. At the title, in a session, Select
does nothing: a session is for two.

1 PLAYER never shows the menu, and says nothing to a nesp32.

## The cartridge

The game's own board is a UxROM: 128 KB of PRG ROM in banks of 16 KB, one
switched in at $8000 and the last fixed at $C000, and 8 KB of CHR RAM. It
has no PRG RAM, the game clears and uses nearly all of the console's own
2 KB, and it leaves 552 bytes free in its fixed bank. So the netplay ROM is
on an MMC3, as Contra's is (it is the same board), with 8 KB of PRG RAM at
$6000, the same 8 KB of CHR RAM, and twice the PRG ROM, for the room
(`net/cart.inc`, `net/jackal_net.cfg`, and the ROM's NES 2.0 header).

- **The banks.** The game's banks 0 to 6 are the MMC3's 8 KB banks two by
  two, R6 at $8000 and R7 at $A000, and its fixed bank 7 is the last two,
  at $C000 and $E000: the last in the file. Banks 8 to 15 are new, between
  them: bank 8 is the netplay's code, which the reset copies into the PRG
  RAM, and bank 9 the menu. The game switches banks in two places:
  `subChangeBank`, with the bank in Y, and `subLoadNewPatternTable`, with
  it in X. Each goes to the MMC3's two registers (`net_set_bank`,
  `net_set_bank_x`), 24 cycles more than the UxROM's one write, at five to
  seven switches in a tick of play.
- **A lag frame's NMI** runs the sound engine in bank 0 and puts the
  game's bank back, and can break into a switch between a register picked
  and its bank written. So once the bank is back, if the NMI is to return
  into a switch, it returns to its start instead (`net_lag_leave`).
  `tests/test_console.py` breaks into a switch before each of its
  instructions.
- **The reset vector** goes to `net_cart_start`, in the fixed bank's free
  space, which sets the MMC3 up as the game's board is: the CHR banks over
  the CHR RAM in order, the mirroring vertical, the PRG RAM on, the
  scanline counter's IRQ off.
- **The PRG RAM** has the netplay's code, which the reset copies there from
  bank 8: the session (`net/net.inc`), and nesp32's library with its serial
  routines and its CRC table. From there it reads the same whichever bank
  the game has in. It has the netplay's memory too (`net/ram.inc`). The
  library's serial routines need six bytes of zero page, which the
  disassembly's map has as not used: $F7-$FB and $EB.
- **The samples.** The game's drums are samples, which are in the fixed
  bank at $C000, where the MMC3 has them too.

## How the netplay works

As in every netplay game (nesp32's
[`docs/MULTIPLAYER.md`](../../docs/MULTIPLAYER.md)): both consoles run the
whole game, only the buttons cross, a byte a tick, and a console takes a
tick only when it has both players' buttons for it. All of Jackal's game
runs in its NMI, as Contra's does: the NMI sends the sprites, makes the
picture's writes, sets the scroll, runs the sound engine, reads the
controllers, and runs the game. A frame whose work does not end before the
next vblank is broken into by the next NMI, which the game answers with its
own lag frame: the scroll and the sound, and nothing else.

**What had to change in the game**, by `patches/`:

- **The exchange, and the controller read with it** (`net_read_input`), in
  place of the NMI's call of the game's read: with no session, the game's
  read and OUT0 back to mark after it; in a session, both players' buttons
  for the tick as the game's read leaves them, or in a stall the end of the
  NMI with none of the game done. The game's read reads port 2 too, which
  is the line to the nesp32: a session's reads only port 1, twice while a
  sample plays (nesp32's [`docs/PHANTOM-RIGHT.md`](../../docs/PHANTOM-RIGHT.md)).
- **The NMI** (`net_nmi`, the vector): the menu's while the menu is up,
  and after a stall the stall's (`net_nmi_stalled`): the scroll and the
  sound, as a lag frame, and the buttons tried for again; with them the
  game goes on where its NMI reads the controllers. The sprites and the
  picture's writes are sent once a tick, in its first NMI.
- **The bank switches and the lag frame's end**, for the MMC3 ("The
  cartridge").
- **The reset** (`net_cart_reset`), once the game has cleared the memory:
  the netplay's code into the PRG RAM, OUT0 to mark, and a session if one
  was asked for. A session goes straight into its game for two: the
  title's Start with 2 PLAYERS chosen, past the choice's flashing. With no
  title, the reset also turns the picture on as the title's set-up would
  (`NormalPPUMASK`, which nothing else writes): the first hardware session
  had the music and no picture.
- **The sprites** (`net_sprites`, from the PRG RAM), in place of bank 1's
  own, faster ("The frame rate").
- **The title's Start and Select** (`net_title_button`). Start with 2
  PLAYERS and no session is the menu's, with the game for two set up for
  when it gives the NMI back (LOCAL GAME). In a session Select does not
  change the choice.

**What did not have to change.** Jackal's random number counts the frames
of its game (`subProcessGameControl`), not the picture's, and a lag frame
does nothing to the game but the scroll and the sound. So even the original
plays the same game on two consoles given the same buttons, whatever the
samples steal and wherever the frames fall (`tests/test_console.py`). Its
sound engine keeps to $E0-$EF and its own part of page 1, which nothing of
the game reads.

**The scene's loads.** Where the game loads a scene (`subLoadNewPatternTable`
and the screens it draws) its NMI waits for the next vblank by looking at
PPUSTATUS with the NMI still on, and the NMI that comes with that vblank
reads PPUSTATUS too, which clears the flag. On a console the wait gets out
only when its own read comes first, which is a matter of where the CPU's
cycles fall against the picture's: a load takes a few frames more or less,
on each console. It changes nothing of the game, but a tick that loads a
scene is a few frames long, and has no exchange in them; the nesp32s wait
it out. The simulation lets the wait's read come first at the first vblank
(`tests/console.py`).

**The last boss's tank** splits the screen by waiting some 10,000 cycles in
every NMI, a stall's and a lag's too, before the second scroll is written.
The exchange comes after it.

**The netplay's memory** is the PRG RAM (`net/ram.inc`): its code from
$6000, its own and the menu's at $7800-$7AFF, and the order that starts a
session at $7F00, which the reset does not clear.

**The menu** is Bubble Bobble's (`net/menu.inc`), in bank 9. Its letters
are the title's, its cursor the title's little jeep.

**What keeps the frames' time**, and is left out of the digest and of
what the tests compare: the sound engine's memory ($E0-$F0, and page 1
from $0120 with the stack below it), the scratch at $00-$0F, and the link's
zero page.

## The frame rate

All of the game runs in its NMI, and the exchange is made there too: some
3100 cycles of a frame's 29780, less the game's own double read of both
controllers that it replaces (some 700). A tick whose work does not end
before the next vblank has no NMI of its own there, and the game stands
still for a frame.

Jackal slows down for two players on one console already. `make bench`,
both players kept in lives and pressing at random, 3 seeds of 1500 frames
for each level (levels 3, 5 and 6 are not got far into by random presses,
and are under 2% throughout):

| Ticks of play over a frame | Level 1 | Level 2 | Level 4 |
|---|---|---|---|
| The original | 11.5% | 27.0% | 49.9% |
| The netplay ROM, alone | 4.0% | 18.8% | 34.7% |
| The netplay ROM, in a session, the line at 14 cycles a bit | 5.7% | 37.2% | 43.7% |
| The same, the line at the link's 21 | 7.1% | 44.6% | 47.9% |
| The same, with the game's own routines | 11.8% | 58.1% | 56.0% |

"In a session" is each tick with the exchange's cost added: some 2500
cycles with the line at 14 cycles a bit ("The session's line", below),
3150 at 21, less the game's own read of the controllers (some 700). The original
and the netplay ROM are not the same game from the same buttons here: the
netplay ROM's LOCAL GAME skips the title's flashing, and the random number
counts the ticks. The netplay ROM and `jackal_net_slow.nes` are.

So a session plays levels 2 and 4 slower than one console does alone:
in level 4 about half its ticks take two frames, as the original's do for
two players on one console.

**The faster ways** (`net/fast.inc`), from the PRG RAM, each in place of
the game's own and leaving the same memory, registers and flags
(`tests/test_fast.py`: each from 400 states of memory at random, and each
level tick by tick against `jackal_net_slow.nes`):

- **The sprites**, bank 1's `subProcessSpriteUpdates` with its drawing of
  each object in line: one of four loops by the object's flips, the next
  slot of the OAM from a table, and the empty objects passed over in a
  register.
- **The slots left hidden** at the sprites' end: the game steps from slot
  to slot, $C4 at a time; here a run of stores, one for each place in that
  order, is entered at the first and ended by an RTS put in for the time.
- **The background's collisions** (`fctGetCollisionTypeFromRAM300_4FF`
  and its two other ways in): the place of the point's tile looked up
  where the game shifts for it.

Together they save some 1100 cycles a tick of play, the median down from
28000 to 27000 in levels 2 and 4.

What is left, by a profile of a tick of play in levels 2 and 4, is spread
thin: the bullets' and the weapons' tests against the enemies (`Label1001`,
`Label996`, 1200 to 1400 cycles a tick each, and tight already), the
enemies' routines by the game's jump table (`subExecuteCodeViaIndirectJump`,
some 60 cycles a call, 1200 to 1400 a tick), and each object's movement
(`subProcessObjectSpeed_UpdatePosition`, `subUpdateSpritePositionForScrolling`,
1000 to 2000 together), which are plain arithmetic.

## The session's line

A session's exchanges go at 14 cycles a bit, where the link's are at 21
(`NET_RATE` in the Makefile).

10 was built and tried (`NET_RATE=10`): under 11 the reply is received by
folding each sample into A, 6 cycles, and put right from a table after
(nesp32's `nes/lib/gen_link.py`). On a StickC Plus2, level 4, the music
playing (November 2026), the line held at 10, but 12% of its replies were
misheard and asked for again, against 0.6% at 14: each one is a second
exchange in its frame, and a frame with one is the frame that lags. 10 is
no faster than 14 for Jackal. A stolen fetch of a sample is 40% of a bit
at 10, and the look for a start bit 60%: there is no margin left for the
samples. The simulation had it too (9%). A game with no samples might do
better at 10. In its first NMI a session asks its nesp32
for that rate, with PEER's RATE, at the link's rate (`net_rate`); once
the answer says yes, its short frames go at it (nesp32's `nes/lib/nesp.inc`,
`nesp_fast`, and `gen_link.py --short-period`), and everything else, the
menu and its hello first, stays at 21. A nesp32 whose firmware has no
RATE says so, and the session stays at 21. Half a second of exchanges at
14 with no reply, and the console goes back to 21, and asks again 3/4 of
a second later, once its nesp32 has gone back too (it does when it has
heard nothing it could make out for half a second): three times a session
at the most. nesp32's [`docs/MULTIPLAYER.md`](../../docs/MULTIPLAYER.md),
"A faster exchange", has the design; `tests/test_lockstep.py` its cases.

On hardware (November 2026), each session's nesp32 log, the music
playing:

| | Board that hosted | Frames | Misheard, asked again | Line |
|---|---|---|---|---|
| Level 1 | StickS3 | 2376 | 0.6% | 14 throughout |
| Level 4 | StickS3 | 3663 | 0.7% | 14 throughout |
| Level 2 | StickC Plus2 | 2495 | 0.6% | 14 throughout |

A delay of 1 tick in each, and next to no frame that waited, but as a
session began and at the network's spikes (to 141 ms). In level 4 the
exchanges came at half the frame rate for some ten seconds of its busiest
play: the game's own slowdown, with the exchange's cycles on top. One
session before it ended with the connection lost; its nesp32 put the line
back at 21 half a second later, as it should, and the next session was at
14 again.

An exchange is some 2500 cycles at 14, against some 3150 at 21. 10 would
be some 2100, but needs a receiver that samples in 6 cycles, which is to
come. The drum samples are what could make 14 worse than it looks:
each fetch stops the CPU for up to 4 cycles, which the serial routines
cannot see. The session's receiver times each byte from its own start
bit, so a fetch spoils one byte at the most, and a reply misheard is
asked for again in the same NMI.

## The simulation

`tests/console.py` is Contra's console on py65 with Jackal's ROM: the
UxROM or the MMC3 with its PRG RAM, and the race of a wait for the vblank
against the NMI. `tests/drive.py` plays from the title to a game for two,
and `tests/netplay.py` is two consoles, each with nesp32's firmware built
for this computer, and a network between.

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
make test
```

## What has been learned

- **What a faster way may do.** Each leaves the game's memory, registers
  and flags as the game's own routine does, so that a session is the game
  as it is on one console: the same hits, the same damage, the same order.
  A way that would change any of that is not one.
- **What is left is spread thin.** By a profile of a tick of play in
  levels 2 and 4, after the three faster ways: the bullets' and the
  weapons' tests against the enemies (`Label1001`, `Label996`) are some
  1300 cycles a tick each, but an enemy passed over is 14 cycles and one
  looked at some 75, most of them reads and compares a faster way would
  keep: 200 to 300 cycles to win back, together. The jump table and each
  object's movement are near as short as they can be. A tick of play is
  some 27000 cycles, and a session's exchange some 3100.
- **The mapper is not where the time goes.** The game switches banks five
  to seven times a tick, of which one asks for the bank already in: some
  270 cycles a tick on the MMC3, against some 100 on the UxROM. No mapper
  would give back more than that, but for the last boss's split, which
  the MMC3's scanline IRQ could make in place of a wait of 10,000 cycles.
- **The biggest lever is the line.** The exchange was 3150 cycles, two
  thirds of them bytes at 21 cycles a bit; at 14 it is some 2500 ("The
  session's line").
- **How to measure.** `make bench` for the share of ticks over a frame;
  the netplay ROM against `jackal_net_slow.nes` only, which are the same
  game. A profile by routine: count each instruction's cycles by its
  address in a wrapper of the CPU's step, with the console's own loop
  (some 25 seconds for 900 ticks).

## To do

The frame rate in a session, in order of what each buys. Effective frames
of the game a second in play, from `make bench`'s ticks, by where the
exchange goes and the line's rate (tools as in "What has been learned"):

| | Level 1 | Level 2 | Level 4 |
|---|---|---|---|
| One console, no session | 57.7 | 50.5 | 44.5 |
| A session at 14 (now) | 56.8 | 43.7 | 41.7 |
| At 14, the exchange ahead (model) | 57.4 | 46.8 | 43.3 |
| At 10 (model) | 57.0 | 45.3 | 42.4 |

A model of each console alone, from `make bench`'s ticks; what was tried
of it in full did worse (below).

1. **The exchange ahead**: tried, and dropped (November 2026). After a
   tick that lagged, the next tick's read and exchange were made at its
   end, in the wait for the vblank, so that the busy tick after did not
   pay for them: the MMC3's scanline IRQ, at line 180, as the deadline
   after which none was begun, let in for a moment at the tick's end
   (the game runs with IRQs off), and the next NMI made its exchange
   again if the early one had not brought the other console's buttons.
   The table above is a model: one console's ticks, the exchange a cost
   that moves. Two simulated consoles in a session, the same 900 ticks of
   level 2 on three seeds, took 1149, 1169 and 1155 frames with it (46.6
   frames a second) and 1130, 1161 and 1069 without (48.2): slower, the
   games alike throughout. The early exchange seldom has the other
   console's buttons, which it is made too soon for, and costs the next
   NMI's anyway; what else it cost was not found. Measure a change to the
   exchange with two consoles, and by the frames a fixed run of ticks
   takes: ticks in a fixed run of frames compare different stretches of
   the game.
2. **The session's line at 10 cycles a bit**: tried, and no faster than
   14 for Jackal: 12% of replies misheard ("The session's line"). Left
   at 14.
3. **The last boss**: left as it is, by choice. Its split is a wait of
   some 10,000 cycles in every NMI, which the original pays as well; a
   session adds to it only the exchange, as anywhere else, and the split
   stays where it was (the exchange is after it, and a stall makes it
   too). The MMC3's scanline IRQ could make the split in place of the
   wait, but that would make the fight run faster than the original
   does, not mend anything the netplay did.
4. **The bullets' and the weapons' tests** (`Label1001`, `Label996`),
   unrolled and otherwise the game's: some 200 to 300 cycles a tick. The
   jump table (`subExecuteCodeViaIndirectJump`) and each object's
   movement are near as short as they can be. Last.

And besides:

5. **Hardware**: the music through stalls, the last boss's tank, and a
   long session with the pad log for presses nobody made
   (`make NET_START_LEVEL=6` for the last boss).
6. **The release**: the patch in nesp32's `tools/gen_web.py` and the home
   page's downloads.
