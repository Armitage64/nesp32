# PAL consoles: the plan

**Status: step 1 done, as of 2026-11-08**, and the throughput test passed
on the MiSTer's PAL setting. Nothing here has been tried on a PAL console. This replaces the plans of 2026-10-16 and of earlier on
2026-11-08.

A PAL NES's CPU runs at 1662607 Hz, where an NTSC one runs at 1789773, and
its frame is 312 lines, 50 a second, where an NTSC one is 262, 60 a
second. Every program here was written and measured on NTSC.

## The rule: the firmware changes, the ROMs do not

PAL support is a change to the nesp32's firmware alone. Every ROM, the
nesp32's own programs and the netplay games alike, runs on a PAL console
as it is built for NTSC. Where that makes a program run slower, as a game
or a song played at 50 frames a second in place of 60, that is accepted.
Where something would need a ROM to know its region, it is left as it is
and written down here as a known difference, not fixed.

So a PAL console plays the netplay builds of the US releases (Dr. Mario,
Tetris, Contra, Bubble Bobble, Jackal, TMNT II) at 5/6 of their speed,
their music 5/6 of its tempo and about 1.3 semitones flat: as any US game
plays on a PAL console from a flash cart. Contra Force's faster 1P ROM
does not talk to the nesp32, and is no different.

Not in it:

- **Family BASIC**, whose keyboard goes in the Famicom's expansion port,
  which a PAL NES does not have.
- **Games made from PAL releases** (Contra's is *Probotector*, another
  program): work for later, and on their own.

## Why it is less than it looks

The link's rate is a whole number of the console's CPU cycles a bit
(`PERIOD` in [`proto/nesp.toml`](../proto/nesp.toml), and 14 for a PEER
session's faster line), and the console's routines in [`nes/lib`](../nes/lib)
count those cycles. On a PAL CPU the same code, unchanged, sends and hears
21 cycles a bit; that is 79172 baud there, where it is 85227 on NTSC.
Nothing on the console has to know.

The nesp32 is what turns cycles into a baud rate, and it does it from one
constant, `NESP_CPU_HZ`:

- `firmware/main/link.c`, the link's rate (`NESP_BAUD` at the start, and
  `link_line_rate`, which PEER's RATE and RAW's runs set)
- `firmware/components/nesp_services/tuner.c` (`BAUD`), the radio's rates
- `firmware/components/nesp_services/juke.c`, a sound's rate and its
  samples a second
- `firmware/components/nesp_services/raw.c`, through the HAL's
  `line_rate`, which comes back to `link.c`

So the core of it is the nesp32 learning which clock the console has, and
using that in place of the constant.

## How the nesp32 learns the clock: from the line

A ROM cannot be asked to say its region, so the nesp32 finds it out: the
rate a request is heard at is the region.

- **The nesp32 listens at one rate.** 85227 and 79172 baud are 7.6% apart,
  so a request at the other rate is past what a UART takes, and never
  passes its CRC.
- **Heard, but nothing in it, it tries the other.** Bytes came, the line
  went quiet for `LINK_GAP_US`, and no frame in them was good: the nesp32
  changes to the other clock, and the console's next try is heard. A
  framing error is not the sign: `link.c` already sees one at every
  controller read (`hear`), at either rate.
- **A good frame settles it.** From then the nesp32 keeps that clock, and
  hunts again only once the line has been quiet long enough for the
  console to have been turned off or changed.
- **It remembers.** The clock last settled on is kept in the nesp32's
  flash, so a PAL console's first request is usually heard the first time.
- **The nesp32's screen says PAL** when that is the clock it settled on.

A Dendy (below) is 0.9% from NTSC, near enough for the link to work at the
NTSC rate, so this takes it for NTSC.

Kept in reserve, if the hunt proves unreliable on hardware: the RMT can
read the RX pin beside the UART and time the request marker's low run (its
start bit and bit 0), about 23.5 µs on NTSC and 25.3 on PAL. Exact, but new
code on each of the three boards. A setting on the nesp32 is trivial and
easy to get wrong; worth having only as an override of the hunt.

The first plan's other ways, a region flag in HELLO and a hello at a rate
shared by both clocks, each change every ROM, and are out under the rule.

## What changes

In the order to do them.

### 1. The firmware: done, but for the hardware

