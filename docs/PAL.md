# PAL consoles: the plan

**Status: not started, as of 2026-11-08.** Nothing here has been tried on
a PAL console. This replaces the plan of 2026-10-16, which predates the
netplay games after Dr. Mario and Contra, the faster line, and the S3
boards.

A PAL NES's CPU runs at 1662607 Hz, where an NTSC one runs at 1789773, and
its frame is 312 lines, 50 a second, where an NTSC one is 262, 60 a
second. Every program here was written and measured on NTSC.

## What PAL covers, and what it does not

The programs that are the nesp32's own, which show things or play sound:
the setup ROM, NESpedia, weather, nes-radar, Bluesky, the jukebox, NESradio
and the throughput test, and chat when it is written.

Not the games made from US releases, and not Family BASIC. These are 60 Hz
programs and will not be converted:

- the netplay builds: Dr. Mario, Tetris, Contra, Bubble Bobble, Jackal and
  TMNT II, and Contra Force's faster 1P ROM. A PAL console would want the
  PAL releases (Contra's is *Probotector*, another program), every address
  in the patches found again, and the [Phantom Right](PHANTOM-RIGHT.md)'s
  fix checked against PAL's other table of sample rates.
- Family BASIC, a Famicom program whose keyboard goes in the Famicom's
  expansion port, which a PAL NES does not have.

Games for PAL consoles, made from PAL releases, are work for later and not
part of this plan. Leaving the netplay builds out also leaves out PEER's
RATE and the faster line, which only they use.

## Why it is less than it looks

The link's rate is a whole number of the console's CPU cycles a bit
(`PERIOD` in [`proto/nesp.toml`](../proto/nesp.toml)), and the console's
routines in [`nes/lib`](../nes/lib) count those cycles. On a PAL CPU the
same code, unchanged, sends and hears 21 cycles a bit; that is 79172 baud
there, where it is 85227 on NTSC. Nothing on the console has to know.

The nesp32 is what turns cycles into a baud rate, and it does it from one
constant, `NESP_CPU_HZ`:

- `firmware/main/link.c`, the link's rate (`NESP_BAUD` at the start, and
  `link_line_rate`)
- `firmware/components/nesp_services/tuner.c` (`BAUD`), the radio's rates
- `firmware/components/nesp_services/juke.c`, a sound's rate and its
  samples a second
- `firmware/components/nesp_services/raw.c`, through the HAL's
  `line_rate`, which comes back to `link.c`

So the core of it is the nesp32 learning which clock the console has, and
using that in place of the constant.

## How the nesp32 learns the clock: from the line

The first plan had each ROM time its frames, a flag in HELLO saying the
region, and the nesp32 trying the other rate when the first hello was not
heard. Only the last of those is needed: the rate a request is heard at is
the region.

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
- **No ROM and no part of the protocol changes.** nes-radar, whose ROM
  comes from upstream (READ-only), needs nothing, nor do the setup ROM,
  NESpedia, weather or Bluesky.
- **PEER is refused on PAL.** A netplay build run on a PAL console (from a
  flash cart, say) gets a status from PEER's ops in place of a session,
  and shows the error it already has, rather than playing out of step.
- **The nesp32's screen says PAL** when that is the clock it settled on.

A Dendy (below) is 0.9% from NTSC, near enough for the link to work at the
NTSC rate, so this takes it for NTSC; only the jukebox would notice.

Kept in reserve, if the hunt proves unreliable on hardware:

- **Measuring the bit.** The RMT can read the RX pin beside the UART and
  time the request marker's low run (its start bit and bit 0): about 23.5
  µs on NTSC, 25.3 on PAL. Exact, but new code on each of the three boards.
- **A hello at a shared rate.** The console sends its hello at a period
  that comes out at nearly the same baud on both clocks, and says its
  region in it. `gen_link.py` already makes a second period's routines for
  the faster line, so this is cheaper than it was, but every ROM changes.
- **A setting on the nesp32.** Trivial, and easy to get wrong; worth
  having only as an override of the hunt.

## What changes

In the order to do them. The first two are what every later step stands
on; the setup ROM and the programs that only show things work with those
alone.

### 1. The firmware: about 1–2 days

- The clock per session in place of `NESP_CPU_HZ` in `link.c`, `tuner.c`,
  `juke.c` and `raw.c`. `NESP_CPU_HZ` stays for what is built into a ROM.
- The hunt, the settling and the remembering, above, in `link.c` and
  `nesp_core` (which counts what was heard and what was good), with host
  tests of each.
- PEER refused on PAL, and the region on the nesp32's screen.

### 2. The simulators: about a day

Only the programs that stay need one. Each wants a region: a PAL frame of
33247.5 cycles, a vblank of 70 lines (about 7459 cycles, where NTSC's is
2273), and a link at the PAL rate. The NTSC frame is written in:

- `tests/console.py` (`FRAME_CYCLES`), the shared console of the setup
  ROM's and the services' tests
- `apps/jukebox/tests/nes_harness.py` (`NTSC_FRAME_CYCLES`), which
  `apps/npr/tests/radio.py` uses too
- `apps/throughput/tests/thru_sim.py` and `apps/throughput/tools/gen_rates.py`
  (`FRAME_CYCLES`)

