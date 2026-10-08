# Dr. Mario, two consoles

A disassembly of Dr. Mario (NES) and a netplay build of it: a two-player
game split over two consoles, each with a nesp32 on controller port 2, the
nesp32s joined over Wi-Fi. The nesp32 is an M5Stack Stick with
[nesp32](../nesp32)'s firmware, the one firmware for every ROM that uses
one; this ROM asks it for its PEER service.

**Status: a proof of concept that works.** It has moved to nesp32, and a
full network game has been played with it on hardware, with the music as
it should be, from an Everdrive N8 on a real NES among the consoles. On two
simulated consoles, with nesp32's own link and services between them, the
menu hosts and joins and a game plays at full speed, the same on both
screens throughout (`make test`). The prototype this replaces, with a
MicroPython firmware and a protocol of its own, is gone from here, and the
ROM no longer speaks to it.

On the title, choose **2 PLAYER GAME**. The console then asks how:

- **HOST GAME**: the nesp32 waits for the other one. The console and the
  nesp32's screen both show the address player 2 has to enter.
- **JOIN GAME**: edit the address (Left/Right to move, Up/Down to change a
  digit) and press Start. It starts as the address last joined, or this
  nesp32's own.
- **LOCAL GAME**: two controllers on this console, as the original.

```sh
make            # build/drmario.nes (the original) and build/drmario_net.nes
make verify     # the original still matches its SHA-1
make test       # needs: python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

Needs cc65 (`ca65`, `ld65`), Python 3, and for the netplay ROM a checkout
of [nesp32](../nesp32) beside this one (or `NESP32=` where it is) and a C
compiler: the link's library for the console comes from there, and the
tests build its firmware's link and services for this computer. They take
about six minutes.

## What is where

| Path | Purpose |
|---|---|
| `bank_FF.asm`, `bank_ram.inc`, `bank_val.inc` | the disassembly. Everything netplay changes is under `.ifdef NETPLAY` |
| `net/net.inc` | ticks, stalls and lags; the buttons' rings; a session's exchange; the way to the menu |
| `net/session.inc` | starting and ending a session |
| `net/menu.s` | the menu, in a second PRG bank of its own: the hello, and PEER's lobby |
| `net/common.inc`, `net/ram.inc` | a session's numbers, the code both banks share, and the memory they share |
| `net/game.cfg`, `net/menu.cfg` | where each bank's code goes, and the link library's memory, the same in both |
| `tools/prepare.py` | strips the disassembly's left-hand columns for ca65 (a port of `preparations.lua`) |
| `tests/console.py`, `tests/wire.py`, `tests/netplay.py` | a console on py65, the serial line, and two consoles with their nesp32s and a network between |
| `docs/PROTOCOL.md` | how the two games are kept the same, and what the ROM asks of PEER |

The link itself is nesp32's: its `docs/PROTOCOL.md` has the line, the
frames and the PEER service, `nes/lib/nesp.inc` there is the library both
banks include, and `firmware/` there is what runs on the nesp32.

`assemble.bat`, `assemble.sh` and `preparations.lua` are the disassembly's
own build, for Windows; the Makefile replaces them here.

## Where the netplay code sits

The cartridge is full. The session's code and the link's library take
space the game does not use: 512 bytes of padding before `$FD00`, the
sample data at `$FD00` (the game never plays a sample), and the padding
after the reset code. About 120 bytes of that are left. The menu did not
fit there, so the netplay ROM has a second 32 KB PRG bank for it
(docs/PROTOCOL.md, "The cartridge"). It needs a flashcart or an emulator.

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
cd ../nesp32
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
  8500 of 29780 CPU cycles with a nesp32 that answers in 0.2 ms, and the
  busiest frame of a two-player game still ends before the next NMI, at
  about 27400.
- **A fixed input delay of 3 frames is a local network's.** Full speed
  with 10 ms between the nesp32s, about three quarters with 40 ms, under
  half with 90 ms. The game slows down and does not break.
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

- **Figures from a network game on hardware**: `waiting` on a nesp32's
  screen counts the frames its console brought it nothing new, against
  `frames`. Those are the stalls, which the picture still shows, and how
  many there are says whether the input delay suits the network.
- **Less input delay.** Both consoles use their own buttons 3 frames
  late, host and guest alike (measured on the simulated consoles: a press
  moves the pill 3 frames later than in a local game, on both screens).
  That is a fixed margin, not what a network needs. For later, the most
  worthwhile first:
  - **Ask later in the frame.** The console asks for the other's buttons
    once a frame, right after its NMI, so buttons that reach its nesp32 a
    moment later wait there most of a frame. Asked for again when the main
    loop is done, with the library's other receiver, they would not, and 2
    frames should then do on one network where 3 do now. The firmware
    needs no change; the game's bank has about 120 bytes for it.
  - **An input delay that sets itself**, as nes-contra's does, in place of
    the fixed 3 frames. The firmware has it all now: the delay to begin
    with comes as a sixth byte of PEER's lobby replies, from the time the
    nesp32s measure between them, and during a game each console reports
    on the other's buttons and is advised a tick longer or shorter
    (nesp32's `docs/PROTOCOL.md`, "The delay"). What is left is the ROM's
    side: the delay as a variable, the report and the advice in the
    exchange, and a read repeated or let go by when it changes. nes-contra's
    `net/net.inc` is the pattern. Needed before the Internet is worth
    trying.
  - **A steadier way between the nesp32s**, since the margin is there for
    the spikes: ESP-NOW
    for two consoles in one room, past the access point; the receiving
    nesp32 woken by what comes instead of looking once a millisecond.
  - **A faster exchange.** The line runs three times faster than the
    link's rate (nes-jukebox's throughput test), which is about 1.5 ms of
    every exchange.
  - **No delay at all on a player's own bottle.** The two bottles only
    meet in the garbage, the win and the pause. Each console could run
    its own player at once and the other's a few frames behind, with the
    garbage sent as events. That is another way of stepping the game, not
    a change to the protocol, and wants the second bank for its code.
    Rolling back, as newer games do, is not for this one: a frame is
    nearly all used already.
- **The Internet**: the host forwards UDP port 6502 today. A relay would
  spare that.
- **A check that the games are still the same**: a sum of the game's
  memory exchanged every so often, so that a difference is reported and
  not just seen.
- **Say why on the console** when a session ends (the other console left,
  the nesp32 went quiet); it only goes back to the title now.
- **The menu**: held buttons do not repeat in the address editor, and its
  colours and layout have only been looked at once.
- **An idle opponent on the nesp32**, as the computer has, to test one
  console with a nesp32 alone.
- PAL is not considered anywhere.

## Known limits

- The input delay is fixed at 3 frames, which suits a local network. In
  simulation the game ran at full speed with 10 ms between the nesp32s,
  at about three quarters with 40 ms and at under half with 90 ms. It
  slows down rather than breaks.
- A button press shorter than a stall is not seen.
- In a stall the picture stands still, and a sound the game asks for is
  heard when it asks, which is a tick's time and not a frame's.
