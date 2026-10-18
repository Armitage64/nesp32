# PAL consoles: the plan

**Status: not started, as of 2026-10-16.** Nothing here has been tried on
a PAL console, and nesp32 has none to try it on yet.

A PAL NES's CPU runs at 1662607 Hz, where an NTSC one runs at 1789773, and
its frame is 312 lines, 50 a second, where an NTSC one is 262, 60 a
second. Every program here was written and measured on NTSC.

## Why it is less than it looks

The link's rate is a whole number of the console's CPU cycles a bit
(`PERIOD` in [`proto/nesp.toml`](../proto/nesp.toml)), and the console's
routines in [`nes/lib`](../nes/lib) count those cycles. On a PAL CPU the
same code, unchanged, sends and hears 21 cycles a bit; that is 79172 baud
there, where it is 85227 on NTSC. Nothing on the console has to know.

The nesp32 is what turns cycles into a baud rate, and it does it from one
constant, `NESP_CPU_HZ`:

- `firmware/main/link.c`, the link's rate
- `firmware/components/nesp_services/tuner.c` (`BAUD`), the radio's rates
- `firmware/components/nesp_services/juke.c`, a sound's rate and its
  samples a second
- `firmware/components/nesp_services/raw.c`, through the HAL's
  `line_rate`, which comes back to `link.c`

So the core of it is the nesp32 learning which clock the console has, and
using that in place of the constant.

## What changes

In the order to do them. The first two are what every later step stands
on; the menu and the simpler programs work with those alone.

### 1. The protocol and the firmware: about 1–2 days

- **The console finds out its region.** At its start, the setup ROM and
  each program count CPU cycles from one vblank to the next: about 29780
  is NTSC, 33248 PAL (and 35464 a Dendy, see below). This belongs in
  `nes/lib/nesp.inc`, done once, before the first exchange.
- **The hello says it.** A flag in HELLO's payload, added in
  `proto/nesp.toml` so that `tools/gen_proto.py` gives it to both ends.
- **The nesp32 keeps the clock per session** and works out every rate from
  it. `NESP_CPU_HZ` stays for what is built into a ROM.
- **The first hello.** It goes out before the nesp32 knows the region,
  at a rate it does not yet know. 85227 and 79172 baud are 7.6% apart,
  past what a UART takes. Two ways out, to choose between:
  - the nesp32 listens at one rate and, on a framing error or a bad CRC,
    tries the other. Cheap, and the console's side does not change; the
    first exchange from a PAL console costs an extra try.
  - the console sends its hello at a period that makes the same baud on
    both clocks (19.5 PAL cycles for 21 NTSC is not a whole number, so
    this means a slower, shared rate for the hello alone). More work on
    the console, and a second rate in `nesp.inc`.

  The first is the one to try.

### 2. The simulators: about 1–2 days

Each program's tests carry their own console with an NTSC frame written
in: `FRAME_CYCLES = 29780.5` in `tests/console.py` and in `apps/contra`,
`apps/drmario` and `apps/wiki`'s copies, and `NTSC_FRAME_CYCLES` in
`apps/npr`'s. They want a region: a PAL frame of 33247.5 cycles, a vblank
of 70 lines (about 7459 cycles, where NTSC's is 2273), and a link at
the PAL rate. Then the suites can run both, and the region check of
step 1 can be tested.

### 3. The menu, wiki, weather and nes-radar: about a day

These only show things, so with the rate right they should work as they
are. To look at:

- **Times counted in frames** run 20% longer: nes-radar's `POLL_FRAMES`,
  `ANSWER_FRAMES` and `RECALL_FRAMES` (`apps/nes-radar/nes/radar_link.inc`),
  and their like in the others. Most can stay; a wait the nesp32's side
  also times should be checked against it.
- **Times worked out from `NESP_CPU_HZ` when the ROM is built**:
  `SOUND_SETTLE` and `SOUND_REST` (`apps/npr/nes/npr.s`,
  `apps/jukebox/nes/serial_link.inc`) and `SETTLE_LOOPS`
  (`apps/throughput/nes/linktest.s`). On PAL each is 7.6% longer. For
  REST that is only safer. For SETTLE the console starts listening at
  about 161 ms in place of 150, and the nesp32's first byte comes at
  `RAW_START_MS`, 175: the margin goes from 25 ms to 14. Enough, but
  worth working out from the region in place of the constant.
- **`NESP_TIMEOUT`**'s passes of 4.15 ms become 4.47 ms. The NMI ends a
  wait in any case, and a PAL frame is longer, so nothing should break.

A PAL vblank is three times as long as an NTSC one, so nothing that fits
an NTSC NMI will stop fitting.

### 4. The jukebox: about 2–4 days

- **Music.** The console plays one frame of a track at each vblank
  (`juke.c`), so on PAL an NTSC rip plays at 5/6 of its speed, and every
  period is 7.6% flat. The nesp32 has to retime the stream from 60 frames
  a second to 50 (merging register writes across frames) and rewrite its
  periods for the PAL clock. `vgm.c` already does the reverse, a PAL
  rip's periods for an NTSC console (`add_pal`); this is the same thing
  the other way, and a PAL rip on a PAL console then needs nothing.
- **The clock on the screen.** `FRAMES_PER_SECOND = 60` in
  `apps/jukebox/nes/ui.inc`; it wants 50 on PAL.
- **Sampled sound.** A sound's rate is a period in cycles, so on PAL a
  `.pcm` track plays 7.6% slow and low. The nesp32 resamples it to the
  rate the PAL console will play, or the tool that makes the tracks makes
  both.

### 5. NPR: about 1–2 days

The two qualities, 23244 and 11622 samples a second, become about 21540
and 10770 on PAL. The tuner's decoder resamples to whatever rate it is
told, so this is giving it the PAL one, and checking that the ring still
never runs dry and that the news's turns of `TUNER_NEWS_TURN_MS` still
fit.

### 6. Dr. Mario and Contra: 1–2 weeks each, or leave them NTSC-only

These are the large part, and the one where the cost may not be worth it.

- **Their patches are made against the US ROMs.** A PAL console wants the
  PAL releases: Dr. Mario's European one, and for Contra *Probotector*,
  whose code and graphics differ. Every address in the patches and in
  `net/` would have to be found again in those, and the tests' fixtures
  with them.
- **No session between regions.** The PAL releases are other programs,
  tuned for 50 frames a second, so an NTSC and a PAL console would not be
  playing one game in lockstep. A session would have to be refused when the two hellos
  disagree, through PEER.
- **The drums.** The cause in [the Phantom Right](PHANTOM-RIGHT.md) is a
  sample's fetch landing on a controller read; PAL's sample channel has
  another table of rates, so the fix's reasoning has to be checked again
  there.

The recommendation is to leave these two NTSC-only, and have them say so
on a PAL console, unless there is a PAL player to play against.

### 7. The hardware: whenever there is a PAL console

[The wiring](WIRING.md) was worked out from an NTSC NES-001's parts,
and says the PAL consoles' levels have not been checked: whether D0 still
goes into a 74HC368 at 5 V, and how OUT0 behaves. Each program then wants
a run on the real console, as each had on NTSC.

## In all

About 1–2 weeks for the firmware, the protocol, the simulators and every
program but the two netplay games; 2–4 more for those, if they are done.

## Not in this plan

The Dendy and the other Famicom clones of the former Soviet Union are a
third timing: a CPU at 1773448 Hz and frames of 312 lines, 50 a second.
Once the clock is chosen per session, they would cost little more than a
third value of the region check and a third simulator setting.
