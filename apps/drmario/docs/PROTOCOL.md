# Dr. Mario netplay: how two games are kept the same

How two consoles play one two-player game, each with a nesp32 on controller
port 2 and the nesp32s joined over a network.

The link, the firmware and the frames are nesp32's
([the top of this repository](../../..)), and
its [`docs/PROTOCOL.md`](../../../docs/PROTOCOL.md) has them: the line,
the hello, and the PEER service this ROM asks for, with its lobby, its
exchange of buttons and what the two nesp32s say to each other.

What the three netplay games share (what a tick, a stall and a lag are,
the exchange, the delay, the check, the menu and how a session ends) is in
nesp32's [`docs/MULTIPLAYER.md`](../../../docs/MULTIPLAYER.md), and is not
said again here. This is what is Dr. Mario's own.

Status: implemented by `net/*.inc` and `net/menu.s`, and tested on two
simulated consoles with nesp32's own link and services between them
(`tests/`). On hardware a game has been played with it between two
consoles on one home network, at a delay of 1 tick and with no reply
misheard. The README has the figures.

## The tick

The game's handler writes to the PPU, counts the frame, and then reads the
controllers; its main loop does the rest of the frame's work after it. The
exchange is made at that read. The handler also draws a row of a bottle
and counts it off, and always runs, whether or not the main loop has
finished the frame, which is why a lag runs nothing of the game. The
console keeps 8 ticks of buttons each way.

## The music

In a session the sound engine runs from the NMI, once in every frame
(nesp32's `docs/MULTIPLAYER.md`, "The music"). Its memory is `$00E0` to
`$00EF` and `$067E` to `$06FF`, and the game only leaves it orders there:
a sound to make, the music to play. One thing comes back: the engine
counts the music's beat, and the viruses in the one-player game's
magnifier dance to it. A session is a two-player game and has no
magnifier. So the two consoles' sound engines are not at the same place at
the same tick, and nothing of the game can tell; the tests leave the
engine's memory out of what they compare, and hold the rest to be equal.

## The menu

On the title, **2 PLAYER GAME** goes to the menu, in the second bank, which
says the hello as `DRMA`. A session begins at the options of a two-player
game.

## The cartridge

The game fills its 32 KB, so the netplay ROM has 64 KB of PRG on the same
mapper (MMC1): the game in the first 32 KB, and in the second the menu and
a session's frame, with the link's library. The banks are switched whole.
The code that runs while the bank changes under it, the start of the reset
code and `net_far`, is the same bytes at the same addresses in both banks.
The menu has its own NMI handler. A flashcart or an emulator runs it; it
does not fit the original board.

In a session the game's NMI goes to the second bank for the frame's
exchange and comes back, at the point where the game reads its
controllers. It does so only in an NMI that found the main loop waiting,
so the mapper is never written in the middle of the game's own writes to
it.

In the game's bank the session's code takes space the game does not use,
the padding before `$FD00`. The two pages at `$FD00` are the samples of
the music's drums. They were left out, in the belief that the game never
plays a sample, which is wrong (nesp32's [`docs/PHANTOM-RIGHT.md`](../../../docs/PHANTOM-RIGHT.md)); the
music still plays them, so the netplay ROM's drums are not the
original's.

The library's memory is 16 bytes of zero page at `$00B0` and its two
buffers at `$0330`, the session's is at `$0742`, and the menu's at `$03B0`:
all of it where the game keeps nothing.

## Timing

Measured on the simulated consoles (`tests/test_lockstep.py`, and runs
like its own):

- An exchange is 5 or 6 bytes out, 210 cycles each, the nesp32's
  turnaround, and 4 bytes back, 231 cycles each, with the CRC of each
  worked out from a table. With the controller's read and the way to the
  menu's bank and back it is about 3500 cycles with a nesp32 that answers
  in 0.2 ms, and a tick's NMI about 6300 of a frame's 29780. As PEER's
  ordinary frames, 9 to 11 bytes out and 10 to 12 back, the NMI was about
  8500. The busiest frame of a game still ends before the next NMI, at
  about 27400. (On hardware the firmware has answered other ROMs in about
  0.07 ms, and in 0.5 at the slowest.)
- A reply that has not begun 4.1 ms after the request is not heard at all.
- With the delay at 1, no frame waits for buttons on a network that takes
  5 or 7 ms to cross, wherever the one console's frames fall in the
  other's. From 8 ms the nesp32s advise 2, which covers 20 ms; at 35 ms
  they advise 3. On a network of 150 ms or more both consoles go to 5, and
  the game still waits.
