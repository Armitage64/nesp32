# Netplay

`make` builds a second ROM, `build/contra_net.nes`, in which a two-player
game can be played on two consoles: each has a
[nesp32](../../..) on controller port 2, each
player uses controller 1 of their own console, and the nesp32s are joined
over the network. Everything it changes is under `.ifdef NETPLAY`, so
`build/contra.nes` is still the original, byte for byte, and `make verify`
says so.

The figures below are the simulation's (`make test`) unless they say
otherwise. On hardware sessions have been played between a MiSTer and a
real NES on one home network, and what was seen is under "On hardware"
below: it plays well, and slows when many enemies are on the screen.

What the three netplay games share (the menu, the nesp32, what a tick, a
stall and a lag are, the exchange, the delay, the check and how a session
ends) is in nesp32's [`docs/MULTIPLAYER.md`](../../../docs/MULTIPLAYER.md).
This is what is Contra's own, with its figures.

## Playing

Pick 2 PLAYERS at the title and press Start. A menu comes up:

| | |
|---|---|
| HOST GAME | the nesp32 opens a room, and the screen shows its code, which player 2 has to enter |
| JOIN GAME | a room's code to edit, and Start joins that room |
| LOCAL GAME | the game as it always was, for a second controller on port 2 |

Select on HOST GAME's screen or JOIN GAME's meets by address instead, as
before rooms: HOST GAME shows the nesp32's address, and JOIN GAME has one
to edit, starting as the one last joined. How the two ways work is
nesp32's [`docs/MULTIPLAYER.md`](../../../docs/MULTIPLAYER.md).

When the two are connected both consoles go straight into a two-player
game, at the screen that names the first stage, and from there they are
one game. Player 1 is the console that hosted. Only player 1 can pause, and
only player 1 answers CONTINUE, as in the original. When the game ends the
title comes back, still joined, and player 1's Start begins another.

1 PLAYER never shows the menu, and says nothing to a nesp32.

## How it works

Both consoles run the whole game, and only buttons cross: one byte for each
frame of the game, each way. A console runs a frame of the game (a *tick*)
only when it holds both players' buttons for it, so the two games see the
same buttons at the same tick and stay the same game. A console's own
buttons are used some ticks after they were read, the *input delay*, which
is the time they have to reach the other console. Nobody sets it: each
console keeps its own, and it changes as the game goes (below).

All of Contra's game runs inside its NMI handler, and so does this
(`net/net.inc`, in the space at the end of bank 7). An NMI in a session is
one of three things:

- **A tick.** The handler writes to the PPU, runs the sound engine, reads
  this console's controller, makes one exchange with the nesp32 (buttons
  out, the other console's in) and, if it then has the buttons for this
  tick, runs the game.
- **A stall.** The other console's buttons are not here. The game does not
  run, and the NMIs that follow leave the PPU alone, run the sound engine
  and try again. The picture stands still and the music goes on.
- **A lag.** The last tick's work was not finished. That is the game's own
  lag frame, left as it was.

The exchange is made before the game's work and not after it, which is what
lets a delay of one tick do: the buttons leave as soon as they are read,
and the other console's are asked for at the last moment they can be used.
nes-drmario made its exchange after the game's work at first, and needed
three; it now makes it this way too.

### What had to change in the game

- **The random number.** The original adds the frame counter to
  `RANDOM_NUM` in its idle loop for as long as the CPU has nothing else to
  do, so its value depends on how many cycles each frame took. Two consoles
  given the same buttons do not play the same game (`tests/test_console.py`
  shows it). The netplay ROM's idle loop does nothing, and the number is
  stirred once a tick from the frame counter and both players' buttons.
  This is so in a local game too.
- **The controller read.** The strobe line is also the line to the nesp32,
  and has to rest high. The read drops it for the eight reads and raises it
  again.
- **The NMI.** It goes to the menu while the menu is up, and stops short of
  the game in a stall.
- **The title's Start**, which goes to the menu first when 2 PLAYERS is
  picked.
- **The reset**, which sets the line to the nesp32 and starts a session if
  the menu asked for one.

