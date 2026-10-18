# Tetris, two consoles

A netplay build of Tetris (NES): a two-player game, side by side, split
over two consoles, each with a nesp32 on controller port 2, the nesp32s
joined over Wi-Fi. The nesp32 is an M5Stack Stick with
[nesp32](../..)'s firmware, the one firmware for every ROM that uses one;
this ROM asks it for its PEER service, as Dr. Mario's and Contra's do.

**Status: works on two simulated consoles, not yet tried on hardware.**
With nesp32's own link and services between them, the menu hosts and
joins, and a game plays at full speed, the same on both screens throughout
(`make test`).

The original game has no game for two. Its code has one that was never
finished and never offered: a second player's state, a second playfield,
garbage sent across for a double or more. This ROM finishes it, as TAUS's
twoplayer mod does, and plays it over the network the way
[Dr. Mario](../drmario) does: both consoles run the whole game, and only
the buttons cross.

The title has **1 PLAYER** and **2 PLAYERS** where the original says PUSH
START: Up, Down or Select to choose, and Start. 1 PLAYER is the original's
game for one, as it always was. For 2 PLAYERS the console asks how:

- **HOST GAME**: the nesp32 waits for the other one. The console and the
  nesp32's screen both show the address player 2 has to enter.
- **JOIN GAME**: edit the address (Left/Right to move, Up/Down to change a
  digit) and press Start. It starts as the address last joined, or this
  nesp32's own.
- **LOCAL GAME**: the game for two on this console, with a controller in
  each port.

B goes back to the title.

In a game for two, player 1 chooses the music and then a level, then player
2 chooses a level. Both playfields are on each screen, player 1's on the
left. Each player gets the same pieces in the same order. A double sends a
row of garbage to the other player, a triple two and a Tetris four. The game
ends when either player's curtain is down; Start, from either player, goes
back to the level menu for another. Start pauses for both, and Select hides
a player's own next piece.

