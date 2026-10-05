# Dr. Mario netplay link protocol

How two consoles play one two-player game, each with a Stick on controller
port 2 and the Sticks joined over a network. The wiring is nes-jukebox's:
the Stick drives D0 (bit 0 of `$4017`, inverted by the port's buffer) and
reads OUT0 (bit 0 of `$4016` writes), which rests at mark.

The numbers both ends share are in `firmware/stick/drnet/linkrate.py`.

Status: implemented by `net/*.inc`, `net/menu.s`, `firmware/stick/drnet`
and `host/`, and tested on two simulated consoles with the Sticks' own code
between them. On hardware, two consoles on one Wi-Fi network have played a
full game, one with a StickC Plus2 and one with a computer on the USB
serial cable.

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
| a tick | the main loop was waiting, and the buttons are here | the game's whole handler, then an exchange with the Stick |
| a stall | the main loop was waiting, but the other console's buttons are not here | the exchange only; the picture and the music stand still |
| a lag | the main loop was still at work | nothing |

So the game's memory depends on how many ticks there have been and on
nothing else: not on when the frames fell, how long the Stick took to
answer, or which exchanges failed.

## The line

| | |
|---|---|
| Rate | 21 NES CPU cycles a bit, 85227 baud, both ways |
| Console to Stick | 8N1 |
| Stick to console | 8N2: the second stop bit is the console's time to store a byte |
| Frames | 8 bytes, always, both ways |
| Check | the last two bytes: a running sum of the first six, and a running sum of that |

The console is in charge. It sends a request at the end of an NMI, and the
Stick answers at once with one reply. The console waits about 5.6 ms for
the reply to begin and then gives up; a reply that is late, cut short or
fails its check is dropped whole, and what it carried is asked for again
in the next frame.

The console reads its controller with OUT0 low for the 8 reads, which the
Stick's UART takes for a byte or a framing error. The Stick looks for a
request's first byte and good check bytes, and passes over anything else a
byte at a time.

## A session's frames

```text
request   $47, FIRST, COUNT, BUTTONS, BUTTONS, WANTED, check, check
reply     $5A, NEXT,  FROM,  COUNT | PEER, BUTTONS, BUTTONS, check, check
```

Ticks are named by their low 8 bits. Neither side is ever more than 8
ticks from what the other holds, so that is enough.

| Field | Meaning |
|---|---|
| `FIRST`, `COUNT` | the request carries this console's buttons for `COUNT` ticks (0 to 2) from tick `FIRST`: the oldest the Stick has not said it holds |
| `WANTED` | the tick of the other console's buttons that this one needs next |
| `NEXT` | the first of this console's ticks the Stick does not hold. The console sends from there next time |
| `FROM`, `COUNT` | the reply carries the other console's buttons for `COUNT` ticks (0 to 2) from tick `FROM`, which is `WANTED` |
| `PEER` | `$10` in the high nibble: the other console is gone, and nothing more of its buttons is held |

A frame carries two ticks where a frame makes one, so either side catches
up after a failed exchange. A request that is repeated carries buttons the
Stick has already taken; it takes only those it has not seen. A reply for
a tick other than the one wanted, or that says the Stick holds more ticks
than were ever read, is ignored.

The console keeps 8 ticks of buttons each way. It stalls rather than read
its controller for a tick whose place is still held by one the Stick has
not taken.

## The menu's frames

Before a session the console's menu asks and tells the Stick with control
frames, a few a second:

```text
request   $43, COMMAND, A, A, A, A, check, check
reply     $A5, STATE,   B, B, B, B, check, check
```

| `COMMAND` | | The Stick |
|---|---|---|
| 0 | status | only answers |
| 1 | host | listens for the other Stick |
| 2 | join | connects to the Stick at address `A` |
| 3 | cancel | drops whatever connection it has or is making |
| 4 | last | answers with the address it last joined in `B` (zeros if none) |

In every other reply `B` is the Stick's own IPv4 address.

| `STATE` | |
|---|---|
| 0 | not on a network |
| 1 | idle |
| 2 | hosting: waiting for the other Stick |
| 3 | connecting |
| 4 | connected, and this console is player 1 |
| 5 | connected, and this console is player 2 |
| 6 | the last join failed, or the connection was lost |

A command that is already what the Stick is doing changes nothing, so the
console sends a command again until it is answered. It acts on a state
only once the command that should lead to it has been answered. With no
answer to 8 requests in a row it shows that there is no Stick.

When the state is 4 or 5 the console leaves the menu and starts a session:
both consoles begin again from the state of one just switched on, at tick
0, at the options of a two-player game. They need not start at the same
moment, since neither takes a tick without the other's buttons.

## Between the Sticks

TCP, to port 6502 on the Stick that hosts. Each side sends `DRM1` and
reads the other's before it calls the connection good. Then:


One byte a tick each way, in order, starting with the buttons for tick
`INPUT_DELAY`. A byte's place in the stream is its tick, so the stream
must be reliable and ordered.

## The cartridge

The game fills its 32 KB, so the netplay ROM has 64 KB of PRG on the same
mapper (MMC1): the game in the first 32 KB and the menu in the second,
switched whole. The code that runs while the bank changes under it, the
start of the reset code and `net_far`, is the same bytes at the same
addresses in both banks. The menu has its own NMI handler and its own
copy of the serial routines. A flashcart or an emulator runs it; it does
not fit the original board.

## Ending

The console leaves a session, and starts again from its title as if reset,
when a reply says the other console is gone, or after 240 NMIs in a row
that were not ticks (4 seconds).

## Timing

Measured on the simulated consoles (`tests/test_lockstep.py`):

- An exchange is 1680 cycles out, the Stick's turnaround, and 1848 back.
  With a Stick that answers in 1 ms a tick's NMI is about 8100 cycles of a
  frame's 29780, and the busiest frame of a game still ends before the
  next NMI.
- With the network taking 10 ms each way nearly every frame is a tick. At
  40 ms about three in four are, and at 90 ms about half: `INPUT_DELAY` is
  fixed at 3 ticks, 50 ms, and has to cover the network, the wait for the
  other console's next frame and both Sticks.
