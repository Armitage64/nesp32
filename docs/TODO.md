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
- More data lines, for the next board. The hat uses one of controller
  port 2's inputs, D0, and the port has two more, D3 and D4, which the
  console reads in the same `$4017` as bits 3 and 4. With one of them
  wired, a nesp32 could send something else while a sound has D0: the
  headlines of [NPR](../apps/npr) at the station's best rate, where today
  they ride in the samples' eighth bit and want a lower one for the cycles;
  a track's name or a running clock in the jukebox. It wants a level-shifting stage a line
  ([the wiring](WIRING.md)), a second UART or a clocked line on the
  nesp32, and the sound's routines taught to keep those bits out of the
  sample (a read of the port takes all of them at once). Not worked out
  further than that. The port's CLK pin, which every read of `$4017`
  pulses, is the other line the hat leaves alone
  ([the jukebox's plan](../apps/jukebox/PLAN.md), "clocked link").
- PAL consoles.
- A licence. A line-by-line comparison found no code of nes-radar's
  (GPL-3.0) here beyond idioms; since then [apps/nes-radar](../apps/nes-radar)
  has a patch to its ROM, which is under that licence, and the cartridge,
  which the web site offers, has that ROM on it. The CRC routine without a table follows
  Greg Cook's on 6502.org, whose terms have not been checked.

