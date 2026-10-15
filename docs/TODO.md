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

## Not started

- A way for two nesp32s to meet across the Internet without a port
  forwarded: a server that introduces them, or a relay. Today the host
  forwards UDP port 6502.
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
- PAL consoles. The console's library counts NTSC cycles, and so does
  every program on it.
