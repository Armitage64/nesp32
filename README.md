# NESP32

An inexpensive, DIY wireless network interface for the Nintendo Entertainment System (NES) based on
the ESP32 S3 microcontroller. 

<p float="left">
  <img src="apps/setup/docs/status.png" width="32%" alt="The status screen" />
  <img src="apps/wiki/docs/search.png" width="32%" alt="The wikipedia app" />
  <img src="apps/jukebox/docs/screen.png" width="32%" alt="The jukebox app" />
</p>

## About

- Provides Internet access, media streaming, and online gaming capabilities to NES software.

- Built using the M5 StickS3. The StickS3 is a ~$20 all-in-one IoT development kit that includes a dual core processor, flash storage, audio, WiFi, color LCD screen, battery, USB interface, and buttons.

- A custom hat plugs into the top of the device and connects to controller port 2 of the NES. 

- Extensible firmware provides an API that any cartridge-based software can interface with. A setup program allows the wifi and USB storage 
to be configured from the NES itself. 

- The NESP32 is an evolution of [NES Radar](https://github.com/k6lcm/nes-radar) where the controller port serial interface was originally conceived.

## Quick Links

[NESP32 Home Page](https://retrobits.tv/nesp32)

[Purchase the M5 StickS3](https://amzn.to/3TVUV0y)

PCB Gerber Files

[Firmware Updates](https://retrobits.tv/nesp32/flash/)

## Features

Current NESP32 capabilities:
| Service | What it provides |
|---|---|
| Wi-Fi | Connect to an access point from the NES |
| Fetch | Retrieve pages via HTTP/S, reduced to plain text for display |
| Music | Stream VGM/VGZ music to the NES's APU |
| Sampled sound | Stream PCM audio at up to 20kHz |
| Online Gaming | Host or join a 2-Player game over a LAN or WAN |
| Files | Manage stored music files via USB drive mode |

Current NESP32 apps: 

| Program | What it is |
|---|---|
| [Setup](apps/setup) | Configure the NESP32, status, Wi-Fi, link test, USB drive |
| [NESpedia](apps/wiki) | Search and display Wikipedia articles |
| [Jukebox](apps/jukebox) | Stream VGM/VGZ music files and PCM audio to the NES |
| [Throughput](apps/jukebox/throughput) | Test the bandwidth of the NES<>ESP32 interface |
| [Dr. Mario 2P](apps/drmario) | Dr. Mario two-player over a network |
| [Contra, 2P](apps/contra) | Contra's two-player over a network |

## How it works

- **Repurposes controller port 2 for serial I/O.** The console sends data to the NESP32 on the
  shift register strobe line and receives on a data line of port 2. The custom hat shifts the levels between the
  console's 5 V and the NESP32's 3.3 V ([wiring](docs/WIRING.md)).
- **The NES asks, the NESP32 answers.** Every exchange is one request
  and one reply, each with a check. A request names an API service and an operation.
- **A ROM sends a hello** that names the services it needs. Unified firmware serves all supported
  cartridge programs.

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
