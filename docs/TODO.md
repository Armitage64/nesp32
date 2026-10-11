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

- NES Radar on the cartridge. Its ROM is a CN-ROM with two pictures'
  worth of CHR, and the cartridge gives each program one.
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
  (GPL-3.0) here beyond idioms; since then [apps/nes-radar](../apps/nes-radar)
  has a patch to its ROM, which is under that licence. The CRC routine without a table follows
  Greg Cook's on 6502.org, whose terms have not been checked.

