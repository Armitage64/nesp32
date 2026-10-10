# NESP32

An inexpensive, DIY wireless network interface for the Nintendo Entertainment System (NES) based on
the ESP32 S3 microcontroller. 

<p float="left">
  <img src="docs/cart-menu.png" width="49%" alt="The cartridge's menu" />
  <img src="apps/setup/docs/status.png" width="49%" alt="The status screen" />
</p>

## About

The NESP32 is built using the M5 Stick S3. This 
all-in-one IoT development kit includes a dual core processor,
flash storage, audio, WiFi, color LCD screen, battery, USB interface, and buttons. 
A small "hat" plugs into the top of the device and connects to controller port 2 of the NES. 

Extensible firmware provides an API that any cartridge-based
software can interface with. A setup program allows the wifi and USB storage 
to be configured from the NES itself. 

Once configured, the NESP32 provides Internet access, media streaming, and online 
gaming capabilities to software.

## Quick Links

[NESP32 Home Page](https://retrobits.tv/nesp32)

Hardware | PCB

[Online Firmware Update](https://retrobits.tv/nesp32/flash/)

## Status

The following 
| Service | What it provides |
|---|---|
| Wi-Fi | Connect to an access point from the NES |
| Fetch | Retrieve pages via HTTP/S, reduced to plain text for display |
| Music | Stream VGM/VGZ music to the NES's APU |
| Sampled sound | Stream PCM audio at up to 20kHz |
| Online Gaming | Host or join a 2-Player game over the network |
| Files | Manage stored music files via USB drive mode |

Current NES Apps: 

| Program | What it is |
|---|---|
| [Setup](apps/setup) | Configure the NESP32, status, Wi-Fi, link test, USB drive |
| [NESpedia](apps/wiki) | Search and display Wikipedia articles |
| [Jukebox](apps/jukebox) | Stream VGM/VGZ music files and PCM audio to the NES |
| [Throughput](apps/jukebox/throughput) | Test the bandwidth of the NES<>ESP32 interface |
| [Dr. Mario 2P](apps/drmario) | Dr. Mario two-player over a network |
| [Contra, 2P](apps/contra) | Contra's two-player over a network |

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
- The web site (`make web`: a product page, and a page that flashes a
  nesp32 from a browser) put on GitHub Pages: an Action that builds the
  firmware and deploys `build/web`, for when the repository is public.
  Until then it is served from this computer (`make web-serve`). The
  product page is a stub, and the flashing page has not yet flashed a
  StickS3.
- PAL consoles.
- A licence. A line-by-line comparison found no code of nes-radar's
  (GPL-3.0) here beyond idioms. The CRC routine without a table follows
  Greg Cook's on 6502.org, whose terms have not been checked.

## Further Reading

| | |
|---|---|
| [docs/WIRING.md](docs/WIRING.md) | the hat: its pins, the level shifter, and why it is needed |
| [docs/PROTOCOL.md](docs/PROTOCOL.md) | the link: the line, frames, the hello, every service, timing, and the console's library |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | building, the cartridge, what is where in the repository, the tests, and how far each part has got |
| [firmware/README.md](firmware/README.md) | the nesp32's firmware: building and flashing it, how it keeps time, and what was seen on hardware |
| [apps/setup](apps/setup), [apps/wiki](apps/wiki), [apps/jukebox](apps/jukebox), [apps/drmario](apps/drmario), [apps/contra](apps/contra) | each program |
| [apps/contra/docs/Netplay.md](apps/contra/docs/Netplay.md) | how two consoles are kept in the same game, with figures from sessions on hardware |
