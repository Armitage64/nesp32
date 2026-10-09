# nesp32

A nesp32 is a small Wi-Fi computer that plugs into controller port 2 of a
Nintendo Entertainment System and gives the console what it never had: the
Internet, files, and another console to play against. It is an M5Stack
StickS3 with a level-shifting hat and this firmware. The console needs no
modification, and the games and programs that use it are ordinary ROMs.

![The cartridge's menu](docs/cart-menu.png) ![The status screen](apps/setup/docs/status.png)

Work in progress. Every program below has run on a StickS3, on a real NES
and on the MiSTer's NES core; [To do](#to-do) has what has not.

## What it does

One firmware serves every program. A ROM says which services it needs when
it starts, and the nesp32 provides them; nothing is chosen on the nesp32,
and nothing about it is ever set up from a computer.

| Service | What a ROM gets from it |
|---|---|
| Wi-Fi | the nesp32 put on a network from the controller, and kept there |
| Fetching | a page from the Internet over HTTPS, laid out as lines of text for the screen |
| Music | a playlist of NES music from the nesp32's files, streamed to the console's own sound chip |
| Sampled sound | a recording, a byte a sample, at up to 223722 baud |
| Two consoles | a lobby and a relay of buttons between two nesp32s, for one game on two consoles over a network |
| Files | the nesp32's flash as a USB drive, for a computer to copy music to |

The programs that use them, each in a directory of its own with a README:

| Program | What it is |
|---|---|
| [nesp32 Setup](apps/setup) | the nesp32's own settings on the console: status, Wi-Fi, a link test, the USB drive |
| [NESpedia](apps/wiki) | a Wikipedia reader: type a search on the console and read the article |
| [NES Jukebox](apps/jukebox) | plays rips of NES games' music, and recordings, from the nesp32 |
| [Dr. Mario, two consoles](apps/drmario) | Dr. Mario's two-player game over a network |
| [Contra, two consoles](apps/contra) | Contra's two-player game over a network |

`make cart` puts Setup, NESpedia, the Jukebox, Dr. Mario's netplay and a
link speed test on one cartridge with a menu
([how](docs/DEVELOPMENT.md#the-cartridge)). The two games are not in this
repository: their netplay is, as patches to other people's disassemblies.

## How it works

- **It is a serial line on the controller port.** The console sends on the
  strobe line and receives on a data line of port 2, at 85227 baud, each
  bit timed by counting CPU cycles. The hat shifts the levels between the
  console's 5 V and the nesp32's 3.3 V ([wiring](docs/WIRING.md)).
- **The console asks, the nesp32 answers.** Every exchange is one request
  and one reply, each with a check. A request names a service and an op. A
  request sent again gets the same reply again and is not acted on twice.
- **A ROM begins with a hello** that names the services it needs. The
  nesp32 starts those and stops the rest, so one firmware serves whatever
  cartridge is in.
- **The nesp32 never keeps the console waiting.** One task on a core of its
  own answers from what the services hold; joining a network, scanning and
  fetching are done by other tasks and asked after.
- **What cannot wait for a frame goes outside the frames.** For sampled
  sound the two agree a rate in frames, and then the line is a run of bare
  bytes at that rate until the sound is over.
- **The same C runs on the nesp32 and under the tests.** The link and the
  services touch no hardware. Built for a computer, they answer the real
  ROMs on a simulated console, over a line that models every bit.

[The protocol](docs/PROTOCOL.md) has all of it: the line, the frames, each
service and its timing.

## To do

Built and tested on a computer, not yet run on hardware:

- The nesp32's files in a FAT filing system, and rips of games' music
  converted on the nesp32 itself when it starts.
- A StickS3 as a USB drive, from Setup's screen.
- A computer in place of a nesp32, on a USB serial cable
  (`host/serial_host.py`).

Not measured:

- A long run, and figures from a real NES: it works there, and nothing was
  timed.
- Why the network between two nesp32s is slower for the first eight to ten
  seconds after they connect than it is from then on
  ([the protocol](docs/PROTOCOL.md), "The delay").

Not started:

- A service for [nes-radar](https://github.com/Armitage64/nes-radar), and its ROM moved to it. It is
  the last of the programs that still has a firmware of its own.
- The receiving nesp32 woken when a packet comes, in place of looking once
  a millisecond.
- A way for two nesp32s to meet across the Internet without a port
  forwarded.
- A fetch that drops partway made again; today what came is read, if it
  was a screenful.
- Updates over Wi-Fi, and a way to put music on a nesp32 without a cable.
- PAL consoles.
- A licence. A line-by-line comparison found no code of nes-radar's
  (GPL-3.0) here beyond idioms. The CRC routine without a table follows
  Greg Cook's on 6502.org, whose terms have not been checked.

Each program has a list of its own in its README, and the firmware has one
in [its README](firmware/README.md).

## Documents

| | |
|---|---|
| [docs/WIRING.md](docs/WIRING.md) | the hat: its pins, the level shifter, and why it is needed |
| [docs/PROTOCOL.md](docs/PROTOCOL.md) | the link: the line, frames, the hello, every service, timing, and the console's library |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | building, the cartridge, what is where in the repository, the tests, and how far each part has got |
| [firmware/README.md](firmware/README.md) | the nesp32's firmware: building and flashing it, how it keeps time, and what was seen on hardware |
| [apps/setup](apps/setup), [apps/wiki](apps/wiki), [apps/jukebox](apps/jukebox), [apps/drmario](apps/drmario), [apps/contra](apps/contra) | each program |
| [apps/contra/docs/Netplay.md](apps/contra/docs/Netplay.md) | how two consoles are kept in the same game, with figures from sessions on hardware |
