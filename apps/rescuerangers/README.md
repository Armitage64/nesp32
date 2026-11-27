# Chip 'n Dale Rescue Rangers for two consoles

Capcom's Chip 'n Dale Rescue Rangers (NES, 1990) is a game for two
played at once, on one screen. This is its netplay ROM for nesp32: each
player on a console of their own, each console with a nesp32 on
controller port 2.

**It has been tried only in the simulation** (py65: two consoles, each
with nesp32's firmware built for this computer, and a network between).
Nothing here has been on a real NES, on the MiSTer, or in Mesen, and
there is no patch for players yet ("Not done").

At the title, Select moves the cursor to 2 PLAYERS, and Start there opens
the menu: HOST GAME, JOIN GAME (by a room's code, or with Select by an
address) and LOCAL GAME, as in nesp32's other games. Once the two nesp32s
are joined, both consoles start again from the reset and go past the
title into a game for two, player 1 on the host's console.

## Building

You need your own copy of the US release, as `baserom.nes` here. It is
not in the repository (`*.nes` is ignored).

```sh
make && make verify     # build/rescuerangers.nes, and its SHA-512 checked;
                        # build/rescuerangers_net.nes, the netplay ROM
make test               # the simulation's tests
make trace              # tools/entries.txt again (some 5 minutes)
```

The ROM's SHA-512 is in the Makefile (`SHA512_ORIGINAL`); its SHA-1 is
`39a5fdb7efd4425a8769fd3073b00dd85f6cd574`.

There is no disassembly of the game to start from, so the build makes one,
as Bubble Bobble's and River City Ransom's do. `tools/trace.py` runs the
game on the simulated console and notes every instruction it runs
(`tools/entries.txt`); `tools/convert.py` follows the code from there and
from the names in `tools/game.map`, and writes ca65 source of the whole
ROM to `build/gen`, every byte from `baserom.nes`. None of the game is in
the repository: only addresses, names and comments. So far the trace has
played only the first level, for one player and for two, and has seen
6948 instructions: some 18 KB of the 128 KB of PRG ROM is known to be
code. The rest is written as bytes, which rebuild the ROM all the same.

## The cartridge

An MMC1 with 128 KB of PRG ROM in eight banks of 16 KB and 128 KB of CHR
ROM in 4 KB banks. The game keeps the last bank fixed at $C000 and
switches the others at $8000 (`SET_PRG`); the CHR banks by `SET_CHR0` and
`SET_CHR1`, or from the NMI. Each bank ends with the same reset stub at
$BFE0 and the vectors. It has no PRG RAM, and never touches $6000-$7FFF.

Free in the ROM: next to nothing. The runs of $00 of 64 bytes or more come
to some 1.6 KB, spread over banks 0 to 6, and none is in the fixed bank,
which has 48 bytes at $FFB0 that nothing seen runs or reads. Bubble
Bobble's netplay is some 5.2 KB.

So the netplay ROM is on another board: an MMC3 (mapper 4) with 256 KB of
PRG ROM, the game's 128 KB of CHR ROM, and 8 KB of PRG RAM, which its NES
2.0 header asks for (`net/cart.inc`, `net/rescuerangers_net.cfg`). An
MMC1 could not have taken more PRG ROM: with CHR ROM in 4 KB banks, the
bit that would pick the second 256 KB is the CHR bank's.

- **The banks.** The game's banks 0 to 6 are the MMC3's 8 KB banks two by
  two, R6 at $8000 and R7 at $A000, and its fixed bank 7 is the MMC3's
  last two, at $C000 and $E000: the last in the file. Banks 8 to 15 are
  new, between them. The game's CHR bank at $0000 is R0 and R1, and the
  one at $1000 is R2 to R5.
- **The netplay's code** is in bank 8 (`net/net.asm`: the session, the
  menu and nesp32's library, 4.6 KB), which the game never has in. What
  has to be there whatever bank the game has in runs from the PRG RAM
  (`net/cart.inc`, 438 bytes), which the reset copies from the start of
  bank 9 before the game's own reset (`net_cart_start`, in the reset
  vector): the bank switches, the NMI's netplay, the controller read, the
  title's hooks, and `net_call`, which brings bank 8 in at $8000 and puts
  the game's bank back after. The fixed bank has no room: `SET_PRG`,
  `SET_CHR0`, `SET_CHR1`, the NMI's switches and the hooks are now a few
  bytes each that jump to the PRG RAM, and `net_cart_start` is in the
  room `SET_PRG`'s MMC1 writes left. Every change to the game is the
  length of what it replaces, so none of the game moves.
