# Multiplayer: two consoles, one game

Four of the apps are netplay builds of a two-player game:
[Contra](../apps/contra), [Dr. Mario](../apps/drmario),
[Tetris](../apps/tetris) and [TMNT II](../apps/tmnt2). Each is played on two consoles, each console
with a nesp32 on controller port 2, the nesp32s joined over the network.
The four work the same way, and this is that way: what the player sees,
what a tick is, how the two games are kept the same, and what is still
left to do in all four.

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
| TMNT II | [apps/tmnt2/README.md](../apps/tmnt2/README.md) | its README, "How the netplay works" |

## Playing

Choose the game for two on the title, and the console asks how:

- **HOST GAME**: the nesp32 waits for the other one. The console and the
  nesp32's screen both show what player 2 has to enter.
- **JOIN GAME**: enter it (Left/Right to move, Up/Down to change a letter
  or a digit) and press Start.
- **LOCAL GAME**: two controllers on this console, as the original.

The two nesp32s meet one of two ways. HOST GAME and JOIN GAME start by
room code, and Select on either screen changes to the other way, as the
foot of the screen says (`SELECT - BY IP`, `SELECT - BY ROOM CODE`). Both
players have to choose the same way. The choice holds until the menu is
left.

- **By room code**, the first: across the Internet with no port
  forwarded. HOST GAME opens a room at the rendezvous and shows its four
  letters (no 0 or O, no 1 or I); player 2 enters them. Then each nesp32
  is told where the other is, and the two reach each other themselves
  ([`PROTOCOL.md`](PROTOCOL.md), "Meeting in a room"). It needs the
  Internet, even for two on one network, and a nesp32 whose firmware has
  rooms: an older one is UPDATE NESP32 here.
- **By address**, as before rooms: HOST GAME shows this nesp32's address,
  and JOIN GAME starts with the address last joined, or this nesp32's own.
  On one network that needs nothing more; across the Internet the host
  forwards UDP port 6502. It is for a network with no way to the
  Internet, for a nesp32 that has no rooms, and for two networks that
  rooms cannot get through.

All four games' menus have both ways. Contra and TMNT II write the foot
of the screen as `SELECT   BY IP`, their fonts having no dash.

| Game | The title's choice | Its hello |
|---|---|---|
| Contra | 2 PLAYERS | `CNTR` |
| Dr. Mario | 2 PLAYER GAME | `DRMA` |
| Tetris | 2 PLAYERS, where the original says PUSH START | `TTRS` |
| TMNT II | 2 TURTLES | `TMN2` |

The console that hosted is player 1. When the two nesp32s are connected
both consoles leave the menu and go straight into a game for two. Each
player uses controller 1 of their own console. The game for one never
shows the menu, and says nothing to a nesp32.

