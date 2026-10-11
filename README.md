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
| Radar | Live air traffic round any airport, from adsb.fi |
| Files | Manage stored music files via USB drive mode |

Current NESP32 apps: 

| Program | What it is |
|---|---|
| [Setup](apps/setup) | Configure the NESP32, status, Wi-Fi, link test, USB drive |
| [NESpedia](apps/wiki) | Search and display Wikipedia articles |
| [Jukebox](apps/jukebox) | Stream VGM/VGZ music files and PCM audio to the NES |
| [Throughput](apps/throughput) | Test the bandwidth of the NES<>ESP32 interface |
| [Dr. Mario 2P](apps/drmario) | Dr. Mario two-player over a network |
| [Contra, 2P](apps/contra) | Contra's two-player over a network |
| [NES Radar](apps/nes-radar) | k6lcm's live air traffic scope, with the nesp32 in place of a computer |

## How it works

- **Repurposes controller port 2 for serial I/O.** The console sends data to the NESP32 on the
  shift register strobe line and receives on a data line of port 2. The custom hat shifts the levels between the
  console's 5 V and the NESP32's 3.3 V ([wiring](docs/WIRING.md)).
- **The NES asks, the NESP32 answers.** Every exchange is one request
  and one reply, each with a check. A request names an API service and an operation.
- **A ROM sends a hello** that names the services it needs. Unified firmware serves all supported
  cartridge programs.

## Further Reading

| | |
|---|---|
| [docs/WIRING.md](docs/WIRING.md) | the hat: its pins, the level shifter, and why it is needed |
| [docs/PROTOCOL.md](docs/PROTOCOL.md) | the link: the line, frames, the hello, every service, timing, and the console's library |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | building, the cartridge, what is where in the repository, the tests, and how far each part has got |
| [firmware/README.md](firmware/README.md) | the nesp32's firmware: building and flashing it, how it keeps time, and what was seen on hardware |
| [apps/setup](apps/setup), [apps/wiki](apps/wiki), [apps/jukebox](apps/jukebox), [apps/throughput](apps/throughput), [apps/drmario](apps/drmario), [apps/contra](apps/contra), [apps/nes-radar](apps/nes-radar) | each program |
| [apps/contra/docs/Netplay.md](apps/contra/docs/Netplay.md) | how two consoles are kept in the same game, with figures from sessions on hardware |