- **An NMI in the middle of a switch.** A write to an MMC3 register is
  two, a register picked at $8000 and its bank at $8001, and the NMI
  switches banks of its own: the CHR banks when the game asks, and bank 3
  for the sound engine. Each pick is kept in `net_select`, and the NMI
  (`net_nmi`, `net_nmi_leave`) puts back the one it found, so the switch
  it broke into goes on to the right register. `tests/test_cart.py`
  breaks into each of the three switches before each of its
  instructions. As in the original, `SET_PRG` keeps the NMI off bank 3
  while it switches and runs the sound engine after.
- **The reset's stub** at $FFE0 wrote to $FFE1 (an MMC1 reset); on the
  MMC3 that turns the scanline counter's IRQ on, so the netplay ROM's
  reads it instead. The game never lets an IRQ in (no CLI), and the
  simulation counts writes that would turn it on. One routine
  (`$D3E7`) writes to `$FFE8,y` and `$FFEA,y` with Y from $18 up, which
  wraps round to the RAM; a Y below $18 would write to the MMC3's IRQ
  registers.

With no session, the netplay ROM plays the same game as the original, tick
for tick, from power-on through a level for two (`tests/test_cart.py`),
but for `FRAME_COUNT`: the MMC3's switches take longer, and as the story's
screen comes up the netplay ROM takes one frame more, which leaves the
NMI's count of frames one ahead. Nothing seen so far reads it.

## The game, as far as it has been read

- **Tasks.** The game runs as up to four coroutines (`TASKS`, $80-$8F),
  each on its own stack in page 1. `SCHEDULE` runs the first that is
  ready; a task gives way by sleeping a number of frames (`TASK_YIELD`),
  and the NMI counts the sleeps down. In a level only task 0 was seen,
  sleeping a frame at a time.
