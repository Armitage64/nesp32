# Building and testing nesp32

What is in the repository, how to build it, what the tests cover, and how
far each part has got. The [README](../README.md) has what the nesp32 is.

## Building

Needs [cc65](https://cc65.github.io/) (`ca65`, `ld65`), a C compiler and
Python 3.

```sh
git submodule update --init    # for the two games and nes-radar only
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
make            # build/setup.nes, and the firmware's code for this computer
make cart       # build/nesp32.nes: the cartridge
make test       # about three and a half minutes
```

The nesp32's firmware is built with ESP-IDF, from `firmware/`
([its README](../firmware/README.md)). Each program in `apps/` has a
Makefile and a README of its own.

Three programs are other people's, and are not in this repository: only
what puts each on the link, and the few lines that call it, as patches.
Their code is in submodules in `third_party/`, kept at the commits the
patches were made for. Two are games with netplay, from disassemblies:
[nes-contra-us](https://github.com/vermiceli/nes-contra-us), vermiceli's,
for [nes-contra](../apps/contra), and
[NES-Games-Disassembly](https://github.com/cyneprepou4uk/NES-Games-Disassembly),
cyneprepou4uk's, for [nes-drmario](../apps/drmario). Contra's build also needs a copy of the game, which whoever
builds it supplies. The third is [nes-radar](https://github.com/k6lcm/nes-radar),
k6lcm's, for [nes-radar](../apps/nes-radar): its ROM's source, and its
server's code, which the tests of the firmware's RADAR service run beside
it. Nothing else here needs any of them, and none of the three is on the
cartridge.

## The cartridge

![The cartridge's menu](cart-menu.png)

One ROM with the jukebox, NESpedia, the throughput test and setup, and a
menu that is up at power-on: Up and Down, and A or Start to run a program.
Reset is the menu again. It is built from [nesp32 Setup](../apps/setup),
[nes-jukebox](../apps/jukebox), [nes-wiki](../apps/wiki) and
[nes-throughput](../apps/throughput) in `apps/`,
each program with its own Makefile, into `build/cart/`.

It is an MMC1 (mapper 1) with 256 KB of PRG and 128 KB of CHR ROM and no
memory. Set to 32 KB of PRG and 8 KB of CHR, an MMC1 is an NROM to a
program that never writes to it, so the four programs, each an NROM, are
on it as they were built, their serial routines on the
pages they were timed on. `nes/cart/gen_cart.py` has where everything is
and the few bytes that are not as built: six in each program's padding and
its reset vector, which make reset the menu.

The menu is in the last bank, which is the one an MMC1 has at `$C000` when
the power comes on. Emulators do that, and most of the chips; one that did
not would not start this cartridge.

## How far each part has got

| Part | State |
|---|---|
| The protocol ([`PROTOCOL.md`](PROTOCOL.md)) | version 1: frames, hello, and the services SYS, NET (Wi-Fi) and DIAG |
| The link and services in C (`firmware/components/`) | done; tested on a computer |
| The console's library (`nes/lib/`) | done; every read and write timed on py65 |
| The setup ROM ([nesp32 Setup](../apps/setup)): status, Wi-Fi from the controller, link test, the USB drive | done; tested on a simulated console against the C code over a cycle-exact line |
| The Stick's firmware (`firmware/main/`): UART, Wi-Fi, screen | working on a StickS3 and on a StickC Plus2, with the MiSTer and with a real NES |
| A computer in place of a Stick (`host/serial_host.py`) | written, not run on a cable |
| WIKI, NESpedia's service: an HTTPS fetch, the text laid out in lines | working on a StickS3 with the NESpedia ROM ([nes-wiki](../apps/wiki)) |
| RAW: a run of bytes with framing off, at a rate of its own, either way | working on a StickS3 with the MiSTer: a run to the console as the jukebox's sampled sound, and runs of the pattern both ways with the throughput test's ROM ([nes-throughput](../apps/throughput)), to 298296 baud to the console and 223722 from it |
| JUKE, the jukebox's service: the playlist as a stream, the buttons, sampled sound through RAW | working on a StickS3 with the jukebox's ROM ([nes-jukebox](../apps/jukebox)) on the MiSTer; tested with that ROM on a simulated console |
| The nesp32's files: the jukebox's tracks, in a FAT filing system (`firmware/main/store.c`, `tools/put_files.py`), with rips of games' music (`.vgm`, `.vgz`) made playable on the nesp32 itself (`firmware/components/nesp_services/vgm.c`) | builds for both boards, and the converter makes the same files as nes-jukebox's on a computer; not yet run on hardware. Before this the files were in LittleFS, and that worked on a StickS3 |
| A StickS3 as a USB drive, for music to be copied to (`firmware/main/usb.c`, the setup ROM's USB screen) | builds, and the ROM's screen is tested on a simulated console; not yet run on hardware |
| PEER, for two consoles playing one game: a lobby, and a lockstep relay of buttons between two nesp32s over datagrams (`firmware/main/conn.c`), with advice to each console on the delay it keeps | tested with nes-drmario's netplay ROM ([nes-drmario](../apps/drmario)) and nes-contra's ([nes-contra](../apps/contra), whose exchange is a short frame) on two simulated consoles, the game the same on both; the firmware builds for both boards with it. On hardware both ROMs have played network games, a real NES among the consoles; nes-contra's `docs/Netplay.md` has the figures taken from its sessions |
| One cartridge (`nes/cart/`): the four programs and a menu, on an MMC1 | working on a real NES and on the MiSTer, with a StickC Plus2 and with a StickS3: the menu and every program. Tested on a simulated console: each program starts from the menu, and reset is the menu again |
| RADAR, NES Radar's service: an airport by its letters, and the aircraft round it from adsb.fi as scenes of the nearest eight (`firmware/components/nesp_services/radar.c`), with where the airport is asked of Wikidata and the last one kept in flash | tested with nes-radar's ROM as [nes-radar](../apps/nes-radar) builds it for the link, on a simulated console, and its scenes held to the bytes nes-radar's own server makes; the firmware builds for both boards with it. Not yet run on hardware |

## What is where

| Path | Purpose |
|---|---|
| `proto/nesp.toml`, `tools/gen_proto.py` | the numbers both ends share, and the C, ca65 and Python files written from them |
| `docs/PROTOCOL.md` | the protocol |
| `firmware/components/nesp_core` | frames, CRC, services' registry |
| `firmware/components/nesp_services` | SYS, NET, DIAG, WIKI, RAW, JUKE, PEER and RADAR, and the text code WIKI lays articles out with |
| `firmware/main` | the Stick: UART and link task, Wi-Fi, HTTPS fetches, the connection to another nesp32, files, screen and buttons |
| `tools/put_files.py` | puts the jukebox's tracks on a nesp32, over USB, for a board that cannot be a drive |
| `tools/lcd.py` | pictures of the nesp32's own screen, for trying a layout before flashing it |
| `nes/lib/nesp.inc`, `nes/lib/gen_link.py` | the console's library, and its cycle-timed serial routines |
| `apps/setup/` | the setup ROM |
| `apps/` | the other programs: the jukebox, NESpedia, the throughput test, netplay for Dr. Mario and Contra, and NES Radar |
| `third_party/` | the two games' disassemblies and nes-radar, as submodules |
| `nes/cart/` | the cartridge: its menu, and the tool that puts the four programs on it |
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
- `test_radar.py`: where an airport is from Wikidata's answer, a reply
  from adsb.fi to a scene and its names, held to the bytes nes-radar's own
  server makes of it and of 40 made up, and the fetches by the clock, with
  the test as both sites. nes-radar's ROM is run against this code in
  nes-radar's tests.
- `test_put_files.py`: the image of the tracks that goes over USB.
- `test_vgm.py`: the converter of rips, held to the same bytes as
  nes-jukebox's Python over its rips, over made-up ones, and over 300 made
  at random.
- `test_setup.py`: every screen of the setup ROM worked with the
  controller, to a network joined with a password of every character.
- `test_cart.py`: the cartridge on a console with its mapper: every
  program on it as built, started from the menu, and left by reset. It
  skips without the other programs in `apps/`.

The ROM tests need cc65 and skip without it.
