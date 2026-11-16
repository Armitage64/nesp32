# PAL consoles

**Status, 2026-11-08: PAL consoles are supported**, and every program on
the cartridge runs on the MiSTer's PAL setting. Not yet merged: the work is
on `pal-firmware` (pushed, no pull request) and `pal-pcm` (on top of it,
not pushed). Nothing has been tried on a real PAL console. What remains is
at the end: the netplay games on two PAL consoles, the simulators, a real
console, and the merge.

A PAL NES's CPU runs at 1662607 Hz, where an NTSC one runs at 1789773, and
its frame is 312 lines, 50 a second, where an NTSC one is 262, 60 a
second. Every program here was written and measured on NTSC.

## The rule: the firmware changes, the ROMs do not

PAL support is a change to the nesp32's firmware alone. Every ROM, the
nesp32's own programs and the netplay games alike, runs on a PAL console
as it is built for NTSC. Where that makes a program run slower, as a game
or a song played at 50 frames a second in place of 60, that is accepted.
Where something would need a ROM to know its region, it is left as it is
and listed under "Known differences", not fixed.

One exception was made: NESpedia's split (below), changed so that it works
on both clocks without knowing which it has.

So a PAL console plays the netplay builds of the US releases (Dr. Mario,
Tetris, Contra, Bubble Bobble, Jackal, TMNT II) at 5/6 of their speed,
their music 5/6 of its tempo and about 1.3 semitones flat: as any US game
plays on a PAL console from a flash cart. Contra Force's faster 1P ROM
does not talk to the nesp32, and is no different. Family BASIC is a
Famicom program, typed on through the nesp32 in place of the Famicom's
keyboard, so it is no different either.