- **The controllers** are read in one place, `CTRL_READ` ($C162), which
  `SCHEDULE` calls as it goes back to task 0: once a frame. It reads D0
  and D1 of both ports (a Famicom's expansion pads), into `PAD_HELD` and
  `PAD_PRESSED`. Each controller is read once.
- **No samples.** The reset writes 0 to $4010, and the sound engine only
  ever writes $0F to $4015: the sample channel is never on, so the
  "phantom Right" (`docs/PHANTOM-RIGHT.md`) cannot happen.
- **The NMI** ($C000) makes the PPU's writes and the OAM's DMA unless the
  picture is off, and then, in every NMI: counts `FRAME_COUNT`, counts
  down the tasks' sleeps, and runs the sound engine in bank 3. A bank
  switch under way when it comes leaves the sound engine to `SET_PRG`.
  No sprite 0 waits, no IRQ: the screen is not split.
- **The sound engine** keeps $C0-$D8 and $0700-$077F, and takes its
  orders from `SOUND_QUEUE` ($DB-$E3).
- **Random numbers**, it seems, at $E4-$E7: they change every frame, the
  pause's too.
- **The title** (`TITLE_LOOP`, bank 2): Select moves the cursor between 1
  PLAYER and 2 PLAYERS (`TITLE_PLAYERS`), and Start picks (`TITLE_START`):
  for two the story's screen, which ends by itself, and the first level.
  Left alone, the title starts a demo. In a level, Start pauses.

On the simulated console, a level for two keeps the game busy for some
18000 to 20000 cycles of a frame's 29780 with the players standing still,
and a median of some 16000 with them moving at random; fewer than 1 frame
in 100 overruns. The link's exchange takes some 2500 to 4000 cycles
(`docs/MULTIPLAYER.md`), which leaves room.

## How the netplay works

As in every netplay game (nesp32's
[`docs/MULTIPLAYER.md`](../../docs/MULTIPLAYER.md)): both consoles run the
whole game, only the buttons cross, a byte a tick, and a console takes a
tick only when it has both players' buttons for it. The netplay is Bubble
Bobble's (`apps/bubblebobble/net/`), whose game is made of tasks too; but
Bubble Bobble's runs in its NMI, and Rescue Rangers' in its main line, as
Dr. Mario's and Tetris's do.

**A tick** is an NMI that finds the game waiting: broken into `SCHEDULE`'s
look for a task to run ($FE90-$FEA5), with no task ready or running
(`net_nmi`). The reset's own code runs before there is any task, so the
tasks alone do not say; that was the first desync in the simulation, at
the title. An NMI in a session is one of three things:

- **a lag**: the game is still at its work. The NMI does nothing of the
  game: no writes to the PPU (the game may be filling their lists), no
  count of `FRAME_COUNT`, no sleeps counted down. Only the music runs
  (`NMI_SOUND`).
- **a stall**: the game is waiting, but the other console's buttons for
  the tick are not here. The NMI has made its writes to the PPU, makes the
  exchange, and stops short of waking the tasks (`net_nmi_tick`). The
  PPU's lists are empty by then, so the stall's NMIs write nothing and the
  picture stands.
- **a tick**: the NMI counts the frame and wakes the tasks (`NMI_WAKE`),
  and `CTRL_READ` takes both players' buttons for the tick from
  `net_pads` (`net_ctrl_read`), in place of the controllers.

So the game's memory depends on how many ticks there have been and on
nothing else. In the original, the NMI counts `FRAME_COUNT` and the sleeps
in every NMI, wherever it lands: with no session the netplay ROM still
does, and is the original game.

**What had to change in the game**, by `patches/`, besides the cartridge's:

- **The NMI's count of the frame and waking of the tasks** (`$C0A1`):
  `net_nmi_tick`, the session's exchange first.
- **The controllers' read** (`CTRL_READ`): `net_ctrl_read`. With no
  session it is the game's read, with OUT0 back to mark after it.
- **The reset** (where it set the MMC1's control): `net_reset`, which
  starts a session that `net_start_session` asked for (`net_boot`, in the
  PRG RAM, which the reset leaves).
- **The title's look at Start** (`TITLE_LOOP`): in a session that has just
  begun, as if Start had been pressed on 2 PLAYERS (`net_title_frame`).
- **The title's Start** (`TITLE_START`): on 2 PLAYERS with no session, the
  menu (`net_title_start`), with the title's task asleep until LOCAL GAME,
  when it goes on as the game's own game for two.

**The menu** is Bubble Bobble's (`net/menu.inc`), in bank 8, its memory in
the PRG RAM. Its letters, digits, full stop and dash are the title's, its
colours the title's text's, and its cursor the title's own.

**The netplay's memory** is the PRG RAM: its code from $6000, its own
memory and the link's from $7000, the menu's from $7100, and the order
that starts a session at $7F00. The link's serial routines need six bytes
of zero page: $AA-$AF, which nothing of the game seen so far uses past the
reset (`tests/test_console.py` holds play to it; README's "Not done": the
trace has seen only the first level).

**The digest** (one tick in 256) is of the zero page and of page 4, the
objects', but for NMI_SEEN ($90), the sound engine's ($C0-$D8) and its
queue ($DB-$E3), which run in every NMI, and the link's bytes. When two
digests differ, each console sends its RAM to its nesp32's log first
(`net_differ`, PEER's DUMP), as Bubble Bobble's does.

**The hello** is `RESC`, version 1.

## Not done

1. **Hardware**: two consoles, each with a nesp32, a session by room
   code; and Mesen. Nothing here has run anywhere but the simulation.
2. **More of the game traced**: the zone map, the later zones, the
   bosses, a game over, the continue and the end, by poking in a zone as
   Bubble Bobble's trace pokes in a round. Until then, that the game is
   the same on two consoles past the first level, and that it leaves
   $AA-$AF alone, is known only for what has been played.
3. **A game over and the game's own reset in a session.** The game jumps
   to its reset after some of its screens (`$D1D7`); in a session the
   reset keeps the session, and the title goes straight on to a game for
   two again. Not yet seen in the simulation.
4. **Where each task's stack is**, so the digest and the tests can keep
   the live part of page 1 and leave out only the dead bytes. For now
   they leave out the whole page.
5. **`make bps`** and `dist/rescuerangers_net.bps`, `make ines`, and the
   documents that list the games (the nes-netplay-port skill, "Shipping
   a change").
6. **A faster line** (`NET_RATE`), as Jackal's, if the frames want it.
