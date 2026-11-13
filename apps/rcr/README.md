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
cycles a bit. On hardware, with the late read ("How the netplay works"),
it plays well: the input is quick, and with two players it runs faster
than the original does with two on one console, some 26 passes a second
in a fight against 21 ("The frame rate"). Players get it as a patch on
nesp32's web site, with the other games' (nesp32's `tools/gen_web.py`).

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
  for the next tick, which the next pass's read takes, in each NMI until
  the other console's buttons for it are here. The first NMI of a pass
  sends the buttons its read took; the other console's come in for its
  second, mostly, and then a pass has two exchanges.
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

**This console's buttons are read late in the pass** (`net_read_late`).
A press only has to reach the other console by the end of the pass before
the tick it is for, which is the nesp32's advice in frames (`net_lead`)
after it is sent. So in play, with a delay of 1, the controller is read
for the next tick in the NMI that many frames before the pass is to end,
and sent in that NMI's exchange. A pass ends at its second NMI, or at the
first after its work is done if later: the last pass's work foretells it
(`net_work`, measured from the end of the work, `net_pass_done`, in place
of the pass's last call). A pass whose work ends sooner than foretold has
the read in the NMI after it, which may be the pass's last: then the
other console's buttons come an NMI later, and the next pass waits a
frame. With no buttons yet, the read waits for an NMI that brings them,
and reads this console's controller then if it has not. On the screens
that read with the NMI off, and with a delay of more than 1, the
controller is read at the game's read, as the game reads it alone.

In the simulation, at 2.5 ms each way and a delay of 1, the game reads a
press some 3.2 frames after it is made, where alone it takes 2.2
(`tests/test_lockstep.py`). Read at the top of the pass it took 5.1: the
whole pass, two frames or three. The passes a second are as they were.
The first build read the controller in the NMI after the read, for the
tick after that, which was a tick more again.

**The delay is half the nesp32's advice**, rounded up (`net_advise`): the
nesp32 counts a tick as a frame, and this game's are two or three, and a
read at the top of a pass is sent at its first NMI, so one tick covers 2
frames at the most. The report the console sends counts as late only the
tries a read waited for.

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
- **The pass's last call** (`net_pass_done`, before `MAIN_WAIT`): the
  call, and a mark that the pass's work is done, for the late read.
- **The sprites** ("The frame rate"): `DRAW_OBJECTS`'s wait
  (`net_draw_begin`), the pass's call that ends the sprites' page
  (`net_draw_end`), and the NMI's sending of the page (`net_sprite_dma`).
- **The banks** ("The frame rate"): `BANK_PAIR`, quicker in its own
  bytes, and the two switches of each object's drawing (`L7_ED0E`).
- **The distances between objects** ("The frame rate"): bank 6's call of
  `L7_DAA7` calls `net_distances`, in bank 6's empty bytes.
- **The sprites' places** ("The frame rate"): the part of `L7_ED0E` that
  places each sprite ($EEDC-$EF65), the same bytes in fewer cycles.
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
what the tests compare (`tests/console.py`, `UNKEPT` and `UNKEPT_BITS`): the scratch and the
HUD's split at $00-$14, the link's zero page, the background's columns
and colours as far as they are drawn, which is as far as the queue of
writes to the PPU has had room for ($1A-$1C, $24-$26, $2A-$2B,
$0585-$058D, and the colours' buffer, $058E-$060D, which only the
filling of the queue reads), the PPU's and the banks' shadows ($F7-$FF), the stack, the
queue of writes to the PPU, the HUD's redraw, what the NMI last put in
place of a palette and the sprites' banks ($051B-$051C, $0525-$0528), the
most NMIs a pass took, the sound engine's memory, and $3E's bit 3: a
new palette for the NMI to upload, which the main thread sets and the
NMI clears, and which nothing else reads. Whether the NMI has cleared it
by the next read depends on the frames, and the late read once found the
two consoles apart on it as play began. The digest is of
the zero page the game keeps and of $0300-$04FF. A session's game was
checked against the game itself: its buttons, tick by tick, played into
the original ROM give the same game, for 1500 ticks.

## The frame rate

The game waited for much of its time. `DRAW_OBJECTS` ($EFD4), which fills
the sprites' page, began by waiting until no IRQ had come since the NMI,
so that it filled the page before the next NMI sent it to the PPU: a pass
that came to it after the HUD's IRQ, on line 29, waited for the next
frame. That was some 16% of the console's time in a fight, half a frame a
pass. The netplay ROM does not wait (`net_draw_begin`): an NMI that comes
while the page is being filled does not send it (`net_sprite_dma`), and
the sprites of the frame before stand for that frame, in some 23% of the
frames of a fight. A page is never shown later than the game alone would
have shown it: the game would have begun it no sooner, and it goes at the
first NMI after it is done. The game itself does not change, for nothing
of it depends on its frames' time. It is so with no session too, in
LOCAL GAME.

A session's exchange is some 2000 cycles at the line at 10, made once or
twice a pass of two frames or three. In the simulation, fighting at
random for 3000 frames from the game's start, 4 seeds (`drive.moves`, by
the frame), a session's line 10 ms each way; the game's frame rate is its
passes a second, 30 at most:

| Passes a second | seeds 1-4 | mean |
|---|---|---|
| The original, one player | 29.8, 29.8, 29.9, 29.7 | 29.8 |
| The original, two players | 21.0, 21.6, 21.4, 21.2 | 21.3 |
| A session: the first build (553889d, delay 2) | 21.0, 20.9, 20.8, 20.5 | 20.8 |
| The late read (cc7d77f, delay 1) | 20.5, 20.7, 20.4, 20.4 | 20.5 |
| No wait for the sprites' page (53ef13b) | 24.0, 24.5, 24.1, 24.1 | 24.2 |
| The banks | 23.9, 24.6, 24.2, 24.6 | 24.3 |
| The distances between objects | 24.6, 25.1, 24.7, 24.8 | 24.8 |
| The sprites' places | 26.2, 25.4, 25.7, 26.5 | 26.0 |

Buttons by the frame make each build play its own game, some 2% apart;
`tests/bench.py` (below) compares two builds more closely.

**The banks** are switched some 45 times a pass (`BANK_PAIR`, $FED1),
none of them to the pair already in: most are a call into another bank
and back. The netplay ROM's `BANK_PAIR` is quicker, some 61 cycles
against 80: it writes the shadows first, which an interrupt puts the
registers back from, and does not read A back from the stack. And the
drawing of each object (`L7_ED0E`) put in bank 3's pair and put back the
one it found, two switches an object: in the pass's drawing the pair is
put in once and put back after (`net_object_bank`, `net_object_back`,
`net_draw_end`). Together some 2% more ticks a second.

**The distances between objects** are worked out at the start of each
pass's objects (`L7_DAA7`): for each fighter (objects 0-3) that is on,
its distance to each other object, across, along and up, each held to
-128..127, and the first two's sizes added. `net_distances`
(`net/distances.inc`, in bank 6's empty bytes at $BE1F) keeps the same
bytes in fewer cycles: two fighters' pair is worked out once and kept
both ways (the other way is the same less, or $7F for $80 and $80 for
$7F past the ends), with no call and no stack for each. With four
fighters and six objects on, some 3,700 cycles against 4,550. Some 1.3%
more ticks a second. The
original and it were run on the same thousands of random states, edges
of the range weighted, to the same tables.

**The sprites' places**: of `L7_ED0E`'s work for each sprite, the most
was placing it: its offsets from the object made 16 bits by a byte set
to 0 and then decremented, added in a loop of two, and its line worked
out in five steps. The netplay ROM does the same in its own bytes, some
140 cycles a sprite against 230, to the same sprites' page and the same
bytes of its own: on the same game the pages of 630 passes were the same
as before. Some 4% more ticks a second.

Speed is measured by `tests/bench.py`: the tests' kind of session, but
with each console's buttons following its own tick from the session's
start, so that two builds play the same game tick for tick, which it
shows by the game's digest at the end. Buttons by the frame make a
quicker build play another game, which is as likely to be busier.

Of the work left, the most is a search of the area's table of the
ground (`L4_A379`, 11% of the console's time in a fight), which is the
game's own logic and so has to give the same bytes.

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

1. **Hardware, the rest**: the menu, the line at 10 against 14, and the
   HUD's split while a reply is asked again. Wi-Fi round trips of 40-90
   ms, seen in the nesp32's log in the first trial, still make the game
   wait at the ticks they fall on, as any lockstep game does. If the
   input is felt slow again on a calm network: wait for the other
   console's buttons in the main thread, between the HUD's IRQ and the
   one at the foot, so that a wait of a few milliseconds is not a frame.
2. **More of the game in a session**: the shops, the bosses, Slick and the
   ending, a password entered, and both players knocked out.
3. **The frame rate, more** (if wanted): the search of the ground's table
   (`L4_A379`, "The frame rate") is the most work left in a pass, some 2%
   to 5% to win, and is the game's logic, to be kept to the same bytes as
   the distances were. Two players are at some 26 passes a second against
   the game's 30 for one.
4. **A PAL console**: not yet tried. The late read counts its frames, and
   should hold at 50 a second, the game at 5/6 of its speed as the other
   netplay games are on one.