Written, and tested on the host (`tests/test_region.py`, with a model of a
UART hearing the other clock's rate); all three firmwares build. On a
StickS3 and the MiSTer (step 5) the throughput test passes as it did in
NTSC, and in PAL.

- The clock per session in place of `NESP_CPU_HZ` in `link.c`, `tuner.c`,
  `juke.c` and `raw.c`. `NESP_CPU_HZ` stays for what is built into a ROM.
- The hunt, the settling and the remembering, above, in `link.c` and
  `nesp_core` (which counts what was heard and what was good), with host
  tests of each. A miss is four bytes or more with no good request:
  the controller read is one or two a frame. One miss changes the clock
  until a request has been good at it, eight in a row after that. The
  link task changes it as soon as the line goes quiet after a miss, so a
  console's next try, a frame later, is heard.
  Misses count only while the line is at the link's own rate: at a
  session's faster one, a console that has gone back to 21 before its
  nesp32 has is heard as noise, and that is PEER's to mend (Contra's
  `test_a_line_no_good_at_its_rate_goes_back_to_the_links` found it).
- The region on the nesp32's screen: "PAL:" in place of "NES:".
- **RAW's start on PAL.** The console's settle (`SOUND_SETTLE` in the
  jukebox and NESradio, `SETTLE_LOOPS` in the throughput test) is cycles
  worked out from `NESP_CPU_HZ` when the ROM is built, so on PAL it ends
  at about 161 ms in place of 150, and the nesp32's first byte at
  `RAW_START_MS`, 175, leaves 14 ms where it left 25. The nesp32 scales
  `RAW_START_MS` by the clock on PAL, to 189 ms, and the margin is what
  it was. Nothing else of a run's times wants it: the nesp32 changes its
  rate at `RAW_LISTEN_MS`, while the console is silent either way.
- **The region in PEER's meeting.** The two nesp32s already tell each
  other the game and its version when they meet (`peer.c`); a PAL
  console's sets bit 7 of the version (`PEER_PAL`), so an NTSC one's
  greeting is as it was. Greetings that differ are refused, so for now
  two PAL consoles play and a PAL one and an NTSC one do not, until step
  4 says which games hold between them.

### 2. The simulators: about a day