The sound engine is not part of the game for this purpose: it runs once in
every NMI, tick or not, and its memory differs between the consoles.

### Starting alike, the delay and the check

As in every netplay game (nesp32's
[`docs/MULTIPLAYER.md`](../../../docs/MULTIPLAYER.md)): a session starts
with both consoles reset, top score included, and then at a new two-player
game in place of the title; ticks are counted from -5; each console keeps
its own delay, from 1 tick to 5, as its nesp32 advises; and one tick in
256 carries a digest of the game in place of buttons, here of its zero
page and its sprites.

### The link

nesp32's library for the console (`nes/lib/nesp.inc` there), with the
receiver that gives up by counting, since every exchange is made in an NMI.
Its serial routines count CPU cycles. They have the page before the samples
in bank 7, its CRC table is in bank 1 (the sound engine's bank, which is
the one in place when an exchange is made), and the menu is in bank 5
(`net/menu.inc`), but for its screens. Bank 5 has no room for them
beside the menu's code since it has rooms as well as addresses, so they
are at the end of bank 6 (`net/menu_far.inc`), and the menu reaches them
through a call in the fixed bank (`net_far_draw`). That bank had eight
bytes to spare, and has two now: its calls to bank 1 write the bank
number themselves rather than call the game's routine for it. The game has no run of zero page to spare, so the
library's memory is placed a byte at a time (`net/ram.inc`): in seven bytes
of zero page that the game never touches, and past the end of its buffer of
writes for the PPU.

The exchange is the PEER service's TICKS as a *short frame*, five bytes out
and four back, as in every netplay game.

## What the simulation measured

`tests/console.py` is the game on py65 with as much of an NES round it as
the game uses, the sample channel's stolen cycles included.
`tests/netplay.py` puts two of them on a table, each with the nesp32's own
firmware code built for this computer, and a network between the two with a
delay. The consoles' frames do not line up, and one can be made to run
fast.

**How much of a frame the game uses.** The original, two players who are
kept alive, running right and shooting from the start of each level, 2750
frames each. A frame is 29780 cycles.

| Level | Median | 9 in 10 under | Frames overrun | With an exchange of 4012 | With one of 6710 |
|---|---|---|---|---|---|
| 1 | 18784 | 25184 | 2.9% | 8.7% | 16.0% |
| 2 | 17242 | 21191 | 0.0% | 0.1% | 2.9% |
| 3 | 15851 | 26036 | 0.9% | 10.5% | 12.8% |
| 4 | 18129 | 21736 | 0.0% | 0.5% | 4.5% |
| 5 | 17529 | 20827 | 0.0% | 0.3% | 2.9% |
| 6 | 19568 | 25055 | 0.2% | 7.1% | 21.8% |
| 7 | 18240 | 21714 | 0.0% | 0.1% | 4.3% |
| 8 | 17893 | 21007 | 0.0% | 0.3% | 2.4% |

The last two columns are worked out from the first three: the frames that
would no longer fit with that many cycles more. Players who never stop
scrolling the screen are the worst case, and the levels that scroll
sideways or up are where it shows.

**What the exchange costs.** 6710 cycles as PEER's ordinary frames, 10
bytes out and 11 back. 4012 as short frames of six bytes each way, which
is what the sessions on hardware below were played with. 3112 now, with
five bytes out and four back and the CRCs worked out in fewer cycles; and
the controller is read once, not twice, while no sample plays, which is
170 more. An overrun frame is a frame in which the game stands still on
both consoles, so in the busiest places a session runs slower than a
local game. From the table's frames, those that would overrun with about
2950 cycles more, against 4012:

| Level | With 2950 | With 4012 |
|---|---|---|
| 1 | 7.0% | 9.2% |
| 3 | 8.3% | 10.5% |
| 6 | 3.7% | 7.0% |
| the others | 0.2% at the most | 0.5% at the most |

**What the network may take.** With the input delay at 1, about 940 frames
of a session with the consoles' frames set against each other in three
ways:

| Between the nesp32s, each way | Frames that waited for buttons |
|---|---|
| 5 ms | none |
| 7 ms | none, or 3 |
| 8 ms | none, or 30 |
| 9 to 10 ms | none, or more than one in five, by how the consoles' frames fall |
| 12 ms | from one in fifteen to more than one in five |

With the delay at 2 none waited at 20 ms, and at 24 ms none or 17. With 3,
none at 35 ms. Those were with the delay held where it was put.

**The delay finding its own level** (`tests/test_lockstep.py`). On networks
of 5, 20 and 35 ms a session begins at 1, 2 and 3 and stays. Begun at 1 on
a network of 20 ms, both consoles are at 2 within 500 frames and wait for
next to nothing after. Begun at 2 on one of 3 ms, both are at 1 within
1300 frames. Begun at 1 on one console and 3 on the other, the game is the
same on both. On a network of 150 ms or more both go to 5, and the game
still waits.

**That the game is the same.** Every test that plays a session compares a
digest of the two consoles' memory before each tick, less the sound
engine's and the link's own: on quick and slow networks, with replies lost
and damaged on the line, with a nesp32 whose clock is 1.5% out, with one
console's clock fast, and with the music's samples taking their cycles
throughout.

## On hardware

Across the Internet by a room's code, between a console on a fiber
connection and one on a phone's 5G hotspot, with nothing forwarded at
either, and by address with Select on one home network: both met and
played, with the menu's screens drawn from bank 6 as they should be. No
figures were taken.

Before that, two consoles on one home network, each nesp32 joined to the same access
point, with the build before the datagrams and the delay that sets itself:

- With the delay at 1, about one frame in seven waited for buttons.
- With the delay at 2, 82 frames in 2600 waited (3%), and 5 exchanges were
  asked again because a reply was not heard (0.2%). It was the same with
  the game paused and silent as in play: the music's samples, which take
  cycles from the serial routines, are not what spoils it.
- The network between the two nesp32s took 4 to 10 ms there and back as a
  rule, and 126 ms at the worst. The waiting is those spikes, on the way
  through the access point.

Then with the datagrams and the delay setting itself, by a first rule
that made it longer whenever buttons were late: about 7400 frames.

- The datagrams work: both consoles played the same game throughout.
- The delay went to 5 on one console and 4 on the other, and still 1.5%
  and 1.1% of frames waited. A network with spikes is late in bursts that
  no delay covers, so that rule only made every press slower. The rule is
  now the one above.
- Through the access point the network took over 14 ms there and back
  for one packet in seven, over 40 ms for one in twenty-six, and 419 ms
  at the worst. Radio to radio, by ESP-NOW, it was over 14 ms for one in
  thirteen and over 40 ms for one in several hundred, 57 ms at the worst:
  the access point makes it worse, and the air alone is not clean either.
  Marking the packets for Wi-Fi's first class did not cure it.
- One console's nesp32 was asked again for 2% of its replies, and the
  other's for none.

