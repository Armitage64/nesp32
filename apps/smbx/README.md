# SMBX, two consoles

A netplay build of the Super Mario Bros. two-player hack (Corpse Grinder
and TI, 2018), where Mario and Luigi are on the screen at once: a
two-player game on two consoles, each with a [nesp32](../..) on controller
port 2, meeting by a room's code as [Contra](../contra),
[Dr. Mario](../drmario), [Tetris](../tetris) and [TMNT II](../tmnt2) do.
nesp32's [`docs/MULTIPLAYER.md`](../../docs/MULTIPLAYER.md) has what the
netplay games share. It needs nothing new of the nesp32's firmware: its
hello says `SMBX`, and PEER and the rendezvous take any game's name.

The session and its menu are done and tested in the simulation: 2 PLAYERS
GAME at the title is the menu, HOST GAME and JOIN GAME meet by a room's
code or by an address, and the two consoles play one game, kept the same
by their buttons. It has not been played on hardware yet.

**None of the game is in this repository, and none of Nintendo's code.**
There is no disassembly of the hack to build from. Whoever builds puts the
hack's ROM in this directory as `baserom.nes` (or says where it is with
`BASEROM=`), and the build takes the whole game from it: `net/rom.asm`
copies the file by the place of each byte, around the few places the
netplay changes, and assembles the netplay's own code into the room the
hack leaves empty. What is here is that code, the places, and the tests.
`make` checks `baserom.nes` against its SHA-512 first, since the places
are good for that file and no other.

```sh
make            # build/smbx_net.nes
make verify     # baserom.nes is the hack this is for
make test       # the simulation's tests (needs requirements-dev.txt)
make bps        # dist/'s patches again, for players ("The patch", below)
```

Needs cc65 (`ca65`, `ld65`), Python 3, and a C compiler: the tests run the
ROM against nesp32's firmware built for this computer.

## The patch, for players

To play, there is no need to build anything. `dist/smbx_net.bps` is the
netplay ROM as a patch to the hack: apply it to your own copy of the hack
with any BPS patcher (Floating IPS, or RomPatcher.js in a browser), and put
the ROM it makes on a flash cartridge. A BPS patch knows the ROM it is
for, and a patcher refuses any other: the hack is a 73744-byte file, CRC32
`393BC874`, and the same SHA-512 as the Makefile's. `dist/smbx_net.ips`
is the same for a patcher that takes only IPS, which checks nothing: it
has to be applied to that file.

The patches hold none of the game: 4959 bytes in 51 places, all of them
the netplay's. They are its header, its code in bank 1 (all $FF in the
hack) and in the fixed bank's unused bytes (all 0 in the hack), and the
five instructions that call it, each in place of one of the same length.
`tools/gen_patch.py` (at the top of this repository) refuses to write a
patch with sixteen bytes in a row that are found anywhere in the hack,
and `tests/test_patch.py` holds the patches in `dist/` to the ROM this tree
builds: after a change to the netplay, `make bps` writes them again.

## What is where

| Path | Purpose |
|---|---|
| `net/rom.asm` | the ROM: `baserom.nes` by its bytes' places, the hooks, and the netplay's banks |
| `net/game.inc` | what the netplay knows of the game: where its memory and routines are, by address |
| `net/glue.inc` | what has to be in the fixed bank: the NMI, the hooks' other ends, the way into bank 1 |
| `net/net.asm` | the session: the exchange, the ticks, the digest (bank 1) |
| `net/menu.inc` | the menu (bank 1), TMNT II's with this game's screen |
| `net/net_ram.inc` | the netplay's memory, in the cartridge's PRG RAM |
| `dist/` | the netplay ROM as BPS and IPS patches to the hack |
| `tests/` | a console on py65 with the VRC6 and the 2A03's unofficial opcodes, and two of them with their nesp32s and a network between |

## The cartridge

