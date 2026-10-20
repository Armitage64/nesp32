# Multiplayer: two consoles, one game

Three of the apps are netplay builds of a two-player game:
[Contra](../apps/contra), [Dr. Mario](../apps/drmario) and
[Tetris](../apps/tetris). Each is played on two consoles, each console
with a nesp32 on controller port 2, the nesp32s joined over the network.
The three work the same way, and this is that way: what the player sees,
what a tick is, how the two games are kept the same, and what is still
left to do in all three.

What the nesp32s do between them is the PEER service's, in
[`PROTOCOL.md`](PROTOCOL.md): its lobby, its exchange of buttons, the
datagrams between the two nesp32s, and how the input delay is advised.
This is the console's side. What is a game's own (its memory, its
cartridge, what had to change in it, and the figures from the simulation
and from hardware) is in its own docs:

| Game | Its README | Its netplay doc |
|---|---|---|
| Contra | [apps/contra/README.md](../apps/contra/README.md) | [apps/contra/docs/Netplay.md](../apps/contra/docs/Netplay.md) |
| Dr. Mario | [apps/drmario/README.md](../apps/drmario/README.md) | [apps/drmario/docs/PROTOCOL.md](../apps/drmario/docs/PROTOCOL.md) |
| Tetris | [apps/tetris/README.md](../apps/tetris/README.md) | [apps/tetris/docs/PROTOCOL.md](../apps/tetris/docs/PROTOCOL.md) |

## Playing

Choose the game for two on the title, and the console asks how:

- **HOST GAME**: the nesp32 waits for the other one. The console and the
  nesp32's screen both show the address player 2 has to enter.
- **JOIN GAME**: edit the address (Left/Right to move, Up/Down to change a
  digit) and press Start. It starts as the address last joined, or this
  nesp32's own.
- **LOCAL GAME**: two controllers on this console, as the original.

| Game | The title's choice | Its hello |
|---|---|---|
| Contra | 2 PLAYERS | `CNTR` |
| Dr. Mario | 2 PLAYER GAME | `DRMA` |
| Tetris | 2 PLAYERS, where the original says PUSH START | `TTRS` |

The console that hosted is player 1. When the two nesp32s are connected
both consoles leave the menu and go straight into a game for two. Each
player uses controller 1 of their own console. The game for one never
shows the menu, and says nothing to a nesp32.

The menu says the hello, asking for PEER, and from then on asks a few
times a second how the nesp32 stands (PEER's STATUS) and tells it what the
player chose (HOST, JOIN, LEAVE, LAST). It sends an order again until it
is answered, and acts on a state only once the order that should lead to
it has been. A nesp32 that was switched off and on answers that the
service is not in use; the menu says the hello again, and gives again the
order the screen is waiting on. It shows how the nesp32 stands:

| The menu shows | When |
|---|---|
| the nesp32's address | it is on a network |
| `NO WIFI` | it is on none: nesp32's setup ROM joins one |
| `NO NESP32` | 8 requests in a row had no answer |
| `UPDATE NESP32` | its firmware answered the hello and has no PEER |

## The nesp32

The hat is nesp32's ([`WIRING.md`](WIRING.md)), as for every ROM that uses
a nesp32. Flash nesp32's firmware (`firmware/README.md`) and join a Wi-Fi
network from the controller with its setup ROM, once: the nesp32 keeps the
network and joins it by itself from then on. Nothing is set up from a
computer, and nothing is chosen on the nesp32: the ROM says what it is
when its menu opens, and the firmware needs nothing new for a game. PEER
pairs two nesp32s whose consoles said the same name and version in their
hello.

The nesp32s talk over UDP port 6502. On one network that needs nothing
more. Across the Internet the hosting side has to forward that port to its
nesp32, and player 2 enters the host's public address. Tetris has been
played that way on hardware, and works; no figures were taken. The delay
will be what the distance makes it, three ticks across a continent, five
or more across an ocean.

## The idea

Both consoles run the whole game. Only buttons cross the link: one byte for
each *tick*, a tick being one frame of the game. A console takes a tick
only when it holds both players' buttons for it, so both games see the
same buttons at the same tick and stay the same game.

A console's own buttons are used some ticks after the frame they were read
in, its *input delay*. That is the time they have to reach the other
console. Nobody sets it: each console keeps its own, from 1 tick to 5, and
changes it as the game goes ("The delay", below).

An NMI in a session is one of three things:

| | When | What runs |
|---|---|---|
| a tick | the main loop was waiting, and the buttons are here | the game's whole handler, with the exchange where the game reads its controllers |
| a stall | the main loop was waiting, but the other console's buttons are not here | the handler as far as the controllers, and the exchange. The NMIs that follow make the exchange again and write nothing to the PPU, whose picture stands; the one that has the buttons goes on from there |
| a lag | the main loop was still at work | nothing of the game |

So the game's memory depends on how many ticks there have been and on
nothing else: not on when the frames fell, how long the nesp32 took to
answer, or which exchanges failed. Dr. Mario's and Tetris's NMIs change
the game's state (they draw the playfields, count the frames, step the
random numbers), so an NMI that finds the main loop still at work does
nothing at all. All of Contra's game runs inside its NMI, so there a tick
is the NMI that runs the game, and a lag is the game's own lag frame, left
as it was.