Then with the delay by the rule above, and the figures in the nesp32s'
logs (nesp32's `firmware/deploy.sh watch`): a MiSTer that hosts, with a
StickS3, and a real NES that joins, with a StickC Plus2.

- The delay keeps to 1, and goes to 2 for a while when more than one in
  ten of the network's times call for it. The network took 3 to 7 ms
  there and back as a rule that day, over 14 ms for one packet in
  twenty-five, and 56 ms at the worst.
- **The real NES mishears its nesp32's replies while the music plays**:
  one in twenty to one in twelve of them, and next to none with the game
  paused and silent. The MiSTer mishears none. The music's drums are
  samples, and each byte a sample fetches stops the CPU for a few cycles
  that the serial routines cannot see. The nesp32 answers in 80
  microseconds, 382 at the slowest: the replies are on time, and are read
  wrong. (The first run's finding that the samples did not matter was
  from the MiSTer's side.)
- Each reply misheard stood the game still for a frame, and the other
  console with it: of the 242 frames in 6983 that the MiSTer waited (3.5%),
  about 212 were the NES asking again. So the console now asks again in
  the same NMI when it hears no reply (`net_ask`). With that the NES asked
  again 374 times in 4400 frames, and the MiSTer waited 74 (1.7%), with
  the network's own lateness in that.
- Then the receiver was made to look for each byte of a reply where it is
  due, 6 cycles a look in place of 13 (nesp32's `docs/PROTOCOL.md`, section
  7). With its samples aimed a little before the middle of the bit the NES
  misheard 124 replies in 4650; with them aimed at the middle, and a
  frame's first byte looked for more closely too, none in 4400.
- What is left is the network. On a day when one packet in fourteen took
  over 14 ms there and back, the delay kept to 1 and three frames in a
  hundred waited.
- It plays well. It slows when many enemies are on the screen: those are
  the frames with least to spare, where the exchange, and a second one
  when a reply is misheard, no longer fit (the table above).

Then with the exchange made smaller, five bytes out and four back, and a
session begun straight in the game:

- Both work. In 4500 frames one reply was misheard between the two
  consoles, and with one packet in twenty-three taking over 14 ms the
  delay kept to 1 and one frame in a hundred waited.
- The busy scenes still slow, less than before, and it is playable. A
  local two-player game most likely slows there too, with that many
  sprites on the screen: the original overruns frames of its own (the
  table above).
- The first build of it showed a black screen once the two had joined.
  The game was running: the picture is turned on by a setting that the
  title's graphics leave, and a session that skips the title has to leave
  it itself.

A flash cartridge that shows a grey screen with a new build, or a dark
grey one, has more than once shown the game when the file was copied
again, the fourth time on one occasion. Its card's reader is at fault, not
the ROM: the file's MD5 on the card says which.

The ROM showed a grey screen from an Everdrive N8 until the reset turned
the NMI off before anything else: the cartridge starts a game with the NMI
on and its own leavings in memory, which the handler acted on.

## Not done, and not known

- **The slowdown when the screen is crowded.** Less than it was, and
  still there: those are the frames with least to spare, where the
  original overruns too, and the exchange takes a tenth of every frame.
  What is left to try, if it is wanted: making no wait for a reply in a
  frame whose buttons from the other console are already here, which they
  are whenever its delay has a tick to spare; and leaving the reply's CRC
  at one byte. And to see how a local two-player game does in the same
  scenes, which is the least this can come to.
- **Player 2 cannot pause.** The game reads only player 1's Start.
- **Probotector**, the PAL release.

What is left in all three netplay games (a message when a session ends,
games that differ, no zero delay, a press shorter than a stall) is in
nesp32's [`docs/MULTIPLAYER.md`](../../../docs/MULTIPLAYER.md), "To do"
and "Known limits". What is left on the nesp32 itself is in
[nesp32's `docs/TODO.md`](../../../docs/TODO.md).

## Building and testing

```
make            build/contra.nes and build/contra_net.nes
make verify     check the original against its SHA-512
make test       the simulation's tests
```

The game's code is vermiceli's disassembly, the submodule
`third_party/nes-contra-us` (`git submodule update --init`), and
`baserom.nes` has to be in this directory, as it has to be in the
disassembly's for its own `build.sh`. nesp32 is the top of this repository
(`NESP32=` says where else). The tests need `requirements-dev.txt` and take
about a quarter of an hour.

| | |
|---|---|
| `net/net.inc` | the session: bank 7 |
| `net/menu.inc` | the menu: bank 5 |
| `net/menu_far.inc` | the menu's screens: bank 6 |
| `net/ram.inc` | the memory both use |
| `net/contra_net.cfg` | the disassembly's `contra.cfg`, with room for the link's library |
| `patches/` | the lines that call these, for the disassembly's `bank5.asm`, `bank6.asm`, `bank7.asm` and `ines_header.asm` |
| `tests/console.py` | the simulated console |
| `tests/netplay.py`, `tests/wire.py` | two of them, their nesp32s and the network |
| `tests/test_console.py` | the original is not the same game on two consoles, and the netplay ROM is |
| `tests/test_lockstep.py` | sessions |
| `tests/test_menu.py` | the menu, and HOST GAME and JOIN GAME ending in one game, by room code and by address |
