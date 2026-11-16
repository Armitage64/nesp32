# Bubble Bobble, two consoles

A netplay build of Bubble Bobble (US, NES): a two-player game on two
consoles, each with a [nesp32](../..) on controller port 2, meeting by a
room's code as [Contra](../contra), [Dr. Mario](../drmario),
[Tetris](../tetris) and [TMNT II](../tmnt2) do. nesp32's
[`docs/MULTIPLAYER.md`](../../docs/MULTIPLAYER.md) has what the netplay
games share.

The session and its menu are done and tested in the simulation: 2P START
at the title is the menu, HOST GAME and JOIN GAME meet by a room's code or
by an address, and the two consoles play one game, kept the same by their
buttons. A session lasts past a game over: the title comes back as part of
it, and its 2P CONTINUE goes on at the round the two had reached. On
hardware too (November 2026): a session plays on two real consoles, and
goes straight from the menu into the game for two. Faster ways through the game's busiest
routines keep a session at the game's own speed ("The frame rate",
below).

**The game is not in this repository,** and there is no disassembly of it
to start from. The build makes one:

- `baserom.nes`, a copy of the game, which whoever builds puts in this
  directory (or says where it is with `BASEROM=`). It is the US release:
  `make verify` checks what is built against its SHA-512.
- `tools/game.map`, the names and comments, and `tools/entries.txt`, where
  the game was seen to run on the simulated console (`make trace` writes it
  again). Neither holds any of the game's bytes: only addresses.

`tools/convert.py` makes ca65 source of the ROM in `build/gen`. Every byte
is the ROM's. What is code is found by following it from where the game
was seen to run, which comes first, and from the vectors; the rest is
data. Three routines print a string whose address follows the JSR that
calls them (`inline` in the map), and the converter writes that address
as one. Each label asserts its address, which ld65 checks: a change that
moves any of the game does not link. Each run of 32 bytes of $FF or more
that is not code is a label of its own, `FREE_b_oooo`, which a netplay
build can fill with a macro.

The source is copied to `build/src`, and `patches/` puts the netplay's few
lines into the copy, all under `.ifdef NETPLAY` and each the same length
as the line it replaces, or a label alone. The original is built from the
patched source too, and `make verify` says it is still the ROM.

```sh
make            # build/bubblebobble.nes, the original, build/bubblebobble_net.nes, and
                # build/bubblebobble_net_slow.nes, with the game's own routines, for the tests
make verify     # the original matches its SHA-512
make test       # the simulation's tests (needs requirements-dev.txt)
make patches    # patches/ again, from what has been changed in build/src
make bps        # dist/'s patch again, for players
make trace      # tools/entries.txt again, from the game run on the simulated console
```

Needs cc65 (`ca65`, `ld65`), Python 3, `patch`, and a C compiler: the
tests run the ROM against nesp32's firmware built for this computer.

A change to `tools/game.map` or `tools/entries.txt` can move the lines of
the converted source, and `patches/` has line numbers and no lines of
context: after one, check that `make` still patches what it should before
editing `build/src` again.

## The patch, for players

`dist/bubblebobble_net.bps` is the netplay ROM as a patch to the US
release: apply it to your own copy of the game with any BPS patcher
(Floating IPS, or RomPatcher.js in a browser), and put the ROM it makes on
a flash cartridge. A BPS patch knows the ROM it is for, and a patcher
refuses any other: the US release with its iNES header, 163856 bytes,
CRC32 `D3A91B41`, as `make verify` knows it.

The patch holds none of the game. Nothing of the game moves in the netplay
build, so what differs is its header, its code at the end of bank 6 and in
the fixed bank's free bytes, and the instructions that call it; what the
patch has of the game, it copies from the player's own ROM.
`tests/test_patch.py` holds the patch in `dist/` to the ROM this tree
builds: after a change to the netplay, `make bps` writes it again.

## The cartridge

An MMC1 with 128 KB of PRG ROM in eight banks of 16 KB, and 32 KB of CHR
ROM in 4 KB banks. The game keeps the last bank fixed at $C000 and switches
the others at $8000: bank 6, its own code (`HOME_BANK`, $04A3), for most
of the time; bank 4, the sound engine, for a moment each frame; banks 0 to
3 for each round's data. The original has no PRG RAM, and never touches
$6000-$7FFF.