The menu says the hello, asking for PEER, and from then on asks a few
times a second how the nesp32 stands (PEER's STATUS, or in a room ROOM)
and tells it what the player chose (HOST_ROOM, JOIN_ROOM, HOST, JOIN,
LEAVE, LAST). It sends an order again until it
is answered, and acts on a state only once the order that should lead to
it has been. A nesp32 that was switched off and on answers that the
service is not in use; the menu says the hello again, and gives again the
order the screen is waiting on. It shows how the nesp32 stands:

| The menu shows | When |
|---|---|
| the nesp32's address | it is on a network |
| `NO WIFI` | it is on none: nesp32's setup ROM joins one |
| `NO NESP32` | 8 requests in a row had no answer |
| `UPDATE NESP32` | its firmware answered the hello and has no PEER, or, by room code, has PEER but no rooms |

By room code the host's screen says how its room stands, and the join
screen why a room could not be met in: `OPENING A ROOM`, `NO RENDEZVOUS`,
`NO SUCH ROOM`, `NOT THIS GAME` (another game's room, or another
version's), `ROOM IS FULL`, `CANNOT REACH IT`, `ROOM CLOSED`.

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
more. Across the Internet they meet by a room's code, with nothing to set
up on either router ("Meeting across the Internet", below), or by address,
with the hosting side forwarding that port to its nesp32 and player 2
entering the host's public address. Tetris has been played by address
with a port forwarded on hardware, and works; no figures were taken. The
delay will be what the distance makes it, three ticks across a continent,
five or more across an ocean.

## Meeting across the Internet

A router lets a datagram in from the Internet only as an answer to one
sent out from inside, so a nesp32 behind one cannot simply be called.
Forwarding a port gets round that, but many players cannot arrange it,
and none can behind a carrier's shared address, as on many phone
hotspots. A room gets round it with nothing set up on either router: each
nesp32 is told where the other is, and both send at once, so that each
one's sending opens its own router to the other's.

Five things take part:

| | What it does |
|---|---|
| the console's menu | asks for a room, shows its code, takes player 2's, says how it stands |
| the nesp32 (PEER, and its connection task) | finds where it can be reached, asks the rendezvous, sends to the other |
| two STUN servers (Cloudflare's and Google's) | tell a nesp32 what address and port its datagrams come from, as the Internet sees them |
| the rendezvous ([`server/rendezvous`](../server/rendezvous/README.md)) | hands out codes, and tells each nesp32 the other's addresses |
| the two routers | let the other's datagrams in once their own nesp32 has sent to it |

From HOST GAME to the first tick:

1. **Player 1's nesp32 opens its socket and finds its addresses.** It
   opens the socket at port 6502 that the whole game will be played on.
   It asks the two STUN servers from that socket, and has two addresses:
   its own on its network, and the public one the servers saw, which may
   have another port. That takes a second or so (`OPENING A ROOM`). It
   asks STUN again every 20 seconds while it waits, which also keeps its
   router's way in open.
2. **It asks the rendezvous for a room.** It is given a code and a
   session, and the console shows the code. From then on the nesp32 asks
   every two seconds whether player 2 has come, with its addresses as they
   are then.
3. **Player 2's nesp32 does the same, and joins.** It enters the code,
   opens its own socket at 6502, finds its own two addresses, and asks to
   join. The rendezvous refuses another game, or another version of this
   one (`NOT THIS GAME`), a code it does not know (`NO SUCH ROOM`), and a
   third player (`ROOM IS FULL`). Otherwise it tells player 2 the host's
   addresses and the session.
4. **Player 1 hears of player 2** when it next asks, two seconds at the
   most, and is told player 2's addresses.
5. **Both send at once, for up to eight seconds.** Player 2 calls each of
   the host's addresses, ten times a second. The host sends punches to each
   of player 2's, which are datagrams that carry nothing. Each one's
   datagrams going out are what let the other's in. The host answers only
   a call that names the session. The first address that answers is the
   path.
6. **From there it is a connection like any other:** the greetings, then
   the game, at the delay the network's time calls for. The one that
   opened the room is player 1. The rendezvous forgets the room a minute
   later. It never sees the game.

**On one network** the path is the network itself. Each nesp32's
addresses include its own on the network, which the other reaches
directly, as by address, with the urgent marking for Wi-Fi a game on one
network has. The router never has to send a datagram back to its own
public address, which many routers will not do. The rendezvous is still
needed to swap the addresses, so the Internet is too. With no way to it,
Select, and meet by address.

**What it costs: nothing.** The rendezvous is a Cloudflare Worker on the
Workers Free plan, on an account with no payment method. Past the free
plan's daily limits it stops answering until the next day (`NO
RENDEZVOUS`), and nothing is billed. A minute of waiting in a room is about
40 requests. The STUN servers are free. No game's datagrams pass through
anything of nesp32's.

**What a room cannot get through,** which is `CANNOT REACH IT` after the
eight seconds:

- both routers giving the socket a new public port for every address it
  sends to (some routers, some phone hotspots and some carriers): neither
  one's punch reaches the port the other was told of;
- a network that lets no datagrams out at all (some workplaces, schools
  and hotels).

For those, meet by address with a port forwarded at the host. A relay
that carried the game for them would cost per gigabyte, and is not here.

**On hardware** (October 2026), the first three games have been played both
ways:

- **By room code**, between a console on a fiber connection and one on a
  phone's 5G hotspot, Dr. Mario first and then Tetris and Contra. The
  hotspot's side is behind its carrier's shared address (STUN saw port
  6502 as 41747), where no port can be forwarded. Both routers kept one
  public port for every address the socket sent to, which is what
  punching needs.
- **By address**, with Select, between two consoles on one home network.

TMNT II has been played on hardware since (October 2026, its README):
a session, the menu, and level 7 for two at the game's own speed.

The nesp32's log (`firmware/deploy.sh watch`) says the same of any
network: `stun:` lines with what each server saw, and whether the router
keeps the port.

**To try it with no Internet**, from a computer: `host/rendezvous.py` is
a stand-in for the rendezvous, and `host/serial_host.py --game
--rendezvous URL` points a computer standing in for a nesp32 at it, or at
`wrangler dev`.

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
nothing at all. All of Contra's game runs inside its NMI, and all of
TMNT II's, so there a tick is the NMI that runs the game, and a lag is
the game's own lag frame, left as it was.

**The exchange is made where the game reads its controllers**, before the
game's work: after the NMI's writes to the PPU, and before the main loop
(or, in Contra and TMNT II, the rest of the NMI) does the frame's work.
TMNT II's is made a little before its read, where the NMI has set up the
counter for its splits of the screen and before it lets the IRQs in, so
that no IRQ breaks into the serial routines. So the buttons
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
up and slow down. Contra and TMNT II run it from their NMIs anyway.

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

### What it costs a frame

The exchange is made in the NMI and takes some 3100 cycles, a tenth of a
frame, in every NMI that is not a lag. A game with that much to spare
loses nothing. A game whose frames are nearly full already overruns more
of them, and stands still for a frame each time: the same game, slower,
and on both consoles, as the other waits for its buttons. Contra's
busiest scenes slow for it: its level 6, crowded in the original too,
would overrun 28 frames in 100 with the exchange, against 11 alone. Its
netplay ROM builds the sprites with less work, some 900 cycles a frame,
which brings that to 24 (its `docs/Netplay.md`, "The sprite pass").
TMNT II's level 7 for two would slow a lot: 26 frames in 100, against 2.
Its netplay ROM builds the sprites faster, from the cartridge's PRG RAM,
which brings that to 3 in 100 (its README, "The frame rate"). A game's
own work is the place to find the cycles; a faster exchange (To do)
would give some back to every game.

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
| TMNT II | its zero page, less the link's bytes, the sound engine's, what its IRQs keep and the flag of a frame under way, and its sprites |

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
(`net_ask`), and so does TMNT II; Dr. Mario and Tetris in the next frame.

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
- Meeting by room code needs the Internet, even for two consoles on one
  network, and does not get through every pair of networks ("Meeting
  across the Internet"). By address is there for both.

## To do

What is left on the nesp32 itself is in [`TODO.md`](TODO.md). In all
four games:


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