The hack is a VRC6 (mapper 24) with 64 KB of PRG ROM in four banks of
16 KB, and 8 KB of CHR ROM. A 16 KB bank is switched in at $8000, an 8 KB
one at $C000, and the last 8 KB are fixed at $E000. The game keeps bank 2
at $8000 and bank 6 (the first half of bank 3) at $C000, and brings in
bank 0, the sound engine and the controllers' read, for a moment in each
NMI. Bank 1 is all $FF, and is the netplay's. The fixed bank has 2100
bytes of 0 at $F5AB that the game never reads, where the netplay's few
routines that the game's code calls go (`net/glue.inc`).

The reset turns the cartridge's 8 KB of PRG RAM on, and the game never
uses it: it is the netplay's memory. The netplay ROM's NES 2.0 header says
so, where the hack's own iNES header leaves it to be guessed.

The hack uses the 2A03's stable unofficial opcodes (LAX, SAX, DCP, SLO and
the like), so a flash cartridge or an emulator has to run those, as any
for the hack itself does.

## How the netplay works

As in every netplay game (nesp32's
[`docs/MULTIPLAYER.md`](../../docs/MULTIPLAYER.md)): both consoles run the
whole game, only the buttons cross, a byte a tick, and a console takes a
tick only when it has both players' buttons for it. All of the game runs
in its NMI, as Contra's and TMNT II's do, so the netplay is TMNT II's
(`net/net.asm`), in bank 1.

**The NMI.** It turns the IRQs on at once, and sets the VRC6's counter for
the split under the status bar, some 5930 cycles on. Then it sends the
sprites and the buffer of writes to the PPU, brings in bank 0, runs the
sound engine and reads the controllers, steps its timers and its random
number, and runs the game. The netplay changes five things in the hack:

- **The NMI's drawing** (`HOOK_NMI_DRAW`, 3 bytes): a call to
  `net_nmi_draw`, which draws as the hack does but in an NMI after one
  that stalled ("A stall", below).
- **The NMI's sound and controllers** (`HOOK_NMI_PADS`, 9 bytes): a call to
  `net_nmi_pads`. With no session it is the hack's own sound and read,
  with OUT0 put back to mark after it. In a session it is the exchange,
  with the IRQs held off; then in a tick the sound engine, and both
  players' buttons for the tick given to the game's own code that works
  out what is held and what is newly pressed (`GAME_PADS_USE`), as if it
  had read them; in a stall, the end of the NMI.
- **The NMI vector**: `net_nmi`, which is the menu's NMI while the menu has
  the console, and the game's otherwise.
- **The reset's last call** (`HOOK_RESET`): `net_reset` first, which turns
  the link's line to mark and starts a session if one was asked for.
- **The title's look at what was pressed** (`HOOK_TITLE_PAD`): Start with
  2 PLAYERS GAME chosen is the menu's. In a session the title is for two,
  and Start is taken as pressed at the first one, so the players go
  straight from the menu into 1-1.

**A stall** ends the NMI after the PPU's writes, with the scroll set as the
game's NMI sets it for a frame with no split: no sound, no timers, no
random number and no game. The NMIs after it send the same sprites and
draw nothing, so the picture stands, and try again. The split still
comes, from the counter the NMI set.

They draw nothing because a tick's game can fill two buffers of writes:
the one it picks for the next NMI (`DRAW_NEXT`), and its own at $0301,
which the NMI picks for the one after. With no stall the game's own is
drawn after the next tick, which adds to it first. A stall's second NMI
would draw it a tick early and empty it, and the next tick's game would
add to it on one console and begin it again on the other: the two
consoles' memory differed there, which the simulation found with replies
lost on the line. So `net_nmi_draw` passes over the drawing, and the
emptying with it, in any NMI after one that stalled, and the tick finds
both buffers as it would have with no stall between. It puts back the
three bytes of scratch the last drawing left ($00-$02, where it came to in
the buffer), which the NMI had set again for a drawing it then did not
do.

