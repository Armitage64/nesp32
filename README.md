# nesp32

One firmware for an M5Stack Stick on NES controller port 2, to serve every
application that uses one: fetching from the Internet, streaming sound,
two consoles playing one game. A ROM says which services it needs and the
Stick provides them; nothing is chosen on the Stick, and nothing about a
Stick is ever set up from a computer.

It is replacing the separate firmware and link protocol that each of
[nes-radar](../nes-radar), [nes-jukebox](../nes-jukebox),
[nes-wiki](../nes-wiki) and [nes-drmario](../nes-drmario) has, on the hat
and the wiring they share. NESpedia has moved to it, and the jukebox's ROM
has too, and plays on the same hardware. The jukebox's throughput test has
moved and runs there too. Dr. Mario's netplay has moved, and a full
network game has been played with it on hardware. The radar has not moved
yet.

![The status screen](docs/setup-status.png) ![Choosing a network](docs/setup-list.png)
![Typing a password](docs/setup-password.png) ![The link test](docs/setup-test.png)

## Status

Work in progress. **The setup ROM works on hardware:** a StickS3 on the
MiSTer's NES core, through a SNAC adapter. It found the Stick, joined a
Wi-Fi network from the controller, and the Stick joined it again by itself
after a power cycle. The link test ran 6000 requests with every one good,
and the Stick's slowest reply was 215 microseconds
([`firmware/README.md`](firmware/README.md), "On hardware"). **The
cartridge works on hardware too:** its menu and all five programs, on a
real NES and on the MiSTer, with a StickC Plus2 and with a StickS3. No
figures were taken from those runs.

| Part | State |
|---|---|
| The protocol ([`docs/PROTOCOL.md`](docs/PROTOCOL.md)) | version 1: frames, hello, and the services SYS, NET (Wi-Fi) and DIAG |
| The link and services in C (`firmware/components/`) | done; tested on a computer |
| The console's library (`nes/lib/`) | done; every read and write timed on py65 |
| The setup ROM (`nes/setup/`): status, Wi-Fi from the controller, link test | done; tested on a simulated console against the C code over a cycle-exact line |
| The Stick's firmware (`firmware/main/`): UART, Wi-Fi, screen | working on a StickS3 and on a StickC Plus2, with the MiSTer and with a real NES |
| A computer in place of a Stick (`host/serial_host.py`) | written, not run on a cable |
| WIKI, NESpedia's service: an HTTPS fetch, the text laid out in lines | working on a StickS3 with the NESpedia ROM ([nes-wiki](../nes-wiki)) |
| RAW: a run of bytes with framing off, at a rate of its own, either way | working on a StickS3 with the MiSTer: a run to the console as the jukebox's sampled sound, and runs of the pattern both ways with the throughput test's ROM ([nes-jukebox](../nes-jukebox/throughput)), to 298296 baud to the console and 223722 from it |
| JUKE, the jukebox's service: the playlist as a stream, the buttons, sampled sound through RAW | working on a StickS3 with the jukebox's ROM ([nes-jukebox](../nes-jukebox)) on the MiSTer; tested with that ROM on a simulated console |
| The nesp32's files: the jukebox's tracks, in LittleFS (`firmware/main/store.c`, `tools/put_files.py`) | working on a StickS3: tracks written over USB are found and played |
| PEER, for two consoles playing one game: a lobby, and a lockstep relay of buttons between two nesp32s over datagrams (`firmware/main/conn.c`), with advice to each console on the delay it keeps | tested with nes-drmario's netplay ROM ([nes-drmario](../nes-drmario)) and nes-contra's ([nes-contra](../nes-contra), whose exchange is a short frame) on two simulated consoles, the game the same on both; the firmware builds for both boards with it. On hardware both ROMs have played network games, a real NES among the consoles; nes-contra's `docs/Netplay.md` has the figures taken from its sessions |
| One cartridge (`nes/cart/`): the five programs and a menu, on an MMC1 | working on a real NES and on the MiSTer, with a StickC Plus2 and with a StickS3: the menu and every program. Tested on a simulated console: each program starts from the menu, and reset is the menu again |
| A service for the radar | a number reserved; not started |

