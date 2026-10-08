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
(`tests/`). On hardware a full network game has been played with it; the README
has what is known of that, and what was learned from the prototype before
it, which had a MicroPython firmware and a protocol of its own.

## The idea

Both consoles run the whole game. Only buttons cross the link: one byte for
each *tick*, a tick being one NMI that the game takes. A console takes a
tick only when it holds both players' buttons for it, so both games see the
same buttons at the same tick and stay the same game.

A console's own buttons are used `INPUT_DELAY` ticks (3) after the frame
they were read in. That is the time they have to reach the other console.
The first `INPUT_DELAY` ticks of a session have no buttons on either.

An NMI in a session is one of three things:

| | When | What runs |
|---|---|---|
| a tick | the main loop was waiting, and the buttons are here | the game's whole handler, then an exchange with the nesp32 |
| a stall | the main loop was waiting, but the other console's buttons are not here | the exchange only; the picture stands still |
| a lag | the main loop was still at work | nothing of the game |

So the game's memory depends on how many ticks there have been and on
nothing else: not on when the frames fell, how long the nesp32 took to
answer, or which exchanges failed.

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
each of its two banks, at the same places in memory. Every exchange is made
inside an NMI, where nothing can interrupt the library's cycle-timed serial
routines, so the library is built with the receiver that gives up by
counting: the console waits about 4.1 ms for a reply to begin. A reply that
is late, cut short or fails its CRC is dropped whole, and what it carried
is asked for again in the next frame.

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
without the other's buttons.

## A session

Every NMI that is not a lag ends with one exchange, PEER's TICKS:

```text
request   FIRST, WANTED, BUTTONS[0 to 2]
reply     NEXT,  FROM,   LOST, BUTTONS[0 to 2]
```

The request carries this console's buttons from the first tick the nesp32
has not said it holds, two ticks of them at most, and names the tick of
the other console's that it needs next. The reply says which of this
console's the nesp32 now holds, and carries up to two ticks of the
other's. A frame carries two ticks where a frame makes one, so either side
catches up after a failed exchange.

PEER counts each console's stream of buttons from 0. The console counts
its ticks from -`INPUT_DELAY`, so that the buttons read in a session's
first frame are those of tick 0.

The console keeps 8 ticks of buttons each way. It stalls rather than read
its controller for a tick whose place is still held by one the nesp32 has
not taken. A reply for a tick other than the one wanted, or that says the
nesp32 holds more ticks than were ever read, is ignored.

## The cartridge

The game fills its 32 KB, so the netplay ROM has 64 KB of PRG on the same
mapper (MMC1): the game in the first 32 KB and the menu in the second,
switched whole. The code that runs while the bank changes under it, the
start of the reset code and `net_far`, is the same bytes at the same
addresses in both banks. The menu has its own NMI handler and its own
copy of the link's library. A flashcart or an emulator runs it; it does
not fit the original board.

In the game's bank the session's code takes space the game does not use:
the padding before `$FD00`, the sample data at `$FD00` (the game never
plays a sample), and the padding after the reset code. The library's two
serial routines share the first page of the samples', and the rest of the
library follows them; about 120 bytes of the bank are left.

The library's memory is 16 bytes of zero page at `$00B0` and its two
buffers at `$0330`, the session's is at `$0742`, and the menu's at `$03B0`:
all of it where the game keeps nothing.

## Ending

The console leaves a session, and starts again from its title as if reset,
when a reply says the other console is gone, when the nesp32 answers that
it knows of no hello (it was switched off and on), or after 240 NMIs in a
row that were not ticks (4 seconds).

## Timing

Measured on the simulated consoles (`tests/test_lockstep.py`):

- An exchange is 9 to 11 bytes out, 210 cycles each, the nesp32's
  turnaround, and 10 to 12 bytes back, 231 cycles each, with the CRC of
  each worked out besides. With a nesp32 that answers in 0.2 ms, a tick's
  NMI is about 8500 cycles of a frame's 29780, and the busiest frame of a
  game still ends before the next NMI, at about 27400. (On hardware its
  firmware has answered other ROMs in about 0.07 ms, and in 0.5 at the
  slowest.)
- A nesp32 that takes longer makes the NMI longer, and more frames lags:
  every frame was a tick with it taking up to 1 ms, and about 97 in 100
  with it taking 5 ms. A reply that has not begun 4.1 ms after the request
  is not heard at all.
- With the network taking 10 ms each way nearly every frame is a tick. At
  40 ms about three in four are, and at 90 ms under half: `INPUT_DELAY` is
  fixed at 3 ticks, 50 ms, and has to cover the network, the wait for the
  other console's next frame and both nesp32s.
