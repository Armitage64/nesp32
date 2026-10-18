# Tetris netplay: how two games are kept the same

How two consoles play one game of Tetris for two, each with a nesp32 on
controller port 2 and the nesp32s joined over a network.

The link, the firmware and the frames are nesp32's
([the top of this repository](../../..)), and its
[`docs/PROTOCOL.md`](../../../docs/PROTOCOL.md) has them: the line, the
hello, and the PEER service this ROM asks for, with its lobby, its exchange
of buttons and what the two nesp32s say to each other. This is the game's
side: what a tick is, and what the ROM does with what PEER gives it.

It is [Dr. Mario's](../../drmario/docs/PROTOCOL.md), nearly line for line:
the same board, the same kind of NMI, and the same code for a session's
frame and the menu. What differs is said here; the rest is said there too.

Status: implemented by `net/*.inc` and `net/menu.s`, and tested on two
simulated consoles with nesp32's own link and services between them
(`tests/`). Not yet on hardware.

## The game for two

The original offers a game for one only. Its code has one for two, never
finished: the state of the active player at $40, player 1's copy at $60
and player 2's at $80, a playfield each at $0400 and $0500, the two players
taken in turn every frame, and garbage passed between them. The netplay
ROM finishes it (`net/twoplayer.inc`, after TAUS's twoplayer mod) and
offers it, from LOCAL GAME and in every session. It is A-type only.

Each player's pieces come from a generator of their own, kept in the 32
bytes of their state that the game leaves unused (at $5C, as the game's own
at $17 is laid out). Both are begun from the game's at the start of a game,
so both players get the same pieces in the same order, however far apart
they are. The game's own generator goes on stepping once a tick, and the
garbage's hole comes from it.

## The idea

Both consoles run the whole game. Only buttons cross the link: one byte for
each *tick*, a tick being one NMI that the game takes. A console takes a
tick only when it holds both players' buttons for it, so both games see the
same buttons at the same tick and stay the same game.

A console's own buttons are used some ticks after the frame they were read
in, its *input delay*. That is the time they have to reach the other
console. Nobody sets it: each console keeps its own, from 1 tick to 5, and
changes it as the game goes (Dr. Mario's "The delay").

An NMI in a session is one of three things:

| | When | What runs |
|---|---|---|
| a tick | the main loop was waiting, and the buttons are here | the game's whole handler, with the exchange where the game reads its controllers |
| a stall | the main loop was waiting, but the other console's buttons are not here | the handler as far as the controllers, and the exchange. The NMIs that follow make the exchange again and write nothing to the PPU, whose picture stands; the one that has the buttons goes on from there |
| a lag | the main loop was still at work | nothing of the game |

So the game's memory depends on how many ticks there have been and on
nothing else. In Tetris that matters more than in most games. The NMI
draws each playfield four rows a frame, and the pieces wait for the rows
to be drawn; it steps the line-clearing animation and the game over's
curtain, counts the frames, and steps the generator of random numbers.

The game's handler writes to the PPU, does all that, and reads the
controllers last. The exchange is made at that read, so the buttons leave
as soon as they are read and the other console's are asked for at the last
moment they can be used.

The main loop waits for the NMI in two routines, which every wait in the
game goes through. The netplay ROM puts `net_wait_nmi` in both, which says
the main loop is waiting.

## The music

As in Dr. Mario: in a session the sound engine runs once in every frame
from the NMI, whichever of the three the frame is, and not once a pass of
the main loop. Its memory is `$00E0` to `$00EF` and `$0680` to `$06FF`, and
the game only leaves it orders there; nothing of the game reads it back. So
the two consoles' sound engines are not at the same place at the same tick,
and nothing of the game can tell. The tests leave the engine's memory out
of what they compare.

## The menu

As Dr. Mario's, with **Select** on the title in place of 2 PLAYER GAME,
and the hello as `TTRS`, version 1. LOCAL GAME goes back to the game, to
its game type menu for two.

When the nesp32 says it is connected, as player 1 or as player 2, the
console leaves the menu and starts a session: both consoles begin again
from the state of one just switched on, and go straight to the game type
menu of a game for two, past the legal screen and the title. They begin
with the high scores of one never played: the level menu draws the high
scores, and leaves a digit of one in the zero page, which the check below
would find different.

In a session the game type menu's B, which would go back to the title, does
nothing, and nor does A+B+Select+Start in a game.

## A session

Every NMI that is not a lag makes one exchange, PEER's TICKS as a short
frame, as Dr. Mario's does: five bytes out, or six, and four back. A tick's
byte is the controller as it was read; the game's own code makes the
buttons newly pressed and held from it, for both players.

### Checking that they stay alike

One tick in 256 carries no buttons. In their place each console sends a
digest of its game: of its zero page, less the link's bytes, the sound
engine's, the flag the main loop waits on and the session's one byte
there, and of both playfields, taken at the start of the same tick on both,
eight ticks before. A console whose digest differs from the other's gives
the session up and goes back to the title, as does the other.

## The cartridge

The game fills its 32 KB, so the netplay ROM has 64 KB of PRG on the same
mapper (MMC1): the game in the first 32 KB, and in the second the menu and
a session's frame, with the link's library. The banks are switched whole.
The code that runs while the bank changes under it, the start of the reset
code and `net_far`, is the same bytes at the same addresses in both banks,
from `$FF00`. The menu has its own NMI handler.

The game resets the mapper as each of its menus begins, and once more for
the high scores, which puts the last 16 KB at `$C000` until the next write
to the mapper's control. In the netplay ROM the last 16 KB are the menu's,
and an NMI in between would run the menu's handler, so the netplay ROM
does not reset it there. Its writes to the mapper are never left half done
when an NMI comes: the NMI changes the bank only when it finds the main
loop waiting.

In the game's bank the netplay code is where the original keeps unused
data: the two-player screen in `unreferenced_data1`, and the code in
`unreferenced_data4`. The netplay ROM's CHR is the original's with six
tiles of the game's tileset, which the game does not use, made the joins of
the two-player screen's frames.

The memory:

| | Where |
|---|---|
| the link's library | 16 bytes of zero page at `$0020`, and its two buffers at `$0330` |
| the menu | `$0380` to `$03C3` |
| a session | `$0760` to `$0781`, and the way between the banks at `$0790` |
| a session's scratch byte | `$0006` |
| player 1's and 2's generators | `$7C` and `$9C`, in their state, with the garbage's rows to go at `$7B` and `$9B` |

All of it is where the game keeps nothing. The game's reset clears
`$0000` to `$06FF` and keeps the high scores, up to `$0754`; the session's
own numbers are past them.

## Ending

The console leaves a session, and starts again from its title as if reset,
when a reply says the other console is gone or the nesp32 knows of no
session (it was switched off and on), when the two games' digests differ,
or after 240 NMIs in a row that were not ticks (4 seconds).

## Timing

Measured on the simulated consoles (`tests/`):

- The NMI's last write to the PPU in a game for two, with four rows of
  each playfield, is about 1630 cycles after the vblank begins, of its
  2273. The game's own copy of a row, eight of them, would not have fit;
  four at a time does (TAUS's figure for it: 559 cycles for four rows).
- The exchange is Dr. Mario's: about 3500 cycles with a nesp32 that
  answers in 0.2 ms, after the game's writes to the PPU.