Games made from PAL releases (Contra's is *Probotector*, another program)
are work for later, and on their own.

## Why the firmware is enough

The link's rate is a whole number of the console's CPU cycles a bit
(`PERIOD` in [`proto/nesp.toml`](../proto/nesp.toml), and 14 for a PEER
session's faster line), and the console's routines in [`nes/lib`](../nes/lib)
count those cycles. On a PAL CPU the same code, unchanged, sends and hears
21 cycles a bit; that is 79172 baud there, where it is 85227 on NTSC.
Nothing on the console has to know. The nesp32 is what turns cycles into
a baud rate, and it did that from one constant, `NESP_CPU_HZ`: the work
was the nesp32 learning which clock the console has, and using that.

## What was built

### The region, heard from the line (`pal-firmware`)

- **The hunt** (`nesp_link_gap` in `firmware/components/nesp_core`, and
  `link.c`). The two rates are 7.6% apart, so a request at the other one
  never passes its CRC. Four bytes or more between two quiet lines with
  no good request in them are a miss; the controller read is one or two
  a frame. One miss changes the clock until a request has been good at
  it, eight in a row after that. The link task changes the UART as soon as
  the line goes quiet after a miss, so the console's next try, a frame
  later, is heard. Misses count only while the line is at the link's own
  rate (below, "Lessons").
- **Remembered.** The clock settled on is kept in flash (`radio.c`,
  setting `region`) and the UART opens at it, so a PAL console is usually
  heard at its first request. Checked: after a reboot the log says "PAL
  console, 0 hunts".
- **Every rate from it.** `NESP_CPU_HZ` gave way to `nesp_link_baud` and
  `nesp_link_cpu_hz` in `link.c`, `tuner.c`, `juke.c` and `raw.c`: the
  link, RAW's runs, PEER's faster line, NESradio's and the jukebox's
  sample rates.
- **RAW's first byte.** A console counts its 150 ms settle in cycles, so
  on PAL it ends at about 161 ms; the nesp32's first byte waits as much
  longer, 189 ms in place of 175 (`nesp_link_console_ms`), and the margin
  is the 25 ms it was.
- **PEER.** A PAL console's nesp32 sets bit 7 of the version in its
  greeting (`PEER_PAL`); an NTSC one's greeting is as before, so older
  firmware still plays newer. Greetings that differ are refused: two PAL
  consoles play, a PAL one and an NTSC one do not (decided 2026-11-08:
  the NTSC console would stand still one frame in six).
- **The screen** says "PAL:" in place of "NES:", and the log the region
  and its hunts.
- **Tests:** `tests/test_region.py`, with a model of a UART hearing bytes
  sent at the other clock's rate.

### NESpedia's split (`pal-firmware`)

The article screen's split waited 969 cycles from a sprite 0 hit on the
title, eight lines up. On PAL a cycle is 3.2 dots in place of 3, and the
write landed halfway along the article's first line, which showed torn.
Sprite 0 is now on the header's last line, black over a pixel put there
for it, and the write comes 39 cycles after the hit: in the hblank on
either console (`apps/wiki/tools/gen_screen.py` works out where, for both
clocks). Its test console can be a PAL one, and `tests/test_split.py` runs
on both.

### Sampled sound (`pal-pcm`)

A `.pcm` track's samples are at an NTSC console's rate for its period, and
the console plays each as it arrives, so on PAL a sound was 7.6% slow and
low. The period cannot change (the console's receivers are built for
seven), so the nesp32 resamples: `juke.c` turns each file byte into its
level, puts it through the DAC's curve and a windowed-sinc filter to the
PAL rate, and back into a wire byte with bit 7 set. The filter is the
tuner's, moved into `resample.c` for both. A sound's length on the screen
is the file's own, and one left and taken up again goes on from its place
in the file. An NTSC console gets the file's bytes as they are. At 7 cycles
a bit a PAL console now gets 21593 samples a second against 23244, so
sound above 10.8 kHz, in place of 11.6, is filtered out. Tests:
`tests/test_juke.py`, a tone at its own pitch and length on PAL.

### The rest

- `host/peer_player.py --pal`, to be a PAL console's second player.
- The README, the user guide and the product page say NTSC and PAL are
  both supported, with the differences.

## What was checked

On a StickS3 and the MiSTer's NES core through SNAC, 2026-11-08:

- the throughput test in NTSC, and in PAL: one hunt, then the link held
  at every rate up to 6 cycles a bit both ways (shown as 298296 baud,
  NTSC's figure; 277101 at the PAL clock). So the core does run its CPU at
  the PAL clock.
- every program on the cartridge in PAL; NESpedia again after its fix, in
  both regions; NESradio with its ring never dry
- sampled sound at 7 cycles a bit, at its speed and pitch, in both regions
- the hunt from PAL back to NTSC, and the region kept over a reboot

And on the host: the root suite and every app's (the six netplay games',
the jukebox's, NESradio's, NESpedia's), and all three firmwares building
with no warnings.

## Lessons

- **Hunt only at the link's own rate.** The first build counted misses
  at PEER's faster line too. Contra's `test_a_line_no_good_at_its_rate_
  goes_back_to_the_links` loses every reply at 14 cycles a bit, so the
  console goes back to 21 before its nesp32: the nesp32 heard noise,
  changed to PAL, and the session never came back. At another rate, what
  is not heard is that rate's, and the service that set it puts it back.
- **At 7 and 8 cycles a bit nothing may wait after the lead.** The
  console's tracking receiver settles on the lead's $FF and then goes by
  the clock. The first PAL sound popped and was left: the run's first
  read worked out the filter (a few thousand sines) and read the file
  three times, with only the lead's 0.34 ms queued. The filter is now
  worked out when the track opens, and the first 512 samples are made in
  tick once the console has been told GO. Anything a run needs at its
  start is made before it.
- **Cycle-counted waits move on PAL.** A raster effect timed in CPU
  cycles is 3.2 dots a cycle there, not 3: keep a timed wait short, close
  to the event it counts from (NESpedia). The netplay games are to be
  looked at for the same (below).
- **The MiSTer's PAL setting is a real PAL clock**, and enough to test
  all but a real console's voltages and sound chip.
- **One stick, one file.** A hitch at the start of `01 Diablo - Town.pcm`,
  on a StickS3 only, in both regions and on main too, was a damaged copy
  of the file on that stick: copied again, it played. Two changes made
  for it before that was found were taken out. Check the file, and the
  same firmware on both boards, before the code.
- **Watch long suites by test.** The six netplay suites take 12 to 23
  minutes each; the first run, quiet behind `tail`, sat an hour on the
  Contra failure above. Run them verbose to a log.
- **Figures worked out when a ROM is built are NTSC's** (the throughput
  test's rates), and read 7.6% high on PAL.

Kept in reserve, if the hunt ever proves unreliable on hardware: the RMT
can time the request marker's low run on the RX pin beside the UART
(about 23.5 µs on NTSC, 25.3 on PAL). A setting on the nesp32 would only
be worth having as an override.

## What remains

### 1. The netplay games on two PAL consoles: a few days each

The firmware lets two PAL consoles play; no game has been played so. Both
have the same clock, and the lockstep is as on NTSC. Some of it is easier:
a PAL frame is 33247 cycles where an NTSC one is 29780, more than Contra's
exchange of about 3100, so the frames a session overruns should mostly
go; and a tick is 20 ms in place of 16.7, so the same input delay covers
more of the network. To look at, in each of the six:

- **Splits timed by counting cycles,** as NESpedia's was. A PAL line is
  about 106.6 CPU cycles where an NTSC one is 113.7. A split placed by
  sprite 0 or the MMC3's line counter is where it was; one placed by a
  loop of counted cycles after it comes some lines off.
- **The drums.** PAL's sample channel has another table of rates. What
  the [Phantom Right](PHANTOM-RIGHT.md)'s fix (Dr. Mario) and the real
  NES mishearing its nesp32 while the drums play (Contra's
  [Netplay.md](../apps/contra/docs/Netplay.md)) depend on is where a
  sample's fetches land, worked out on NTSC.

A game broken on PAL in a way only its ROM could mend is refused by PEER
on PAL. It needs two PAL consoles: the MiSTer and another, or the MiSTer
against `host/peer_player.py --pal`, which keeps no game of its own but
plays the session.

### 2. The simulators: about a day

Only NESpedia's test console can be a PAL one (`pal=True`). Each of these
wants the same: a frame of 33247.5 cycles, a vblank of 70 lines (about
7459 cycles, where NTSC's is 2273), and a link at the PAL rate.

- each netplay game's `tests/console.py` (`FRAME_CYCLES`), and its
  `tests/wire.py` and `tests/netplay.py`, which take the link's rate and
  the network's times from `NESP_CPU_HZ`: first, for the netplay games
  above, to try each in the simulator before the MiSTer
- `tests/console.py`, the setup ROM's and the services'
- `apps/jukebox/tests/nes_harness.py` (`NTSC_FRAME_CYCLES`), which
  `apps/npr/tests/radio.py` uses too
- `apps/throughput/tests/thru_sim.py` and `apps/throughput/tools/gen_rates.py`

### 3. A real PAL console: whenever there is one

For what the MiSTer cannot say. [The wiring](WIRING.md) was worked out
from an NTSC NES-001's parts, and a PAL console's levels have not been
checked: whether D0 still goes into a 74HC368 at 5 V, and how OUT0
behaves, with the StickS3 hat's link and the generic S3's three
resistors. The drums' timing on a real sample channel is the other thing.
A US cartridge does not start on a PAL NES, so the games are played from
a flash cart.

### 4. Smaller

- **Family BASIC** has not been tried on PAL.
- **`host/serial_host.py`**, a computer standing in for a nesp32 over a
  USB serial adapter, runs at the NTSC rate only.
- **Chat** ([its plan](../apps/chat/PLAN.md)) is to be written to work on
  either from the start.
- **Times the ROMs count in frames** run 20% longer on PAL (nes-radar's
  `POLL_FRAMES`, `ANSWER_FRAMES` and `RECALL_FRAMES` among them). All the
  programs worked; a wait the nesp32 also times would be the one to
  check if one ever does not.

### 5. The merge

`pal-firmware` and then `pal-pcm`, one pull request or two. The product
page goes up as soon as `web/` changes on main, but the firmware its
flash page offers only with a release: merge the documentation with, or
just before, the release that carries the firmware, or the page says PAL
works while the firmware it offers does not.

## Known differences on PAL

All from the ROMs being NTSC's, and kept so:

- the netplay games, and any NTSC game, at 5/6 of their speed, and their
  music flat; and the jukebox's NTSC rips likewise
- no netplay session between a PAL console and an NTSC one
- the jukebox's clock on the screen at 5/6
- the throughput test's rates reading 7.6% high
- times the ROMs count in frames 20% longer
- sampled sound filtered at 10.8 kHz in place of 11.6

## Not in this plan

- **Games for PAL consoles**, from PAL releases: later, and on their own.
- **The Dendy** and the other Famicom clones of the former Soviet Union
  are a third timing: a CPU at 1773448 Hz and frames of 312 lines, 50 a
  second. The link takes them for NTSC (0.9% apart), so they should work
  as an NTSC console does but for the jukebox's music, at 5/6. The
  MiSTer's core has a Dendy setting to try them on.