**The exchange is made where the game reads its controllers**, before the
game's work: after the NMI's writes to the PPU, and before the main loop
(or, in Contra, the rest of the NMI) does the frame's work. So the buttons
leave as soon as they are read, and the other console's are asked for at
the last moment they can be used. That is what lets a delay of one tick
do. Dr. Mario made its exchange at the end of the handler at first, a
frame later for both, and needed a delay of 3.

## The music

The music is the one thing that keeps the frames' time and not the ticks'.
In a session the sound engine runs once in every NMI, whichever of the
three the frame is. Dr. Mario and Tetris run it from their main loop, once
a pass, which in a session is once a tick: every stall and every lag then
held the music back by a frame, and on real consoles it was heard to speed
up and slow down. Contra runs it from its NMI anyway.

That is safe because the engine keeps to itself: the game only leaves it
orders, a sound to make, the music to play, and reads nothing back that
matters to a game for two. So the two consoles' sound engines are not at
the same place at the same tick, and nothing of the game can tell. The
engine's memory is left out of the check below, and out of what the tests
compare.

## Starting a session

When the nesp32 says it is connected, as player 1 or as player 2, the
console leaves the menu and starts a session: both consoles begin again
from the state of one just switched on (top score and high scores
included), and go straight to a game for two, past the title. They need
not start at the same moment, since neither takes a tick without the
other's buttons: a tick is counted, not timed.

PEER counts each console's stream of buttons from 0. The console counts
its ticks from -5 on both, and the ticks before 0 have no buttons; the
first buttons either sends are tick 0's. Each console begins
with the delay its nesp32 gave it in the lobby's replies, from how long the
network took while the two connected, and with 2 if it gave none.

