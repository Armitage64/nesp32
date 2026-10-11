# Dr. Mario, two consoles

A netplay build of Dr. Mario (NES): a two-player game split over two
consoles, each with a nesp32 on controller port 2, the
nesp32s joined over Wi-Fi. The nesp32 is an M5Stack Stick with
[nesp32](../..)'s firmware, the one firmware for every ROM that uses
one; this ROM asks it for its PEER service.

**Status: a proof of concept that works.** It has moved to nesp32, and a
full network game has been played with it on hardware, with the music as
it should be, from an Everdrive N8 on a real NES among the consoles. On two
simulated consoles, with nesp32's own link and services between them, the
menu hosts and joins and a game plays at full speed, the same on both
screens throughout (`make test`).

The exchange is now nes-contra's: made before the game's work, in short
frames, with an input delay that sets itself (1 frame on a quick network,
where it was always 3) and a check that the two games are still the same.
A game has been played with it on hardware too, at a delay of 1: it
answers to the buttons at once, and does not slow ("What has been
learned").

On the title, choose **2 PLAYER GAME**. The console then asks how:

- **HOST GAME**: the nesp32 waits for the other one. The console and the
  nesp32's screen both show the address player 2 has to enter.
- **JOIN GAME**: edit the address (Left/Right to move, Up/Down to change a
  digit) and press Start. It starts as the address last joined, or this
  nesp32's own.
- **LOCAL GAME**: two controllers on this console, as the original.

**The game is not in this repository.** What is here is the netplay code,
its tests, and a few lines to be put into the game's own code. The rest,
the game's code and its graphics, is the `Dr. Mario` directory of
[NES-Games-Disassembly](https://github.com/cyneprepou4uk/NES-Games-Disassembly),
cyneprepou4uk's disassemblies, a submodule at
`third_party/NES-Games-Disassembly`.

```sh
git submodule update --init third_party/NES-Games-Disassembly
make            # build/drmario.nes (the original) and build/drmario_net.nes
make verify     # the original still matches its SHA-1
make test       # needs: python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

Needs cc65 (`ca65`, `ld65`), Python 3, `patch`, and for the netplay ROM
[nesp32](../..), the top of this repository (or `NESP32=` where it is), and a C
compiler: the link's library for the console comes from there, and the
tests build its firmware's link and services for this computer. They take
about six minutes.

## What is where

| Path | Purpose |
|---|---|
| `patches/` | the lines that call the netplay code, for the disassembly's `bank_FF.asm` and `bank_val.inc`. All are under `.ifdef NETPLAY` |
| `net/net.inc` | the game's bank: ticks, stalls and lags, starting a session, and the way to the menu's bank |
| `net/session.inc` | a session's frame, in the menu's bank: the buttons' rings, the delay, the exchange and the check |
| `net/menu.s` | the menu, in a second PRG bank of its own: the hello, and PEER's lobby |
| `net/common.inc`, `net/ram.inc` | a session's numbers, the code both banks share, and the memory they share |
| `net/game.cfg`, `net/menu.cfg` | where each bank's code goes, and the link library's memory |
| `tools/prepare.py` | strips the disassembly's left-hand columns for ca65 (a port of its `preparations.lua`) |
| `tests/console.py`, `tests/wire.py`, `tests/netplay.py` | a console on py65, the serial line, and two consoles with their nesp32s and a network between |
| `docs/PROTOCOL.md` | how the two games are kept the same, and what the ROM asks of PEER |

The link itself is nesp32's: its `docs/PROTOCOL.md` has the line, the
frames and the PEER service, `nes/lib/nesp.inc` there is the library the
menu's bank includes, and `firmware/` there is what runs on the nesp32.

## Changing the game's code

The build copies what it needs of the disassembly to `build/upstream` and
applies `patches/` there; the submodule is never written to. To change
what netplay adds to the game's own files, edit the copies in
`build/upstream`, then

```sh
make patches    # patches/ again, from build/upstream
```

A patch is made with no context, so it holds our lines and where they go
and none of the disassembly. That is why the submodule is kept at one
commit (`DRMARIO_COMMIT` in the Makefile): the patches are line numbers in
that commit's files. `make clean` will not delete a `build/upstream` that
has changes `patches/` has not.

## Where the netplay code sits

The cartridge is full, so the netplay ROM has a second 32 KB PRG bank
(docs/PROTOCOL.md, "The cartridge"). The menu is there, and so is a
session's frame with the link's library and its table: the game's NMI goes
to that bank and back once a frame, about 110 cycles for the two changes.
What is left in the game's bank is small, and sits in the 512 bytes of
padding before `$FD00`. The sample data after it (the game never plays a
sample) is left out and its two pages are empty. It needs a flashcart or
an emulator.

## The nesp32

The hat and the pins are nes-radar's, as for every ROM that uses a nesp32.
Flash nesp32's firmware (`firmware/README.md` there) and join a Wi-Fi
network from the controller with its setup ROM, once: the nesp32 keeps the
network and joins it by itself from then on. Nothing is set up from a
computer, and nothing is chosen on the nesp32: this ROM says what it is
when its menu opens.

The nesp32s talk over UDP port 6502. On one network that needs nothing
more. Across the Internet the hosting side has to forward that port to its
nesp32, and player 2 enters the host's public address.

## A computer in place of a nesp32

With nes-radar's 5 V USB serial cable on controller port 2 instead of a
nesp32, a computer answers the console with the firmware's own code
(nesp32's `host/serial_host.py`, after `make host` there):

```sh
cd ../..
.venv/bin/python host/serial_host.py /dev/cu.usbserial-XXXX --game   # hosts or joins, as a nesp32
.venv/bin/python host/serial_host.py /dev/cu.usbserial-XXXX --idle   # no other console needed
```

A computer and a nesp32 can be the two ends of a session. With `--idle`,
HOST GAME starts a game at once against an opponent who never presses a
button, which is the first thing to try on one console.

## What has been learned

From the simulation:

- **The game's NMI changes the game's state** (it draws a row of a bottle
  and counts it off), and always runs, whether or not the main loop has
  finished the frame. Left alone, a frame that ran long on one console
  only would make the two games differ. So in a session an NMI that finds
  the main loop still at work does nothing at all, and the game depends
  only on how many ticks there have been.
- **There is room in a frame.** A tick's NMI with its exchange is about
  6300 of 29780 CPU cycles with a nesp32 that answers in 0.2 ms, where it
  was 8500 with PEER's ordinary frames. The exchange is about 3500 of
  that, with the controller's read and the way to the menu's bank and
  back. In 1500 frames of play 99 in 100 ended by 22800, and the busiest
  at 27400.
- **The delay finds its own level.** On a network that takes 5 or 7 ms to
  cross, a session begins with a delay of 1 frame and no frame waits for
  buttons, wherever one console's frames fall in the other's. From 8 ms the
  nesp32s advise 2, and at 10 to 12 ms a session at 2 waited 11 frames
  in 600 at the worst and none as a rule; at 35 ms they advise 3.
  Begun a frame too short, both consoles are at the delay the network
  needs within 500 frames; begun a frame too long, within 1300. The game
  is the same on both throughout. On a network of 150 ms or more both go to 5, and the game
  waits.
- **The game reads its controllers in its NMI**, after its writes to the
  PPU and before its main loop goes on. So the exchange could go ahead of
  the game's work with no rearrangement: it is made where the game reads,
  and an NMI that has no buttons for its tick ends there, to be taken up
  from there in the next frame.
- **The game never plays a sample**, so nothing takes cycles from the
  bit-banged serial routines, and the sample data's space is free.
- **The disassembly's edit mode** (`con_bzk_hack`) skips the copy
  protection's checksum, which is a frame of work at the title. The
  netplay ROM is one frame ahead of the original from there, and
  otherwise plays the same.

From hardware, with nesp32's firmware:

- **The network game works**: hosted, joined, and a full game played. No
  figures were taken.
- **The music sped up and slowed down** in a network game, and not in a
  local one. The game runs its sound engine once for each pass of its main
  loop, which in a session was once a tick, so every frame spent waiting
  for the other console's buttons held the music back. The engine now runs
  once in every frame of a session, from the NMI (docs/PROTOCOL.md, "The
  music"), and the music has since been heard to keep its time through a
  full game.
- **The first try on the Everdrive N8 gave a white screen**, and the next
  build ran. The one change between them was an NES 2.0 header in place of
  the iNES one, which the MiSTer's core had warned about; everything that
  runs before the title was the same in both, so the card or the cart may
  as well have been the cause.

From hardware, with the exchange as it is now: two consoles on one home
network, a StickS3 on the one that hosted and a StickC Plus2 on the one
that joined, and the figures from the nesp32s' logs (nesp32's
`firmware/deploy.sh watch`) over 7900 frames.

- **It plays at a delay of 1 frame on both consoles**, and feels it: the
  pill answers at once, and nothing slows.
- **60 frames in 7967 waited for buttons on one console and 65 in 7852 on
  the other**, under one in a hundred. The network took 3 to 5 ms there
  and back as a rule, over 14 ms for 199 packets in 15506 and over 40 ms
  for 29, and 148 ms at the worst. The waiting is those.
- **No reply was misheard**, in over 5000 on each console: the short
  frames and the change of bank in every frame are sound on real
  hardware. The nesp32s answered in 90 and 150 microseconds, 358 at the
  slowest.
- **The console that joined began at a delay of 4**, and was at 1 after
  about a minute, a frame shorter every 17 seconds or so. The nesp32 took
  the delay to begin with from a mean of the network's time as the two
  connected, and one slow packet then was enough to set it long. It takes
  the quickest time now, and a session's first report, a second or two
  in, sets the delay outright from what the game's own packets have taken
  (nesp32's `docs/PROTOCOL.md`, "The delay").
- **With that firmware a session begins at 1, goes to 2 within two
  seconds and is back at 1 about half a minute in**, in each of two games.
  The network is slower for the first eight to ten seconds after the two
  nesp32s connect, three packets in ten over 14 ms there and back where
  one in twenty or thirty are after it, and the delay follows that. Why
  it is slower then is not known. In the second of those games, 5500
  frames, 27 frames waited on one console and 36 on the other, and no
  reply was misheard.
- **A session of 35 minutes**, 127800 frames and the game played through
  twice: one frame in 75 waited, two replies were misheard on the one
  console whose count was kept to the end, and the delay was 1 for most
  of it, 2 for 17 seconds at a time when more than one packet in ten
  called for it, and 3 and 4 for a while on a network at its worst.

From hardware, with the prototype's own firmware and protocol (a real NES
with a flashcart, a StickC Plus2 on MicroPython, an FT232 cable on a Mac).
None of it has been measured again since the move to nesp32:

- **The 64 KB ROM runs from a flashcart**, menu bank and all.
- **A computer on the USB serial cable answers in time** at 85227 baud
  with the driver asked for 1 ms of receive latency: 4 requests repeated
  in 4500 against the idle opponent, at 60 ticks a second.
- **Two consoles on one Wi-Fi network played a full game** at full speed,
  the same on both screens. The joining side (the computer) repeated 25
  requests in 4200, most of them frames spent waiting for the other
  console's buttons: about one frame's wait every three seconds.
- **One end that fails mid-session takes both consoles back to the title**
  within seconds, as designed: one by its own end's silence, the other by
  the lost connection.

## To do

- **A steadier way between the nesp32s**, since what is left of the
  waiting is the network's spikes (nes-contra's `docs/Netplay.md`, "On
  hardware"): ESP-NOW for two consoles in one room, past the access point;
  the receiving nesp32 woken by what comes instead of looking once a
  millisecond.
- **A faster exchange.** The line runs three times faster than the link's
  rate (nes-throughput's test), which is about 1.5 ms of every
  exchange. And no wait for a reply in a frame whose buttons from the
  other console are already here.
- **No delay at all on a player's own bottle.** The two bottles only meet
  in the garbage, the win and the pause. Each console could run its own
  player at once and the other's a few frames behind, with the garbage
  sent as events. That is another way of stepping the game, not a change
  to the protocol; the second bank has room for its code. Rolling back, as
  newer games do, is not for this one: there is nowhere to keep a copy of
  the game.
- **The Internet**: the host forwards UDP port 6502 today. A relay would
  spare that. The delay will be what the distance makes it.
- **Say why on the console** when a session ends (the other console left,
  the nesp32 went quiet, the games differed); it only goes back to the
  title now.
- **The menu**: held buttons do not repeat in the address editor, and its
  colours and layout have only been looked at once.
- **An idle opponent on the nesp32**, as the computer has, to test one
  console with a nesp32 alone.
- PAL is not considered anywhere.

## Known limits

- Both consoles must run this build: the nesp32s tell an older one from
  it, and will not join the two.
- The input delay is 1 to 5 frames, each console's own, as its nesp32
  advises. A network slower than 5 frames covers slows the game rather
  than breaks it.
- A button press shorter than a stall is not seen.
- In a stall the picture stands still, and a sound the game asks for is
  heard when it asks, which is a tick's time and not a frame's.
