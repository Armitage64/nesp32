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

- The Bluetooth keyboard, which works on hardware (paired from Setup,
  typing in NESpedia and Weather): whether every byte of the 75 KB comes
  back when Bluetooth turns off, over many times; the wait for a sleeping
  keyboard being called off; and a keyboard other than the MX Keys S,
  whose report may be laid out otherwise
  ([the firmware](../firmware/README.md), "A Bluetooth keyboard").
- The Bluetooth keyboard's 10 s or so to type again once a program that
  uses it starts: see where the time goes in the log, and whether
  NimBLE's GATT caching (so that esp_hid need not read the keyboard's
  services afresh every connection) or keeping Bluetooth on longer
  between programs shortens it.

## Not started

- **Games that differ: find out why, then perhaps mend them.** For later
  consideration. Today a session whose digests differ ends, and both
  consoles go back to the title; no session on hardware is known to have
  ended that way, since the console does not say why it ended.
  1. *A dump when they differ.* Each console sends its 2 KB of RAM to its
     nesp32 before going back to the title, about a quarter of a second
     at 85227 baud, and the nesp32 logs it. The two logs, side by side,
     say which bytes went apart, and from that why. It wants a service to
     take the dump, and is worth doing first: it is a fraction of the
     work below, whose RAM-sending code it shares.
  2. *Resync, if differing turns out to be real and to come back.* The
     console that hosted is taken as right, and its game is copied to the
     other while both screens stand: RAM, the mapper's state, and the
     screen's tiles and palette unless the game draws them again from
     RAM. Between the nesp32s that wants a bulk way, ARQ carrying 32
     bytes a packet and holding 96. A second or less of a black screen in
     place of a session lost; but the digest is one byte in 256 ticks,
     and the player who did not host may see their game jump by up to
     eight seconds. Tetris first (its NMI draws the playfields again from
     RAM), then Dr. Mario; Contra would need its 8 KB of CHR RAM sent too,
     about 12 KB in all, and its going back to the title may well stay.

  Rolling back, as newer games do, is not for any of the three: a
  cartridge with no RAM has nowhere to keep a copy of the game, and no
  frame has the time to run the game again.
- **PEER's session at a faster rate** (issue #15): built, November 2026.
  PEER's RATE runs a session's line faster when its console asks
  ([MULTIPLAYER.md](MULTIPLAYER.md), "A faster exchange"); Jackal, TMNT II
  and Contra ask for 14 cycles a bit. Dr. Mario and Tetris have the room
  at 21 and would not gain; Bubble Bobble would gain a little. TMNT II and
  Contra at 14 have been played on a real NES and are fine, the music as it
  was; their misheard replies are not yet counted. Jackal's sessions at 14 have been played on a real NES with
  each board, levels 1, 2 and 4, the music's samples playing: 0.6% to 0.7%
  of replies misheard, and no fall back to 21 in play. 10 was built (the
  fold receiver) and tried: 12% misheard with Jackal's samples, no faster
  than 14, so Jackal asks for 14. A game with no samples might use it.
- **The exchange ahead**: tried in Jackal and dropped (November 2026; its
  README, "To do"). Made at the end of a tick that lagged, with the MMC3's
  scanline IRQ as its deadline, it was slower in a two-console session
  (46.6 frames a second against 48.2 in level 2), where a model of one
  console had it faster: the early exchange seldom has the other
  console's buttons.
- **For [Family BASIC](../apps/family-basic):** TAPE, its SAVE and LOAD,
  is done. Left: the time a SAVE takes on hardware, a list of the files,
  and BG GRAPHIC's SAVE and LOAD tried. Its README, "Not done", has them.
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

