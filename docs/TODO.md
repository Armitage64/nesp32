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
- What holds the hat at 198864 baud to a real NES. The throughput test
  there stops at 9 cycles a bit, on two consoles and from either Stick,
  where the MiSTer takes 298296, the last rate the console's CPU can. A
  pull-up of 3.3 kΩ in place of 10 kΩ took it from 149148 to 198864, and
  a stronger one did no better ([the wiring](WIRING.md), "Speed"). D0 has
  not been on a scope: its rising edge, how long after G8 falls it begins
  (the TX transistor coming out of saturation), and the level the
  console's 74HC368 reads it at would say which it is.
- How fast the hat carries from a real NES, the other way: the throughput
  test's NES-to-nesp32 half has its figure only from the MiSTer (223722
  baud), and the 100 kΩ RX base resistor slows that stage's edges.

## Not started

- The link at full speed to a real NES. Until the hat carries 223722 baud
  there, NPR's high-quality mode is at 10 cycles a bit, 16271 samples a
  second (`TUNER_RATE` 4 and `TUNER_PERIOD` 10 in `proto/nesp.toml`), and
  the jukebox's sound at 8 cycles, 20338 samples a second, is past what
  the throughput test passed. At 10 cycles both play on the hat with the
  3.3 kΩ pull-up. Once the cause is known (above), what to try, cheapest
  first:
  - A speed-up capacitor of 100 to 470 pF across the TX base resistor,
    or a Schottky diode (BAT85, 1N5817) from the TX base to its collector,
    to keep the transistor out of hard saturation.
  - 2N3904s from a known maker, in case the ones on hand are slow.
  - A TX stage that drives D0 high as well as low: the 74AHCT1G125 of
    [the wiring](WIRING.md)'s "two single-gate buffers", powered from the
    NES. That is surface mount, and a new revision of the board.

  With 223722 passing on a real NES and some margin above it, NPR goes
  back to 8 cycles (`TUNER_RATE` 5, `TUNER_PERIOD` 8), and the docs that
  give its rate with it.
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
- PAL consoles ([the plan](PAL.md)). The console's library counts cycles,
  not time, and works as it is on a PAL CPU; what assumes NTSC is the
  nesp32's rates, worked out from the NTSC clock, and the programs' times
  and sounds made for 60 frames a second. Dr. Mario and Contra would also
  need their patches made again for the PAL releases.
