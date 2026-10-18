# To do: the hardware and the firmware

What is still to do on the nesp32 itself. Each program in `apps/` keeps
its own list in its README.

## Not measured, or not known

- Why the network between two nesp32s is slower for the first eight to ten
  seconds after they connect than it is from then on
  ([the protocol](PROTOCOL.md), "The delay").
- What the access point costs a netplay session. Its spikes are in every
  packet's way and differ from day to day; marking the packets for the
  class Wi-Fi sends first, and never holding one back to send with others,
  were not seen to help ([nes-contra's figures](../apps/contra/docs/Netplay.md)).
- Why a real NES's receiver that hunts for each start bit fails at 8
  cycles a bit and the MiSTer's does not. A sweep of the throughput test
  on a real NES passed every rate from 14 cycles to 6 but 8, which lost
  about one byte in nine every time, so the hat carries the console's
  fastest rate ([the wiring](WIRING.md), "Speed"); no simulated line gives
  that pattern. From 8 cycles down the console's receivers track the start
  bit instead, and the slower ones still hunt: a cause found might be one
  that shows at those too, on another console.
- What stops the hat at 223722 baud from the console, on a real NES as on
  the MiSTer: 298296 fails. The 100 kΩ RX base resistor slows that
  stage's edges, which the SNAC adapter needs; nothing the console sends
  needs more than 85227 today.

## Not started

- A release pipeline on GitHub, for the firmware and the cartridge
  together. Today the web site (`.github/workflows/web.yml`) is built
  again from every push to main that touches the firmware, the cartridge
  or the pages, so the flash page and the cartridge to download are
  whatever main is, named by `git describe` and the commit's date
  (`tools/gen_web.py`). Instead, only a numbered release, a tag such as
  `v1.2.0`, would build and publish them, with the firmware for both
  Sticks and the cartridge attached to a GitHub release of that number.
  The firmware would carry the number, built in from the tag (ESP-IDF's
  `PROJECT_VER`, which `esp_app_get_description()` gives back), and show
  it on the Stick's screen; a build that is not a release would say so.
  The cartridge's menu could show it too, and the flash page would name it.
- A way for two nesp32s to meet across the Internet without a port
  forwarded: a server that introduces them, or a relay. Today the host
  forwards UDP port 6502.
- A choice in [Setup](../apps/setup)'s menu that turns the Stick's screen
  the other way up, and is remembered when the Stick is restarted. Today
  the way up is fixed when the firmware is built
  (`CONFIG_NESP_DISPLAY_FLIPPED`, in `firmware/main/Kconfig.projbuild`).
  The cartridge would ask for it with a new request, and the nesp32 would
  keep it in its settings in NVS, as it keeps the ZIP code and the last
  address (`radio.c`, `conn.c`), and read it before the first thing is
  drawn; the build's setting would be the way up until one is chosen.
- An idle opponent on the nesp32, as `host/serial_host.py --idle` has, to
  test one console with a nesp32 alone.
- A fetch that drops partway made again; today what came is read, if it
  was a screenful.
- Updates over Wi-Fi (the partitions are laid out for them), and a way to
  put music on a nesp32 without a cable.
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
- PAL consoles ([the plan](PAL.md)). The console's library counts cycles,
  not time, and works as it is on a PAL CPU; what assumes NTSC is the
  nesp32's rates, worked out from the NTSC clock, and the programs' times
  and sounds made for 60 frames a second. Dr. Mario and Contra would also
  need their patches made again for the PAL releases.