Each wants a region: a PAL frame of 33247.5 cycles, a vblank of 70 lines
(about 7459 cycles, where NTSC's is 2273), and a link at the PAL rate. The
NTSC frame is written in:

- `tests/console.py` (`FRAME_CYCLES`), the shared console of the setup
  ROM's and the services' tests
- `apps/jukebox/tests/nes_harness.py` (`NTSC_FRAME_CYCLES`), which
  `apps/npr/tests/radio.py` uses too
- `apps/throughput/tests/thru_sim.py` and `apps/throughput/tools/gen_rates.py`
  (`FRAME_CYCLES`)
- each netplay game's `tests/console.py` (`FRAME_CYCLES`), and its
  `tests/wire.py` and `tests/netplay.py`, which take the link's rate and
  the network's times from `NESP_CPU_HZ`

Then the suites can run both, and the hunt can be tested against a console
that speaks either.

### 3. The nesp32's own programs: about 2 days

**Setup, NESpedia, weather, nes-radar and Bluesky** only show things, so
with the rate right they should work as they are. Times they count in
frames run 20% longer (nes-radar's `POLL_FRAMES`, `ANSWER_FRAMES` and
`RECALL_FRAMES`, in `third_party/nes-radar/nes_radar/nes/radar_link.inc`,
and their like in the others); a wait the nesp32's side also times should
be checked against it. `NESP_TIMEOUT`'s passes of 4.15 ms become 4.47 ms;
the NMI ends a wait in any case. Chat ([its plan](../apps/chat/PLAN.md))
should be written to work on either from the start.

**NESradio.** The two qualities, 23244 and 11622 samples a second, become
about 21540 and 10770 on PAL. The tuner's decoder resamples to whatever
rate it is told, so this is giving it the PAL one, and checking that the
ring still never runs dry and that the news's turns of
`TUNER_NEWS_TURN_MS` still fit.

**The jukebox.** The console plays one frame of a track at each vblank,
and that stays so.

- **Pitch, in the nesp32.** Every period of an NTSC rip is 7.6% flat on a
  PAL console. The nesp32 rewrites them for the clock it settled on.
  `vgm.c` already does this one way, a PAL rip's periods for an NTSC
  console (`add_pal`); this makes the clock it converts to the session's,
  so that a PAL rip on a PAL console then needs nothing.
- **Tempo, in the nesp32.** An NTSC rip at one frame a vblank plays at
  5/6 of its speed. The nesp32 retimes the stream from 60 frames a second
  to 50, merging register writes across frames, and a PAL rip again needs
  nothing.
- **Sampled sound, in the nesp32.** A sound's rate is a period in cycles,
  so on PAL a `.pcm` track plays 7.6% slow and low. The nesp32 resamples
  it to the rate the PAL console will play.
- **The clock on the screen: a known difference.** The console counts
  `FRAMES_PER_SECOND = 60` (`apps/jukebox/nes/ui.inc`) of the stream's
  frames to a second, and on PAL it plays 50, so its clock runs at 5/6.
  The length the nesp32 puts in a track's intro is its own, and right.

**The throughput test: a known difference.** The rates it shows are worked
out for NTSC when it is built (`apps/throughput/tools/rates.py`), so on
PAL they read 7.6% high. Which rates pass is what it is for, and that it
shows rightly.

A PAL vblank is three times as long as an NTSC one, so nothing that fits
an NTSC NMI will stop fitting.

### 4. The netplay games: a few days each

Each game, as it is, on two PAL consoles, and then on one of each.

**Two PAL consoles.** Both have the same clock, and the lockstep is as it
is on NTSC. Some of it is easier: a PAL frame is 33247 cycles where an
NTSC one is 29780, and the 3467 more are more than Contra's exchange
(about 3100), so the frames a session overruns should mostly go; and a
tick is 20 ms in place of 16.7, so the same input delay takes more of the
network. To look at, in each game:

- **Splits timed by counting cycles.** A PAL line is about 106.6 CPU
  cycles where an NTSC one is 113.7. A split placed by sprite 0 or the
  MMC3's line counter is where it was; one placed by a loop of counted
  cycles after it comes some lines off.
- **The drums.** PAL's sample channel has another table of rates. What
  the [Phantom Right](PHANTOM-RIGHT.md)'s fix (Dr. Mario) and the real
  NES mishearing its nesp32 while the drums play (Contra's
  [Netplay.md](../apps/contra/docs/Netplay.md)) depend on is where a
  sample's fetches land, worked out on NTSC.

**One of each.** The game stays one game: a tick runs only with both
players' buttons, and each build already took out what made a frame's
result depend on its cycles (Contra's random number, stirred in the idle
loop). Each game's tests already play the same game with one console's
frames shorter (0.93 in Contra and Jackal, 0.8 in Bubble Bobble). What has
not been tried:

- a PAL frame, 1.116 of an NTSC one, longer than any tested (1.03)
- a clock 17% apart for a whole session: `drift` in each game's
  `test_lockstep.py` is 0.05%, a crystal's
- how the input delay follows a console that is always behind

If the game holds, the NTSC console stalls about one frame in six: its
picture stands still for a frame while its music goes on, and the game on
both runs at 50 ticks a second.

**What is decided from it.** For each game, from the simulator and then
the MiSTer:

- two PAL consoles: let in, unless a split or the drums break the game in
  a way only the ROM could mend, and then PEER refuses that game on PAL
- one of each: let in if the game stays one game, refused at the meeting
  (step 1) if not

The faster line (PEER's RATE, 14 cycles a bit) is 118758 baud on PAL, and
works as the rest of the link does once the clock is the session's.

### 5. The hardware: the MiSTer now, a PAL console later

There is no need to wait for a PAL console to start. The MiSTer's NES core
has a region setting, and a StickS3 already runs on it through SNAC:

- **First, the throughput test** on the core set to PAL. Done on
  2026-11-08, on a StickS3 that had settled on NTSC: when the core was
  set to PAL the nesp32 hunted once ("listening for a PAL console") and
  answered from then on. The test climbed to 6 cycles a bit both ways, as
  on NTSC, which it shows as 298296 baud: that is NTSC's figure for 6, and
  at the PAL clock it is 277101 (step 3's known difference). So the core
  does run the CPU at the PAL clock (the NTSC rate would not have been
  heard), and the link holds at every rate up to the fastest.
- **Then each program** of steps 3 and 4, as each had on NTSC. A session
  of one of each needs a second console: the MiSTer against a real NTSC
  NES.

A real PAL console is then for what the MiSTer cannot say. [The
wiring](WIRING.md) was worked out from an NTSC NES-001's parts, and the PAL
consoles' levels have not been checked: whether D0 still goes into a
74HC368 at 5 V, and how OUT0 behaves, with the StickS3 hat's link and the
generic S3's three resistors. The drums' timing on the sample channel is
also the real console's to say. A US cartridge does not start on a PAL
NES, so the games are played from a flash cart.

## In all

About a week for the firmware, the simulators and the nesp32's own
programs, and a few days for each netplay game, with the hardware's runs
on the MiSTer.

## Known differences on PAL

All from the ROMs being NTSC's, and kept so:

- the netplay games, and any NTSC game, at 5/6 of their speed, and their
  music flat
- in a session of one of each, if let in, the NTSC console's picture
  standing still one frame in six
- the jukebox's clock on the screen at 5/6
- the throughput test's rates reading 7.6% high
- times the ROMs count in frames 20% longer

## Not in this plan

- **Games for PAL consoles**, from PAL releases: later, and on their own.
- **The Dendy** and the other Famicom clones of the former Soviet Union
  are a third timing: a CPU at 1773448 Hz and frames of 312 lines, 50 a
  second. The link takes them for NTSC (above), and the jukebox's tempo
  is the one thing that would want a third answer. The MiSTer's core has
  a Dendy setting to try them on.