NESpedia runs on it: a search typed on the console is fetched over HTTPS
and read, with the link answering throughout. The jukebox is the second
application: its ROM plays music and sampled sound from it, on the MiSTer
as on the simulated console.

## Building

Needs [cc65](https://cc65.github.io/) (`ca65`, `ld65`), a C compiler and
Python 3.

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
make            # build/setup.nes, and the firmware's code for this computer
make test       # about two and a half minutes
tools/preview.py docs    # the pictures above, from the ROM itself
```

`build/setup.nes` is NROM-256 (mapper 0). The Stick's firmware is built
with ESP-IDF, from `firmware/`.

## The cartridge

![The cartridge's menu](docs/cart-menu.png)

```sh
make cart       # build/nesp32.nes
```

One ROM with the jukebox, NESpedia, Dr. Mario's netplay, the throughput
test and setup, and a menu that is up at power-on: Up and Down, and A or
Start to run a program. Reset is the menu again. It wants checkouts of
[nes-jukebox](../nes-jukebox), [nes-wiki](../nes-wiki) and
[nes-drmario](../nes-drmario) beside this one, and builds each program with
its own Makefile, into `build/cart/`.

It is an MMC1 (mapper 1) with 256 KB of PRG and 128 KB of CHR ROM and no
memory, the mapper Dr. Mario has already. Set to 32 KB of PRG and 8 KB of
CHR, an MMC1 is an NROM to a program that never writes to it, so the four
NROM programs are on it as they were built, their serial routines on the
pages they were timed on. `nes/cart/gen_cart.py` has where everything is
and the few bytes that are not as built: six in each program's padding and
its reset vector, which make reset the menu.

The menu is in the last bank, which is the one an MMC1 has at `$C000` when
the power comes on. Emulators do that, and most of the chips; one that did
not would not start this cartridge.

## Music for the jukebox

The jukebox's tracks are files in the nesp32's flash, and go there over
USB:

```sh
pip install littlefs-python esptool
tools/put_files.py tracks/          # .jbs and .pcm files: the playlist, in name order
```

nes-jukebox makes the files and calls this itself (`tools/deploy.py`
there, from a directory of rips and recordings). The tool builds the whole
filing system on this computer and writes it over whatever tracks the
nesp32 had, so the files named are the playlist. There are 3968 KB for
them: a track of music is a few kilobytes, a minute of sampled sound 465
to 1220.

## The setup ROM

A Stick has no keyboard. This ROM is its setup: plug the Stick into
controller port 2, run the ROM, and use controller 1.

| Screen | Buttons |
|---|---|
| Status: the Stick, its firmware, its Wi-Fi, address, signal, battery | A: Wi-Fi setup. B: link test |
| Networks, strongest first, with a lock on those that want a password | Up, Down. A: choose. Select: look again. B: back |
| Keyboard, for a password (or the name of a network that hides it) | D-pad. A: type. B: delete. Select: `abc`, `ABC`, `#+=`. Start: join |
| Link test: a checked request every frame, and the Stick's time to reply | B: back |

Every printable character can be typed, and a password may be the full 63.
The Stick saves the network and joins it by itself from then on. The
password goes to the Stick and is never sent back.

## How it works

- **The console asks, the Stick answers.** Every exchange is one request
  and one reply, at 85227 baud, bit-banged by counting CPU cycles. A
  request names a service and an op. A request sent again gets the same
  reply again and is not acted on twice.
- **A ROM begins with a hello** that names the services it needs. The
  Stick starts those and stops the rest, so one firmware serves whatever
  cartridge is in.
- **The Stick never keeps the console waiting.** One task on a core of its
  own answers from what the services hold; joining a network, scanning and
  fetching are done by other tasks and asked after.
- **The same C runs on the Stick and under the tests.** The link and the
  services touch no hardware. Built for a computer, they answer the real
  ROM on a simulated console, over a line that models every bit.
- **What cannot wait for a frame goes outside the frames.** Sampled sound
  is a byte a sample at up to 223722 baud. The console and the nesp32
  agree to it in frames, and then the line is a run of bare bytes at that
  rate until the sound is over (RAW).

## What is where

| Path | Purpose |
|---|---|
| `proto/nesp.toml`, `tools/gen_proto.py` | the numbers both ends share, and the C, ca65 and Python files written from them |
| `docs/PROTOCOL.md` | the protocol |
| `firmware/components/nesp_core` | frames, CRC, services' registry |
| `firmware/components/nesp_services` | SYS, NET, DIAG, WIKI, RAW, JUKE and PEER, and the text code WIKI lays articles out with |
| `firmware/main` | the Stick: UART and link task, Wi-Fi, HTTPS fetches, the connection to another nesp32, files, screen and buttons |
| `tools/put_files.py` | puts the jukebox's tracks on a nesp32, over USB |
| `nes/lib/nesp.inc`, `nes/lib/gen_link.py` | the console's library, and its cycle-timed serial routines |
| `nes/setup/` | the setup ROM |
| `nes/cart/` | the cartridge: its menu, and the tool that puts the five programs on it |
| `host/nesp_host.c`, `host/nesp.py` | the firmware's code as a library for this computer, with a stand-in for the hardware |
| `host/serial_host.py` | that, on a USB serial cable in place of a Stick |
| `host/peer_net.py` | for it, PEER's connection to another nesp32 on this computer's sockets, and an opponent who never presses a button |
| `tests/console.py`, `tests/wire.py`, `tests/drive.py` | a console on py65, the serial line, and a hand on the controller |

## Tests

```sh
make test
```

- `test_core.py`: the C link and services, bytes in and bytes out.
- `test_link_timing.py`: every sample and every bit of the console's two
  receivers and its sender, at every phase and with the Stick's clock out.
- `test_link.py`: the ROM and the C code over the line: how soon and how
  late the Stick may answer, damaged and lost frames, a Stick switched off
  and on.
- `test_text.py`, `test_wiki.py`: an API reply to ASCII to lines of 28, and
  the WIKI service with the test in place of the Internet.
- `test_raw.py`: a run agreed, called off, sent and heard, with the test as
  the clock and the UART, and then on the simulated line at its own rate.
- `test_juke.py`: the playlist as a stream whatever is lost on the way,
  the buttons, and a sound handed to RAW, with the test as the console.
  The jukebox's ROM itself is run against this code in nes-jukebox's tests.
- `test_peer.py`: the lobby, the greetings and the relay of buttons, with
  the test as the network between two nesp32s. Dr. Mario's netplay ROM is
  run against this code, on two consoles, in nes-drmario's tests.
- `test_peer_net.py`: a computer's stand-in for that network, on real
  sockets on this machine.
- `test_put_files.py`: the image of the tracks that goes over USB.
- `test_setup.py`: every screen of the setup ROM worked with the
  controller, to a network joined with a password of every character.
- `test_cart.py`: the cartridge on a console with its mapper: every
  program on it as built, started from the menu, and left by reset. It
  skips without the other programs' checkouts.

The ROM tests need cc65 and skip without it.

## Not done

- A long run, and figures from a real NES and from the StickC Plus2: both
  work, with the cartridge, and nothing was measured.
- Why the network between two nesp32s is slower for the first eight to
  ten seconds after they connect than it is from then on (`docs/PROTOCOL.md`,
  "The delay"). nes-drmario's README has the figures from its games on two
  consoles, with nes-contra's exchange and a delay that sets itself.
- The receiving nesp32 woken when a packet comes, in place of looking once
  a millisecond; and a way for two nesp32s to meet across the Internet
  without a port forwarded.
- The service the radar needs, and its ROM moved to it. NESpedia's, the
  jukebox's and Dr. Mario's netplay are done.
- A fetch that drops partway is not made again; what came is read, if it
  was a screenful.
- Updates over Wi-Fi, and a way to put music on a Stick without a cable.
- PAL consoles.
- A licence. A line-by-line comparison found no code of nes-radar's
  (GPL-3.0) here beyond idioms; the rest descends from nes-jukebox, nes-wiki
  and nes-drmario, which have none yet. The CRC routine without a table
  follows Greg Cook's on 6502.org, whose terms have not been checked.
