# River City Ransom, two consoles

A netplay build of River City Ransom (US, NES): a two-player game on two
consoles, each with a [nesp32](../..) on controller port 2, meeting by a
room's code as [Jackal](../jackal) and the other netplay games do. nesp32's
[`docs/MULTIPLAYER.md`](../../docs/MULTIPLAYER.md) has what the netplay
games share.

The session and its menu are done and tested in the simulation: Start at
the first screen with 2P PLAY chosen is the menu, HOST GAME and JOIN GAME
meet by a room's code or by an address, and the two consoles play one
game, kept the same by their buttons, with the session's line at 10
cycles a bit. It has not been played on hardware yet.

The netplay ROM is on the game's own cartridge, an MMC3 (mapper 4), with
8 KB of PRG RAM and twice the PRG ROM ("The cartridge", below). A flash
cartridge or an emulator has to take that.

**The game is not in this repository,** and there is no disassembly of it
to start from. The build makes one, as Bubble Bobble's does:

- `baserom.nes`, a copy of the game, which whoever builds puts in this
  directory (or says where it is with `BASEROM=`). It is the US release:
  `make verify` checks what is built against its SHA-512.
- `tools/game.map`, the names and comments, and `tools/entries.txt`, where
  the game was seen to run on the simulated console (`make trace` writes
  it again, in some eight minutes). Neither holds any of the game's bytes:
  only addresses.

`tools/convert.py` makes ca65 source of the ROM in `build/gen`. Every byte
is the ROM's. What is code is found by following it from where the game
was seen to run, which comes first, and from the vectors; the rest is
data. Each label asserts its address, which ld65 checks: a change that
moves any of the game does not link. Each run of 32 bytes or more of $00
or $FF that is not code is a label of its own, `FREE_b_oooo`, which a
netplay build can fill with a macro.

The source is copied to `build/src`, and `patches/` puts the netplay's
few lines into the copy, all under `.ifdef NETPLAY` and each the same
length as the line it replaces: none of the game moves. The original is
built from the patched source too, and `make verify` says it is still the
ROM.