The netplay ROM is on the same mapper with 8 KB of PRG RAM, which its NES
2.0 header asks for: an MMC1 board with RAM, as many cartridges were. The
game keeps the RAM on (bit 4 of each PRG bank it writes is clear).

Free in the ROM: the end of bank 6 from $A5A8 (6.7 KB, the netplay's 5.2
KB), the end of bank 3 (10.5 KB), 4 (9.8 KB) and 5 (8.8 KB), and in each of
banks 0 to 2 two runs of some 2.3 KB. The fixed bank has 73 bytes free at
its end, and four routines of the Famicom Disk System's game that nothing
calls (88 bytes): three reads of the controllers, and the sprites or the
background turned on or off alone.

## How the netplay works

As in every netplay game (nesp32's
[`docs/MULTIPLAYER.md`](../../docs/MULTIPLAYER.md)): both consoles run the
whole game, only the buttons cross, a byte a tick, and a console takes a
tick only when it has both players' buttons for it. All of Bubble Bobble's
game runs in its NMI, as Contra's and TMNT II's does: the NMI makes the
picture's writes, reads the controllers, and runs the game's tasks, five
coroutines each on its own stack in page 1 (`TASKS_RUN`), which sleep for
a number of frames (`TASK_SLEEP`). So the netplay is TMNT II's
(`net/net.asm`, at the end of bank 6), with what has to be in the fixed
bank in its free bytes and in the unused routines' (`net/fill.inc`), and
each call from there to bank 6 through `net_call`, which switches the bank
in and puts the game's own back.

**What had to change in the game**, by `patches/`:

- **The exchange, and the controller read with it** (`net_ctrl_hook`), in
  place of the NMI's read of the controllers, after its writes to the PPU
  and before the tasks: with no session, the game's read and OUT0 back to
  mark after it; in a session, both players' buttons for the tick, as the
  game's read leaves them, or in a stall the end of the NMI with none of
  the game done. The PPU's list of writes is left empty by the NMI, so the
  NMIs of a stall write nothing and the picture stands. The game has no
  splits of the screen and no IRQs: nothing can break into the serial
  routines.
- **The sound in every NMI.** The sound engine was a task, which would
  run once a tick: every stall would hold the music back. It runs in every
  NMI (`net_sound`), and its task only sleeps. The game reads nothing of
  the engine's memory ($CA-$F0).
- **`IDLE_COUNT`**, which the main loop counts up to $FF from the reset
  and the game reads as it plays. It is $FF long before the title, but how
  far it had got at the first NMI was a matter of cycles. The netplay ROM
  has it $FF from the reset (`net_reset`).
- **An NMI while the game's is under way does nothing.** The game turns
  the NMI off as its handler begins and on as it ends, but turns it on
  once before the end, after Start at the logo. An NMI that then comes
  before the end would run the game's again inside it; whether one comes is
  a matter of cycles, and in a session's first frames the exchange made it
  come on one console and not the other. `net_nmi` keeps a flag from the
  game's NMI's start to its end (`net_nmi_done`), and an NMI that finds it
  set does nothing. The original never had one in 6000 frames of play.
- **The reset** (`net_reset_hook`), once the game has set itself up: OUT0
  to mark, `IDLE_COUNT` up, and a session if one was asked for. A session
  goes straight into its game for two (`net_logo`): the logo's set-up
  after Start (`LOGO_SET_UP`: the screens cleared, the CHR banks and the
  palette), and on to the title's choices' code, which takes 2P START as
  chosen (`net_title_cursor`). Neither the logo nor the choices are drawn.
- **The title's Start** with 2P START chosen and no session
  (`net_title_start`), which is the menu's from then on: the NMI is the
  menu's (`net_nmi`), and the title's task sleeps until LOCAL GAME, when
  it goes on as the game's 2P START.
- **Two of the game's busiest routines**, the playfield's tile under a
  point (`TILE_AT`, $D0BE) and a bubble's push away from the others
  ($DAE4), begin with a JMP to a faster way that does the same, from the
  PRG RAM (`net/fast.inc`; "The frame rate", below).
- **The title's cursor** (`net_title_cursor`, `net_title_select`). In a
  session it begins on 2P START, and Select passes over the choices for
  one, 1P START and 1P CONTINUE. With no session Select passes over 2P
  CONTINUE, which goes on with a session's game. The title reads player
  1's buttons alone, as the game does: in a session the host chooses.

**The menu** is TMNT II's (`net/menu.inc`), in bank 6, its memory in the
PRG RAM. Its cursor is the title's own marker, its letters the title's,
its colours the title's text's, and the mark under the letter being edited
is a line from the logo's tiles, in the row below.

