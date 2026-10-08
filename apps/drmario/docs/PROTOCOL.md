# Dr. Mario netplay: how two games are kept the same

How two consoles play one two-player game, each with a nesp32 on controller
port 2 and the nesp32s joined over a network.

The link, the firmware and the frames are nesp32's
([`../nesp32`](../../nesp32), a checkout of which sits beside this one), and
its [`docs/PROTOCOL.md`](../../nesp32/docs/PROTOCOL.md) has them: the line,
the hello, and the PEER service this ROM asks for, with its lobby, its
exchange of buttons and what the two nesp32s say to each other. This is the
game's side: what a tick is, and what the ROM does with what PEER gives it.

Status: implemented by `net/*.inc` and `net/menu.s`, and tested on two
simulated consoles with nesp32's own link and services between them
(`tests/`). On hardware a game has been played with it between two
consoles on one home network, at a delay of 1 tick and with no reply
misheard. The README has the figures.

## The idea

Both consoles run the whole game. Only buttons cross the link: one byte for
each *tick*, a tick being one NMI that the game takes. A console takes a
tick only when it holds both players' buttons for it, so both games see the
same buttons at the same tick and stay the same game.

A console's own buttons are used some ticks after the frame they were read
in, its *input delay*. That is the time they have to reach the other
console. Nobody sets it: each console keeps its own, from 1 tick to 5, and
changes it as the game goes (below).

An NMI in a session is one of three things:

| | When | What runs |
|---|---|---|
| a tick | the main loop was waiting, and the buttons are here | the game's whole handler, with the exchange where the game reads its controllers |
| a stall | the main loop was waiting, but the other console's buttons are not here | the handler as far as the controllers, and the exchange. The NMIs that follow make the exchange again and write nothing to the PPU, whose picture stands; the one that has the buttons goes on from there |
| a lag | the main loop was still at work | nothing of the game |

So the game's memory depends on how many ticks there have been and on
nothing else: not on when the frames fell, how long the nesp32 took to
answer, or which exchanges failed.

The game's handler writes to the PPU, counts the frame, and then reads the
controllers; its main loop does the rest of the frame's work after it. The
exchange is made at that read, so the buttons leave as soon as they are
read and the other console's are asked for at the last moment they can be
used. That is what lets a delay of one tick do. It was made at the end of
the handler before, a frame later for both, and the delay was 3.

## The music

The music is the one thing that keeps the frames' time and not the ticks'.
The game runs its sound engine from its main loop, once a pass, which in a
session is once a tick: every stall and every lag then held the music back
by a frame, and on real consoles over Wi-Fi it was heard to speed up and
slow down. So in a session the engine is run from the NMI instead, once in
every frame, whichever of the three the frame is.

That is safe because the engine keeps to itself. Its memory is `$00E0` to
`$00EF` and `$067E` to `$06FF`, and the game only leaves it orders there:
a sound to make, the music to play. One thing comes back: the engine
counts the music's beat, and the viruses in the one-player game's
magnifier dance to it. A session is a two-player game and has no
magnifier. So the two consoles' sound engines are not at the same place at
the same tick, and nothing of the game can tell; the tests leave the
engine's memory out of what they compare, and hold the rest to be equal.

## The link

The ROM has nesp32's library for the console (`nes/lib/nesp.inc` there) in
the menu's bank. Every exchange is made inside an NMI, where nothing can
interrupt the library's cycle-timed serial routines, so the library is
built with the receiver that gives up by counting: the console waits about
4.1 ms for a reply to begin. A reply that is late, cut short or fails its
CRC is dropped whole, and what it carried is asked for again in the next
frame.

The console reads its controller with OUT0 low for the 8 reads, which the
nesp32's UART takes for a byte or a framing error, and its decoder passes
over.

## The menu

On the title, **2 PLAYER GAME** goes to the menu, in the second bank. The
menu says the hello, as `DRMA`, asking for PEER, and from then on asks a
few times a second how the nesp32 stands (PEER's STATUS) and tells it what
the player chose (HOST, JOIN, LEAVE, LAST). It sends an order again until
it is answered, and acts on a state only once the order that should lead to
it has been.

| The menu shows | When |
|---|---|
| the nesp32's address | it is on a network |
| `NO WIFI` | it is on none: nesp32's setup ROM joins one |
| `NO NESP32` | 8 requests in a row had no answer |
| `UPDATE NESP32` | its firmware answered the hello and has no PEER |

A nesp32 that was switched off and on answers that the service is not in
use. The menu says the hello again, and gives again the order the screen
is waiting on.

When the nesp32 says it is connected, as player 1 or as player 2, the
console leaves the menu and starts a session: both consoles begin again
from the state of one just switched on, at the options of a two-player
game. They need not start at the same moment, since neither takes a tick
without the other's buttons. Each begins with the delay its nesp32 gave it
in the lobby's replies, from how long the network took while the two
connected, and with 2 if it gave none.

## A session

Every NMI that is not a lag makes one exchange, PEER's TICKS as a short
frame: five bytes out, or six, and four back.

```text
request   COUNT, FIRST and WANTED, BUTTONS[1 or 2]
reply     COUNT, BUTTONS[1]
```

The request carries this console's buttons from the first tick the nesp32
has not said it holds, two ticks of them at most, and names that tick and
the tick of the other console's that it needs next, by their low four
bits. The reply carries one tick of the other's, if the nesp32 has it. It
names no ticks: that it comes says the nesp32 holds what it was sent. A
frame carries two ticks out where a frame makes one, so the console
catches up after a failed exchange.

PEER counts each console's stream of buttons from 0. The console counts
its ticks from -5 on both, and the ticks before 0 have no buttons.

The console keeps 8 ticks of buttons each way. It stalls rather than read
its controller for a tick whose place is still held by one the nesp32 has
not taken.

### The delay

Each console keeps a delay for its own buttons, from 1 tick to 5. The two
need not be the same, and nothing is agreed between them: a console only
ever takes the buttons it is given for each tick. To make its delay a tick
longer a console sends the buttons it last read once more, for the tick
between; to make it a tick shorter it lets one read go by.

How long it should be is the nesp32's to say, from the times the network
takes (nesp32's `docs/PROTOCOL.md`, "The delay"). One exchange in 128
carries the console's report in place of a second tick of buttons, and its
reply has the delay advised after its buttons. A session's first report
sets the delay outright; after it the advice is made longer when two
reports running call for it, and a tick shorter when eight do.

### Checking that they stay alike

One tick in 256 carries no buttons. In their place each console sends a
digest of its game: of its zero page, less the link's bytes, the sound
engine's and the flag the main loop waits on, taken at the start of the
same tick on both, eight ticks before, and kept until each comes to send
it. A console whose digest differs from the other's gives the session up
and goes back to the title, as does the other. The game runs that tick on
the buttons of the tick before, for both players.

The two nesp32s also tell this build from the one before it, by the
version in its hello, and do not join the two: one would send buttons
where the other looks for a digest.

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
the padding before `$FD00`. The sample data at `$FD00` (the game never
plays a sample) is left out, and its two pages are empty.

The library's memory is 16 bytes of zero page at `$00B0` and its two
buffers at `$0330`, the session's is at `$0742`, and the menu's at `$03B0`:
all of it where the game keeps nothing.

## Ending

The console leaves a session, and starts again from its title as if reset,
when a reply says the other console is gone or the nesp32 knows of no
session (it was switched off and on), when the two games' digests differ,
or after 240 NMIs in a row that were not ticks (4 seconds).

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