```sh
make            # build/rcr.nes, the original, and build/rcr_net.nes
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

`dist/rcr_net.bps` is the netplay ROM as a patch to the US release: apply
it to your own copy of the game with any BPS patcher (Floating IPS, or
RomPatcher.js in a browser), and put the ROM it makes on a flash
cartridge. A BPS patch knows the ROM it is for, and a patcher refuses any
other. The patch holds none of the game: what it has of the game, it
copies from the player's own ROM. `tests/test_patch.py` holds the patch in
`dist/` to the ROM this tree builds: after a change to the netplay, `make
bps` writes it again.

## The cartridge

An MMC3 with 128 KB of PRG ROM and 128 KB of CHR ROM. The game only ever
switches the PRG 16 KB at a time, R6 and R7 to the two 8 KB banks of one
pair (`BANK_PAIR`, $FED1), and keeps the last 16 KB fixed at $C000, as the
MMC3 does: so the converter has it as eight banks of 16 KB, the last one
fixed. It has no PRG RAM, and never touches $6000-$7FFF. The MMC3's
scanline counter splits the screen twice a frame: an IRQ on line 29 under
the HUD, which also runs the sound engine, and one above the text at the
foot.

The netplay ROM is the same board with 8 KB of PRG RAM and 256 KB of PRG
ROM, which its NES 2.0 header asks for. The game's banks 0 to 6 are where
they were, and its fixed bank is the last in the file, where the MMC3 keeps
it; banks 8 and 9, between, are the netplay's (`net/rcr_net.cfg`). The game
never picks a bank above 6 (`tests/test_console.py`).

## How the game runs

The game's logic is its main loop (`MAIN_LOOP`, $F27D), which waits for
two NMIs at the end of each pass (`MAIN_WAIT`): it plays at 30 passes a
second, or 20 when a pass runs into a third frame, which in a busy fight
is often. The NMI ($F168 for the game) sends the sprites, writes the
queue of writes to the PPU the main loop leaves it, sets the scroll and
sets up the IRQs. The main loop reads the controllers once a pass, at its
top (`READ_PADS`, $FD1D).

The screens before the game, Slick's letter and the pause's screens are
loops of their own, which wait for a frame with the NMI off but for a
moment (the game's wait for one, $FC60), and read the controllers once a
frame. The first screen's NMI ($F12B) reads them itself.

**The game is the same whatever its frames do.** A pass's work does not
depend on how many frames it took, nor on where in it an NMI or an IRQ
came: the original, played with the same buttons pass by pass on Mesen and
with 3100 cycles added to each pass's NMI, had the same game for 8000
passes, though one in three of its passes ran into a third frame and two
in three of the other's did. What differed was what keeps the frames'
time: the queue of writes to the PPU and its ends, where the HUD's redraw
had got to ($0517), the most NMIs a pass took ($06D3), and the sound
engine's memory ($0700 on).

## How the netplay works

As in every netplay game (nesp32's
[`docs/MULTIPLAYER.md`](../../docs/MULTIPLAYER.md)): both consoles run the
whole game, only the buttons cross, a byte a tick, and a console takes a
tick only when it has both players' buttons for it.

**A tick is a read of the controllers.** Every read goes through
`READ_PADS`, and in a session each one takes the next tick's buttons, or
waits for them: a pass of the main loop in play, a frame on the other
screens. The game being the same whatever its frames do, nothing else has
to be done to keep the two consoles alike: a console that waits for the
other's buttons goes on drawing the same picture, and the music goes on.

**Where the exchange is made** (`net/net.inc`):

- **In play**, the game's NMI makes it, once it has written to the PPU and
  set up the IRQs (`net_nmi_count`, in place of its count of the NMIs):
  for the next tick, which the next pass's read takes. So there is one
  exchange a pass, in the frame after the read, and the other console's
  buttons have a frame or two to come before they are wanted.
- **On the screens that read with the NMI off**, the read makes it itself,
  with the IRQ held off, after the frame's writes to the PPU; with no
  buttons yet it waits for the next vblank and makes it again.
- **On the first screen and the title**, whose NMI reads the controllers,
  that read gives no buttons in a session, and the session passes the
  first screen with 2P PLAY chosen. It makes the exchange all the same,
  which keeps the session's line busy through screens that read nothing
  for seconds.

Nothing breaks into an exchange: in an NMI the IRQ waits, and in the main
thread the NMI is off and the IRQ held off. The HUD's IRQ comes some 5770
cycles after the NMI begins, and the NMI with an exchange takes some 4000
at the most but for an exchange asked again: in 1500 frames of play, one
IRQ came 3 lines late.

**What had to change in the game**, by `patches/`:

- **The reset** (`net_cart_start`, `net/cart.inc`, in the fixed bank's
  empty bytes at $F9B3): the MMC3 set up, the PRG RAM on, the netplay's
  code copied into it from bank 8, and the console's RAM cleared, all of it.
  The game's own reset clears $0200-$07FF only, and reads memory it has
  not written (at $F253, an index from $0102): two consoles that begin a
  session have to begin alike.
- **The controllers' read** (`net_read_pads`): with no session, the game's
  read and OUT0 back to mark after it (the game leaves it low, which the
  nesp32 would take for the start of a byte); in a session, the tick.
- **The NMI's count of NMIs** (`net_nmi_count`): the count, and the
  session's exchange in play.
- **The first screen's wait for its NMI** (`net_select_wait`): in a
  session, 2P PLAY chosen and Start.
- **The first screen's Start** (`net_select_start`): with 2P PLAY and no
  session, the menu has the NMI until LOCAL GAME, and the game goes on
  from there as it would have.
- **The vectors**: the reset's, and the NMI's (`net_nmi`), which is the
  menu's while the menu is up, and counts the frames a session's line has
  been quiet.

**The session's line** is at 10 cycles a bit (`NET_RATE`, the Makefile),
received by folding (nesp32's `nes/lib/gen_link.py`): the game plays no
samples, whose fetches are what made 10 too fast for Jackal. The nesp32
puts its line back at the link's rate with no frame on it for half a
second, and the game has screens with no read for longer (the logo after
the session's first tick, the screens between the choices): a try that
finds no reply heard for 36 frames (`net_quiet`, counted in every NMI)
puts this console's line back too, and asks for 10 again, before any
exchange is missed for it.

**The menu** is Jackal's (`net/menu.inc`), in bank 9, its memory in the
PRG RAM. Its letters are the first screen's, white on black in its own
palette; its cursor is the font's arrow, as a sprite, from the font's CHR
bank put at $1000 for it (R2), which the game sets again on LOCAL GAME
(`SET_SPRITE_CHR`).

**The netplay's memory** is the PRG RAM: its code at $6000-$77FF, copied
there at the reset, its own and the menu's at $7800-$7AFF, and the order
that starts a session at $7F00. The link's serial routines need six bytes
of zero page: $15-$17, $F3, $F9 and $FA, which no instruction of the game
names and the game was never seen to touch (`tests/test_console.py`).

**What keeps the frames' time**, and is left out of the digest and of
what the tests compare (`tests/console.py`, `UNKEPT`): the scratch and the
HUD's split at $00-$14, the link's zero page, the PPU's and the banks'
shadows ($F7-$FF), the stack, the queue of writes to the PPU, the HUD's
redraw, the most NMIs a pass took, and the sound engine's memory. The
digest is of the zero page the game keeps and of $0300-$04FF.

## The frame rate

A session's exchange is some 3000 cycles, made once a pass of two frames
or three. In the simulation, two players at random, 3000 frames:

| Passes a second | alone | in a session |
|---|---|---|
| Fighting at random, three runs | 21.3 | 20.9 |
| Walking right | 23.7 | 22.2 |

A busy fight's passes take three frames already, and the exchange seldom
makes one take a fourth; the slowdown is where the passes nearly fit in
two. The game's own work is where the cycles are, and the place to win
them back: the sorting and drawing of the objects (`DRAW_OBJECTS`, $EFD4)
and the objects' logic in bank 6.

## The simulation

`tests/console.py` is Bubble Bobble's console on py65 with the MMC3 of
Jackal's, and the MMC3's scanline counter and IRQ. `tests/drive.py` plays
from the power on to a game for two. `tests/netplay.py` is two of them,
each with nesp32's firmware built for this computer, and a network between.

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
make test
```

## To do

1. **Hardware**: a session on two consoles, the menu, the line at 10, and
   the HUD's split while a reply is asked again.
2. **Faster ways** through the game's busiest routines, for the slowdown
   ("The frame rate").
3. **More of the game in a session**: the shops, the bosses, Slick and the
   ending, a password entered, and both players knocked out.
4. **The release**: the patch in nesp32's `tools/gen_web.py` and the home
   page's downloads.