Then the suites can run both, and the hunt can be tested against a console
that speaks either.

### 3. Setup, NESpedia, weather, nes-radar and Bluesky: about half a day

These only show things, so with the rate right they should work as they
are. To look at:

- **Times counted in frames** run 20% longer: nes-radar's `POLL_FRAMES`,
  `ANSWER_FRAMES` and `RECALL_FRAMES`
  (`third_party/nes-radar/nes_radar/nes/radar_link.inc`),
  and their like in the others. Most can stay; a wait the nesp32's side
  also times should be checked against it.
- **`NESP_TIMEOUT`**'s passes of 4.15 ms become 4.47 ms. The NMI ends a
  wait in any case, and a PAL frame is longer, so nothing should break.
- **Chat** ([its plan](../apps/chat/PLAN.md)) should be written to work on
  either from the start.

A PAL vblank is three times as long as an NTSC one, so nothing that fits
an NTSC NMI will stop fitting.

Weather looks up US zip codes. It will run on a PAL console, but is of
little use to most who have one; that is the weather service's to change,
not this plan's.

### 4. The jukebox: about 2–4 days

The jukebox is the one program whose console side has to know its region,
and it can time its own frames: about 29780 cycles from one vblank to the
next is NTSC, 33248 PAL.

- **Pitch.** Every period of an NTSC rip is 7.6% flat on a PAL console.
  The nesp32 rewrites them for the clock it settled on. `vgm.c` already
  does this one way, a PAL rip's periods for an NTSC console (`add_pal`);
  this makes the clock it converts to the session's, so that a PAL rip on
  a PAL console then needs nothing.
- **Speed.** The console plays one frame of a track at each vblank, so on
  PAL an NTSC rip plays at 5/6 of its speed. Two ways, to choose between:
  - the console plays two of the stream's frames at every fifth vblank.
    The stream and the nesp32 are as they are, since the console asks for
    more from where it has got to. The one to try first.
  - the nesp32 retimes the stream from 60 frames a second to 50, merging
    register writes across frames, as the first plan had it.
- **The clock on the screen.** `FRAMES_PER_SECOND = 60` in
  `apps/jukebox/nes/ui.inc`; it wants 50 on PAL, or 60 still if the
  console plays 60 of the stream's frames a second.
- **Sampled sound.** A sound's rate is a period in cycles, so on PAL a
  `.pcm` track plays 7.6% slow and low. The nesp32 resamples it to the
  rate the PAL console will play, or the tool that makes the tracks makes
  both.
- **The settle and the rest** (`SOUND_SETTLE`, `SOUND_REST` in
  `apps/jukebox/nes/serial_link.inc`), worked out from `NESP_CPU_HZ`
  when the ROM is built, are 7.6% longer on PAL. For REST that is only
  safer. For SETTLE the console starts listening at about 161 ms in place
  of 150, and the nesp32's first byte comes at `RAW_START_MS`, 175: the
  margin goes from 25 ms to 14. Enough, but worth working out from the
  region in place of the constant.

### 5. NESradio: about a day

The two qualities, 23244 and 11622 samples a second, become about 21540
and 10770 on PAL. The tuner's decoder resamples to whatever rate it is
told, so this is giving it the PAL one, and checking that the ring still
never runs dry and that the news's turns of `TUNER_NEWS_TURN_MS` still
fit. `SOUND_SETTLE` and `SOUND_REST` in `apps/npr/nes/npr.s` are as the
jukebox's.

### 6. The throughput test

`SETTLE_LOOPS` (`apps/throughput/nes/linktest.s`) is as the jukebox's
settle. The rates it shows are worked out for NTSC when it is built
(`apps/throughput/tools/rates.py`), so on PAL they read 7.6% high. It is
the first program to run on a PAL console, below, so its numbers should
be right there.

### 7. The hardware: the MiSTer now, a PAL console later

There is no need to wait for a PAL console to start. The MiSTer's NES core
has a region setting, and a StickS3 already runs on it through SNAC:

- **First, the throughput test** on the core set to PAL. One run says
  whether the core changes the CPU's clock as a PAL console's, and whether
  every rate the link uses holds at the PAL clock, sound's 7 cycles a bit
  among them, where the first plan thought only of 21.
- **Then each program** of steps 3 to 5, as each had on NTSC.

A real PAL console is then for what the MiSTer cannot say. [The
wiring](WIRING.md) was worked out from an NTSC NES-001's parts, and the PAL
consoles' levels have not been checked: whether D0 still goes into a
74HC368 at 5 V, and how OUT0 behaves, with the StickS3 hat's link and the
generic S3's three resistors.

## In all

About 1–1½ weeks for the firmware, the simulators, and every program that
stays, with the hardware's runs on the MiSTer. The first plan's 3–6 weeks
were mostly the netplay games, now left out.

## Not in this plan

- **Games for PAL consoles**, from PAL releases: later, and on their own.
- **The Dendy** and the other Famicom clones of the former Soviet Union
  are a third timing: a CPU at 1773448 Hz and frames of 312 lines, 50 a
  second. The link takes them for NTSC (above), so they would cost the
  jukebox's region check a third answer and the simulators a third
  setting. The MiSTer's core has a Dendy setting to try them on.