**The game is not in this repository.** What is here is the netplay code,
the code that finishes the game for two, the tests, and a few lines to be
put into the game's own code. The rest, the game's code and its graphics,
is [TetrisNESDisasm](https://github.com/CelestialAmber/TetrisNESDisasm),
CelestialAmber's disassembly, a submodule at `third_party/TetrisNESDisasm`.

```sh
git submodule update --init third_party/TetrisNESDisasm
make            # build/tetris.nes (the original) and build/tetris_net.nes
make verify     # the original still matches its SHA-1
make test       # needs: python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

Needs cc65 (`ca65`, `ld65`), Python 3, `patch`, and for the netplay ROM
[nesp32](../..), the top of this repository (or `NESP32=` where it is), and a C
compiler: the link's library for the console comes from there, and the
tests build its firmware's link and services for this computer. The
disassembly's own build wants Pillow for its graphics; this one turns them
into CHR with `tools/png2chr.py`, which needs nothing.

## What is where

| Path | Purpose |
|---|---|
| `patches/main.patch` | the lines that call the netplay code and the game for two, for the disassembly's `main.asm`. All are under `.ifdef NETPLAY` |
| `net/twoplayer.inc` | the game for two: its screen, its pieces, its menus and its end |
| `net/twoplayer_game.nam`, `net/twoplayer.chr` | its screen, and the few tiles of it that the game's tileset has not (TAUS's) |
| `net/net.inc` | the game's bank: ticks, stalls and lags, starting a session, and the way to the menu's bank |
| `net/session.inc` | a session's frame, in the menu's bank: the buttons' rings, the delay, the exchange and the check |
| `net/menu.s` | the menu, in a second PRG bank of its own: the hello, and PEER's lobby |
| `net/common.inc`, `net/ram.inc` | a session's numbers, the code both banks share, and the memory they share |
| `net/game.cfg`, `net/menu.cfg` | where each bank's code goes, and the link library's memory |
| `tools/png2chr.py` | the disassembly's tilesets as CHR, with no Pillow |
| `tools/chr_tiles.py` | the game for two's tiles, into the netplay ROM's CHR |
| `tests/console.py`, `tests/wire.py`, `tests/netplay.py` | a console on py65, the serial line, and two consoles with their nesp32s and a network between |
| `docs/PROTOCOL.md` | how the two games are kept the same, and what the ROM asks of PEER |

The link itself is nesp32's: its `docs/PROTOCOL.md` has the line, the
frames and the PEER service, `nes/lib/nesp.inc` there is the library the
menu's bank includes, and `firmware/` there is what runs on the nesp32.
The firmware needs nothing new for this ROM: PEER pairs two nesp32s whose
consoles said the same name in their hello, `TTRS` here.

## Changing the game's code

Edit the copy in `build/upstream`, then `make patches`. nesp32's
[`docs/DEVELOPMENT.md`](../../docs/DEVELOPMENT.md), "Changing a borrowed
program's code", has how the patches are kept.

## Where the netplay code sits

The game fills its 32 KB, so the netplay ROM has a second 32 KB PRG bank,
on the same mapper (MMC1), as Dr. Mario's does (docs/PROTOCOL.md, "The
cartridge"). The menu is there, and so is a session's frame with the
link's library and its table: the game's NMI goes to that bank and back
once a frame. What is in the game's bank is in the space the original
leaves to unused data: the two-player screen, 1 KB of it whole, where
`unreferenced_data1` was, and the game for two's code with the way to the
menu's bank where `unreferenced_data4` was. 323 bytes are left in the one
and 135 in the other. It needs a flashcart or an emulator.

## The nesp32

The hat is nesp32's ([`docs/WIRING.md`](../../docs/WIRING.md) there), as
for every ROM that uses a nesp32. Flash nesp32's firmware
(`firmware/README.md` there) and join a Wi-Fi network from the controller
with its setup ROM, once. Nothing is set up from a computer, and nothing is
chosen on the nesp32: this ROM says what it is when its menu opens.

The nesp32s talk over UDP port 6502. On one network that needs nothing
more. Across the Internet the hosting side has to forward that port to its
nesp32, and player 2 enters the host's public address.

## What has been learned

From the simulation:

- **The game's NMI is most of the game's timing.** It draws a playfield
  four rows a frame, steps the line-clearing animation, counts the frames
  and steps the generator of random numbers, and the pieces wait for the
  rows to be drawn. So, as in Dr. Mario, an NMI that finds the main loop
  still at work does nothing at all in a session, and the game depends
  only on how many ticks there have been.
- **The game reads its controllers last in its NMI**, after all its writes
  to the PPU. The exchange is made there, and an NMI that has no buttons
  for its tick ends there, to be taken up from there in the next frame.
- **Two playfields fit in the vblank** only with their rows copied four at
  a time, as TAUS found: the NMI's last write to the PPU is about 1630
  cycles in, of the vblank's 2273.
- **A session has to start with nothing left of the menu's NMIs.** The flag
  that tells a waiting main loop from a busy one was left set by the title,
  and the first NMI of a session, before the game had started again, was
  taken for a tick. Dr. Mario cleared it with the page it keeps its
  options in.
- **The high scores are on the level menu**, and drawing them leaves a
  digit in the zero page. A session starts both consoles with the high
  scores of one never played, or the check between the two would find
  them different.
- **The game resets the mapper at the start of its menus.** That puts the
  last 16 KB at C000, which in the netplay ROM is the menu's bank, until
  the next write; the netplay ROM does not, and its mapper is never left
  half written when an NMI comes.

## To do

What is left on the nesp32 itself is in nesp32's
[`docs/TODO.md`](../../docs/TODO.md).

- **Play it on hardware**, two consoles on one network, and take the
  figures Dr. Mario's README has.
- **Say who won.** The game ends with both curtains down and no word of it.
- **B-type for two.** Its goal, its heights and its endings are left out.
- **The game's own sound effects for garbage**, and a mark of it coming;
  it arrives when the player's piece is down, with nothing to say so.
- **Say why on the console** when a session ends (the other console left,
  the nesp32 went quiet, the games differed); it only goes back to the
  title now.

## Known limits

- Both consoles must run this build: the nesp32s tell another game, or an
  older build of this one, from it, and will not join the two.
- The input delay is 1 to 5 frames, each console's own, as its nesp32
  advises. A network slower than 5 frames covers slows the game rather
  than breaks it.
- A button press shorter than a stall is not seen.
- In a stall the picture stands still, and a sound the game asks for is
  heard when it asks, which is a tick's time and not a frame's.
- A session clears the console's high scores, for the reason above.
- No high scores are kept from a game for two.

## Credits

The game for two follows TAUS's twoplayer mod
([ejona86/taus](https://github.com/ejona86/taus), copyright 2019 Eric
Anderson, MIT License): its screen and tiles are TAUS's files, and its
copying of rows, its pieces, its garbage and its menu for player 2 are
TAUS's code, rewritten for this disassembly. Tetris is its publishers', and
no ROM of it is here.