## The exchange

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
catches up after a failed exchange. A tick's byte is the controller as it
was read; the game's own code works out what is newly pressed and what
is held, for both players. Between the nesp32s the buttons go as
datagrams, each repeating what the other end has not said it has, so that
a lost packet holds nothing up (PEER's "Between the nesp32s").

The console keeps a ring of buttons each way, and stalls rather than read
its controller for a tick whose place is still held by one the nesp32 has
not taken.

### The delay

Each console keeps a delay for its own buttons, from 1 tick to 5, and
changes it as its nesp32 advises: the delay that covers nine in ten of the
network's times, so that the game stands still a frame or two for a press
that meets one of the rest. One exchange in 128 carries the console's
report, and its reply the delay advised. How the delay is changed, and how
the nesp32 works out its advice, is PEER's, in
[`PROTOCOL.md`](PROTOCOL.md), "The delay".

### Checking that they stay alike

One tick in 256 carries no buttons. In their place each console sends a
digest of its game, taken at the start of the same tick on both, eight
ticks before, and kept until each comes to send it. A console whose digest
differs from the other's gives the session up and goes back to the title,
as does the other. The game runs that tick on the buttons of the tick
before, for both players.

What the digest covers is each game's own:

| Game | The digest is of |
|---|---|
| Contra | its zero page and its sprites |
| Dr. Mario | its zero page, less the link's bytes, the sound engine's and the flag the main loop waits on |
| Tetris | the same as Dr. Mario's, less the session's one byte there too, and both playfields |

The two nesp32s also tell one build from another, by the name and version
in its hello, and do not join the two: one might send buttons where the
other looks for a digest.

## The link

Each ROM has nesp32's library for the console (`nes/lib/nesp.inc`). Every
exchange is made inside an NMI, where nothing can interrupt the library's
cycle-timed serial routines, so the library is built with the receiver
that gives up by counting: the console waits about 4.1 ms for a reply to
begin. A reply that is late, cut short or fails its CRC is dropped whole,
and what it carried is asked for again. Contra asks again in the same NMI
(`net_ask`); Dr. Mario and Tetris in the next frame.

The strobe line to the controllers (OUT0) is also the line to the nesp32,
and rests high. The console reads its controller with it low for the 8 reads,
which the nesp32's UART takes for a byte or a framing error, and its
decoder passes over.

**The controller is read twice while a sample plays.** On a real NES the
fetch of a sample's byte that falls on a read of `$4016` reads it once
more: a button is lost, the ones after it come a place early, and Right is
pressed behind them. Dr. Mario's own routine reads twice and compares,
which is why a local game never showed it, and a session read once, so a
player had a press of Right that nobody made. A
session now reads twice while the sample channel has bytes to fetch, and
keeps the buttons of the last time both reads were alike if they differ.
[`PHANTOM-RIGHT.md`](PHANTOM-RIGHT.md) has the whole of it. The fetches
take cycles from the serial routines too, which is why a real NES once
misheard replies while Contra's music played, and the MiSTer did not
(Contra's Netplay.md, "On hardware").

## Ending

The console leaves a session, and starts again from its title as if reset,
when a reply says the other console is gone or the nesp32 knows of no
session (it was switched off and on), when the two games' digests differ,
or after 240 NMIs in a row that were not ticks (4 seconds). One end that
fails takes both consoles back to the title within seconds: one by its own
end's silence, the other by the lost connection.

## Known limits

- Both consoles must run the same build: the nesp32s tell another game, or
  an older build of the same one, from it, and will not join the two.
- The input delay is 1 to 5 frames, each console's own, as its nesp32
  advises. A network slower than 5 frames covers slows the game rather
  than breaks it.
- A button press shorter than a stall is not seen: no controller is read
  in one.
- In a stall the picture stands still, and a sound the game asks for is
  heard when it asks, which is a tick's time and not a frame's.
- The netplay ROMs need a flashcart or an emulator.

## To do

What is left on the nesp32 itself (meeting across the Internet without a
port forwarded, a steadier way between two nesp32s) is in
[`TODO.md`](TODO.md). In all three games:

- **Say why on the console** when a session ends (the other console left,
  the nesp32 went quiet, the games differed); it only goes back to the
  title now.
- **Games that differ** (for later): a dump of each console's RAM to its
  nesp32 when the digests differ, to learn why; and if it comes back, the
  host's game copied to the other in place of ending the session. Tetris
  would be the easiest: its NMI draws the playfields again from RAM, so
  the RAM is most of what has to be sent. Dr. Mario's bottles are in RAM
  too, and whether the game can draw them again from there, or the
  screen's tiles have to be sent too, is not known.
  Contra's would take its screen's tiles and its 8 KB of CHR RAM as well,
  about 12 KB, and going back to the title may well stay.
- **A faster exchange.** The line runs three times faster than the link's
  rate (nes-throughput's test), which is about 1.5 ms of every exchange.
  And no wait for a reply in a frame whose buttons from the other console
  are already here, which they are whenever the delay has a tick to spare.
- **No zero delay, and no rolling back.** A delay of 0 would need the
  other console's buttons in the frame they were read, which works only
  while the two consoles' frames happen to line up. Rolling back, as newer
  games do, needs a copy of the game, and there is nowhere to keep one.