**The netplay's memory** is the PRG RAM: its own and the menu's at
$6000-$62FF, the faster ways' code from $6400, which the reset copies
there from bank 6, and the order that starts a session at $7F00. The
link's serial routines need six bytes of zero page: $F1-$F4, which only
an unused routine names, and $64-$65, which nothing does
(`tests/test_console.py` holds the game to that).

**A game over in a session.** The game over's screen and the title are
ticks like any other, so the session goes on through them: Start on player
1's console, 2P CONTINUE, and a round to begin at, up to the furthest the
two reached, as in the original (`tests/test_continue.py`).

**What keeps the frames' time**, and is left out of the digest and of
what the tests compare: the sound engine's memory ($CA-$F0) and the
scratch at $00-$0F, the PPU's status as the NMI read it ($20) and where
the OAM's DMA begins ($049F), for the sprites' flicker, and the stacks:
the path a sound the game asks for takes through the engine depends on
what the engine is playing, and leaves other dead bytes below the asking
task's stack.

## The frame rate

All of the game runs in its NMI, and the exchange of buttons is made there
too: some 3100 cycles of a frame's 29780, and some 130 more for the two
bank switches of `net_call`, less the game's own double read of the
controllers that it replaces (some 690). A frame whose work does not end
before the next vblank has no NMI there, and the game stands still for a
frame.

Most rounds have the room, but the busiest are nearly full already: round
91's NMI is 25000 cycles as a median, round 50's 24500. With the game's
own code, the busiest rounds would play slower in a session than the
original does on one console.

**Where the time goes**, in round 66, the busiest: the bubbles (task 4).
Each of the 15 moves each frame, looking up the playfield's tile under a
point (`TILE_AT`, $D0BE, 16 calls a frame at 109 cycles), and now and then
looks over every other bubble and monster for one it is near, to be pushed
away from (`$DAE4`, some 3000 cycles a frame). The game's loops over the
objects step to the next with a call (`$C39E`, some 100 calls a frame),
and test a pair with another (`$C43E`, 55 calls).

**What the netplay ROM does instead** (`net/fast.inc`), from the PRG RAM,
where the reset copies it: the game's routine begins with a JMP to its
faster way, which does what it does.

- **The tile under a point** from two tables of the playfield's rows, in
  place of the shifts and branches that work out the row's address: 65
  cycles in place of 109.
- **The push away from the bubbles** with the step and the test of a pair
  in line, each the same instructions as the game's, so that the flags are
  the same; only the calls are gone.

**What it saves**, over all 100 rounds, two players pressing at random for
1200 frames each:

| Frames that overrun | alone | in a session |
|---|---|---|
| The original | 0.2% | 2.0% |
| The netplay ROM | 0.0% | 0.2% |
| Round 66, the busiest, the original | 8% | 26% |
| Round 66, the netplay ROM | 0% | 5% |

"In a session" is each frame's NMI with the exchange's cost added. So a
session drops about as many frames as the original game does on one
console. The original game is left as it was, its slowdown too: it has no
PRG RAM to run the faster ways from.

**That it is the same game.** `tests/test_fast.py` holds the netplay ROM to
`bubblebobble_net_slow.nes`, the same build with the game's own routines:
each faster way and the game's, from 400 states of memory and registers at
random, leave the same memory, registers and flags (but for the dead bytes
below the stack, which the game's calls leave and the faster ways do not);
and rounds 1, 50, 66, 80 and 91 are the same game tick by tick. It matters
beyond the speed: both consoles run the same build, but a difference would
change the digest.

## The simulation

`tests/console.py` is TMNT II's console on py65 with Bubble Bobble's
cartridge: the MMC1's serial port and PRG banks, and the PRG RAM.
`tests/drive.py` plays from the title to a game for two, and to any round:
put the round in `ROUND` ($0401) at the title and choose 2P CONTINUE.
`tests/netplay.py` is two of them, each with nesp32's firmware built for
this computer, and a network between.

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
make test
```

## To do

1. **More on hardware**: a game over and a continue in a session, the
   busiest rounds (66, 80, 65) with the faster ways, and the music through
   stalls.
2. **The ending**, round 100 and after, has not been played in the
   simulation; nor the password's screen in a session.
3. **The release**: the patch in nesp32's `tools/gen_web.py` and the home
   page's downloads.
