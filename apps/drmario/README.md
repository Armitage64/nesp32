# Dr. Mario, two consoles

A disassembly of Dr. Mario (NES) and a netplay build of it: a two-player
game split over two consoles, each with an M5Stack Stick on controller
port 2 (the nes-jukebox interface), the Sticks joined over Wi-Fi.

**Status: a working prototype.** A full two-player game has been played
between two real consoles on one Wi-Fi network, one with a StickC Plus2 and
one with a computer on the USB serial cable (`host/drnet_host.py`), at full
speed and with both screens the same throughout. Not yet tried: two
Sticks, and anything beyond a local network.

On the title, choose **2 PLAYER GAME**. The console then asks how:

- **HOST GAME**: the Stick waits for the other one. The console and the
  Stick's screen both show the address player 2 has to enter.
- **JOIN GAME**: edit the address (Left/Right to move, Up/Down to change a
  digit) and press Start. It starts as the address last joined, or this
  Stick's own.
- **LOCAL GAME**: two controllers on this console, as the original.

```sh
make            # build/drmario.nes (the original) and build/drmario_net.nes
make verify     # the original still matches its SHA-1
make test       # needs: python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

Needs cc65 (`ca65`, `ld65`) and Python 3.

## What is where

| Path | Purpose |
|---|---|
| `bank_FF.asm`, `bank_ram.inc`, `bank_val.inc` | the disassembly. Everything netplay changes is under `.ifdef NETPLAY` |
| `net/net.inc` | ticks, stalls and lags; the buttons' rings; a session's exchange |
| `net/exchange.inc`, `net/session.inc` | one exchange with the Stick; starting and ending a session |
| `net/menu.s`, `net/menu.cfg` | the menu, in a second PRG bank of its own |
| `tools/gen_link.py` | writes the cycle-timed serial routines and the link's constants (`build/link.inc`) |
| `tools/prepare.py` | strips the disassembly's left-hand columns for ca65 (a port of `preparations.lua`) |
| `firmware/stick/drnet/linkrate.py` | the numbers both ends share |
| `firmware/stick/drnet/stick.py`, `session.py` | the Stick's answers to the menu and its side of a session; plain Python, and what the tests run |
| `firmware/stick/drnet/net.py`, `device.py`, `ui.py`, `board.py` | Wi-Fi and sockets, the main loop, the screen, the pins (UIFlow only; untested) |
| `firmware/stick/tools/` | `deploy.sh` and friends, from nes-wiki |
| `host/drnet_host.py`, `host/desktop.py` | a computer in place of a Stick, on the USB serial cable |
| `tests/console.py`, `tests/wire.py`, `tests/netplay.py` | a console on py65, the serial line, and two consoles with a network between |
| `docs/PROTOCOL.md` | the link protocol, and how the two games are kept the same |

`assemble.bat`, `assemble.sh` and `preparations.lua` are the disassembly's
own build, for Windows; the Makefile replaces them here.

## Where the netplay code sits

The cartridge is full. The session's code takes space the game does not
use: 512 bytes of padding before `$FD00`, the sample data at `$FD00` (the
game never plays a sample), and the padding after the reset code. The menu
did not fit there, so the netplay ROM has a second 32 KB PRG bank for it
(docs/PROTOCOL.md, "The cartridge"). It needs a flashcart or an emulator.

## The Stick

The hat and the pins are nes-jukebox's. With UIFlow 2.0 on the Stick and
Wi-Fi saved in it (M5Burner, or `firmware/stick/tools/set_wifi.py`):

```sh
firmware/stick/tools/deploy.sh        # or: deploy.sh -p /dev/cu.usbserial-XXXX
```

The Sticks talk over TCP port 6502. On one network that needs nothing
more. Across the Internet the hosting side has to forward that port to its
Stick, and player 2 enters the host's public address.

## A computer in place of a Stick

With nes-radar's 5 V USB serial cable on controller port 2 instead of a
Stick, a computer answers the console with the Stick's own code:

```sh
.venv/bin/python host/drnet_host.py /dev/cu.usbserial-XXXX          # hosts or joins, as a Stick
.venv/bin/python host/drnet_host.py /dev/cu.usbserial-XXXX --idle   # no other console needed
```

A computer and a Stick can be the two ends of a session. With `--idle`,
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
  8100 of 29780 CPU cycles with a Stick that answers in 1 ms, and the
  busiest frame of a two-player game (about 25900 cycles without the
  link) still ends before the next NMI.
- **A fixed input delay of 3 frames is a local network's.** Full speed
  with 10 ms between the Sticks, about three quarters with 40 ms, about
  half with 90 ms. The game slows down and does not break.
- **The game never plays a sample**, so nothing takes cycles from the
  bit-banged serial routines, and the sample data's space is free.
- **The disassembly's edit mode** (`con_bzk_hack`) skips the copy
  protection's checksum, which is a frame of work at the title. The
  netplay ROM is one frame ahead of the original from there, and
  otherwise plays the same.

From hardware (a real NES with a flashcart, a StickC Plus2, an FT232 cable
on a Mac):

- **The 64 KB ROM runs from a flashcart**, menu bank and all.
- **A computer on the USB serial cable answers in time** at 85227 baud
  with the driver asked for 1 ms of receive latency: 4 requests repeated
  in 4500 against the idle opponent, at 60 ticks a second.
- **Two consoles on one Wi-Fi network played a full game** at full speed,
  the same on both screens. The joining side (the computer) repeated 25
  requests in 4200, most of them frames spent waiting for the other
  console's buttons: about one frame's wait every three seconds.
- **The ESP32's UART driver refuses a transmit buffer of 128 bytes or
  less** (`ESP_FAIL`), however little is sent. nes-wiki's is 144 and
  never met this.
- **The Stick's protocol code has to be MicroPython's Python.** It ran
  under CPython in every test and on the computer, and then failed on the
  Stick at `del` of a bytearray's slice, which MicroPython does not have
  (nor `bytes.ljust`). The tests cannot see this until they run that code
  under MicroPython as well.
- **A Stick that fails mid-session takes both consoles back to the title**
  within seconds, as designed: one by its Stick's silence, the other by
  the lost connection.

## To do

- **Two Sticks**, when the second arrives: the case this is for. A Stick
  is slower to answer than a computer, so its repeats are the thing to
  watch (the LINK row on its screen, and its log).
- **Run the Stick's protocol code under MicroPython in the tests** (the
  Unix port: `brew install micropython`).
- **An input delay chosen for each session** from the time the Sticks
  measure between them, in place of the fixed 3 frames. Needed before
  the Internet is worth trying.
- **The Internet**: the host forwards TCP port 6502 today. A relay, or
  UDP with each packet carrying the last few ticks, would do better than
  TCP when packets are lost.
- **Check that the Stick turned Wi-Fi power saving off.** Its log says at
  startup if the radio refused. If it did, stalls of up to a beacon
  (100 ms) are to be expected.
- **A check that the games are still the same**: a sum of the game's
  memory exchanged every so often, so that a difference is reported and
  not just seen.
- **Say why on the console** when a session ends (the other console left,
  the Stick went quiet); it only goes back to the title now.
- **The menu**: held buttons do not repeat in the address editor, and its
  colours and layout have only been looked at once.
- **MiSTer**: whether its NES core can put the link's two lines (OUT0 and
  D0 of controller port 2) on a SNAC adapter.
- **An idle opponent on the Stick**, as the computer has, to test one
  console with a Stick alone.
- **The music stops in a stall.** The sound engine runs once a tick; it
  could run once a frame.
- PAL is not considered anywhere.

## Known limits

- The input delay is fixed at 3 frames, which suits a local network. In
  simulation the game ran at full speed with 10 ms between the Sticks, at
  about three quarters with 40 ms and at about half with 90 ms. It slows
  down rather than breaks.
- A button press shorter than a stall is not seen.
- The music stops with the game during a stall.