**A lag**, an NMI that comes while the last one's game is still at work,
is the game's own: it sets the scroll and steps a byte of its own
(`LAG_COUNT`, in the PPU's buffer), and nothing else. That byte differs
between the consoles, but the game only ever sends it to the PPU.

**The netplay's memory** is the PRG RAM. The link's serial routines count
cycles by six bytes of zero page, and the game has none to spare, so they
are lent: `net_call`, the fixed bank's way into bank 1, keeps the game's
six bytes ($50-$55) while bank 1 runs, and puts them back.

## The sound

The sound engine runs once a tick in a session, and not in a stall. That is
unlike the other netplay games, whose music keeps the frames' time: here
the game reads back one byte of the engine's, whether the music of an
event is still playing ($07B1), and at the end of a level it waits for
that music to end before it goes on. Had the engine run in every NMI, a
console that stalled during that music would hear it end at another tick
than the other console, and the games would differ. So the music holds
back a frame in each stall, which on a network the delay covers is next to
never. The engine's memory is then the game's, and is in the digest and in
what the tests compare.

## The frame

**Where the exchange goes.** In all 32 levels, some 1000 frames of play
for two in each, the NMI came to the controllers' read at cycle 673 as a
median and 1393 at the latest (in 2-1; 1290 in every other level: the
PPU's buffer is what varies), and the split's IRQ is raised at about 5930.
An exchange of some 3100 cycles from there is over by 4700 at the latest,
1200 cycles before the split, which the IRQs held off for it never make
late.

Two exchanges are longer:

- the one in 128 that carries the console's report, whose reply has the
  delay advised as well: some 4340 cycles, over by some 5730 at the very
  latest, which is still before the split, but by 200 cycles where the
  rest leave 1200. On hardware it is the first thing to look at if the
  foot of the status bar is ever seen to jump;
- one whose reply has to be asked for again, misheard or late: that
  frame's split comes late. The digest, once in 256 ticks, is taken with
  the IRQs let in, so it never holds the split back.

**What it costs.** The frames of play took 12000 to 18000 cycles of the
frame's 29780 as a median, by level, with no exchange. The busiest took
28214 (in 3-4), and a few in three levels (3-2, 3-4 and 4-1) take more
than 26680, which the exchange's 3100 make overrun: the game
stands still a frame for them in a session, on both consoles. In 1-1 the
busiest frame was 20312, and none overruns. The hack's own frames that
overrun on one console do so in a session too.

## The simulation

The levels were reached for the measurements by setting the world ($E4)
and the level ($075C) at the title, before its Start.

`tests/console.py` is TMNT II's console on py65 with the hack's cartridge:
the VRC6's PRG banks and PRG RAM, and its IRQ counter in its scanline mode,
which counts CPU cycles; `tests/mpu6502x.py` adds the unofficial opcodes,
with a real 2A03's cycles, and raises on any other. The PPU's pattern
tables are the CHR ROM, read through PPUDATA's buffer, as the game draws
its title from there.

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
make test
```

- `test_console.py`: the netplay ROM is the hack but for its hooks; a game
  for one is the hack's, byte for byte, every frame; the exchange is over
  well before the split.
- `test_lockstep.py`: two consoles play one game on every network the
  other games are tried on, the split stays on its line, and the sound
  engine runs once a tick.
- `test_menu.py`: the menu, by room code and by address, and LOCAL GAME.

## Memory the game uses

| | |
|---|---|
| `OPER_MODE` ($E2) | 0 the title, 1 a game, then 3 and 2 at its end; the task after it |
| `PAD_HELD` ($E0), `PAD_PRESSED` ($06F6) | each two bytes, player 1's and player 2's |
| `TWO_PLAYERS` ($076F) | the title's choice |
| `LIVES` ($075B) | the two players', shared; $FF is the game over |
| `SPLIT_WANTED` ($0722) | 0 where the NMI sets the scroll itself |
| $F0-$FF, $07B0-$07CA | the sound engine's, with the game's orders to it at $FA-$FF |

## To do

1. **Hardware.** A session on two real consoles, by room code; and the
   split, on a flash cartridge's VRC6, through a report's exchange.
2. **The end of a level, in a session**, in the simulation: the flagpole
   and the castle's music, which the game waits on, with stalls among it.
   The tests play 1-1 at random and never reach it.
3. **The nesp32's name for it.** Its screen shows the hello's id, `SMBX`,
   where it has a name for the other games; that is a line in the
   firmware's list, for when it is next built.
