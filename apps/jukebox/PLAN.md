# NES Jukebox: implementation plan

Stream NES music from `.vgm` files to a stock NTSC NES over the controller-2
serial link proven in `../nes-radar`, and play it on the console's own APU.

## Goals and non-goals

Goals:

- Play the 2A03 channels of NES `.vgm`/`.vgz` rips on real hardware (pulse 1
  and 2, triangle, noise) with frame-accurate timing.
- The NES is the timebase. Playback runs from its own vblank NMI, exactly as
  the original game's sound engine did, so host jitter and USB latency cannot
  reach the audio.
- The host feeds a RAM ring buffer on the NES through small bursts that the
  NES requests. The host never transmits unless asked.
- The product's host is the **M5StickS3** in MicroPython. A desktop Python
  streamer on nes-radar's FTDI cable exists for **testing and diagnosis
  only**: it proves the NES side on hardware before the Stick's untested
  parts join in. The Mac also stays the build machine that converts rips to
  `.jbs` for the Stick.
- Until an S3 is on hand, hardware testing uses an **M5StickC Plus2**. The
  Stick firmware runs on both and picks its pins by board; the Plus2 is a
  stand-in, not a second product.

Non-goals for v1:

- DPCM sample playback. The DMC can only fetch from `$C000-$FFFF`, which is
  cartridge ROM, not NES RAM. See phase 7.
- Raw PCM through `$4011` inside a rip (voice or drum streams). It is
  thousands of writes per second, far more than the stream of register
  writes can carry. Occasional `$4011` level writes are kept, because the
  level changes the triangle and noise mix. (Sampled sound as a track of
  its own came later and goes another way: see phase 5.)
- Expansion audio (VRC6, VRC7, N163, MMC5, 5B). VGM does not carry it. FDS is
  representable in VGM but needs the FDS hardware.
- PAL consoles. As in nes-radar, only NTSC is in scope.

## Key findings that shape the design

These come from the analysis of the nes-radar link and the VGM format.

1. **The radar pacing is far too slow.** With its 5 ms byte guard and 30 ms
   chunk gap it moves about 110 bytes/s. Raw VGM for a typical NES track is
   1.1-2.2 KB/s. A new streaming mode is required. The wiring, electrical
   design, and level shifting are reused unchanged.
2. **Compressed frames average 3-5 bytes.** That is a per-frame record of
   changed registers, described below. The original estimate was 7-13;
   phase 1 measured five real rips at 2.7-5.0 mean, p99 13-18, and a worst
   second of 256-492 bytes (about 8 per frame).
3. **At 9600 baud, requesting data every frame doesn't fit.** Per frame
   there is about 16.6 ms. It goes to the NMI (measured in phase 2: median
   0.1-0.4 ms, p99 about 1 ms, and up to 3 ms on a song's opening frame), a
   4-byte
   request (4.2 ms at 9600), host turnaround (an estimated 2-5 ms and not yet
   measured), and a margin. That leaves about 6 ms, or 5 bytes, which is
   barely a burst header. **The target is 38400 baud**, with 57600 as a
   stretch goal:

   | baud | byte time | request | payload per frame (1 ms NMI, 5 ms turnaround) |
   |---|---|---|---|
   | 9600 | 1.04 ms | 4.2 ms | about 0 |
   | 38400 | 0.26 ms | 1.0 ms | about 28 bytes |
   | 57600 | 0.17 ms | 0.7 ms | about 44 bytes |

   Twenty-eight bytes per frame against a measured average need of 3-5 is
   5-9x headroom. The ring buffer absorbs busy frames and the slow opening
   frame.
4. **The radar receiver cannot go faster.** It strobes `$4016` on every
   sample, and its start-bit hunt takes 50+ cycles per pass. A lean receiver
   reads `$4017` directly, which is safe because port 2 has no controller on
   it. Its hunt is `lda JOY2 / lsr / bcc` at 9 cycles, which is 19% of a
   38400 bit (46.6 cycles). That is a new, cycle-verified routine, not an edit
   to the radar's `receive_byte`.
5. **One baud rate for both directions.** The ESP32 and FTDI UARTs use a
   single rate, so the NES's bit-banged transmit also has to be rewritten for
   the new rate. It uses the radar's branchless `uart_tx_byte` technique at a
   46-47 cycle bit period.
6. **38400 is feasible on the port.** The console has no serial hardware.
   A `$4017` read gates D0's level for that one cycle through an inverting
   74HC368 buffer, so the receiver is pure bit-banging. The wiring adds at
   most about 4% of a bit in edge delay, even on the StickS3's NPN stage
   with a long cable. The NES-to-host direction is slower on the Stick: its
   RX base resistor is now 100 kΩ (so a MiSTer SNAC adapter's strobe still
   reaches a valid high), which is estimated to distort a 38400 bit by about
   8-15%. Measure it on a scope in phase 5. The CPU is the limit, and the
   budget holds:

   | Item | Cycles | Share of a 46.6-cycle bit |
   |---|---|---|
   | Start-bit hunt granularity (unrolled `lda JOY2 / lsr / bcs`) | 8 | 17% |
   | Bit sample (`lda JOY2 / lsr / ror zp`) | 11 | 24%, rest is padding |
   | Drift by the stop bit, alternating 46/47 cycles per bit | <1 | 2% |
   | Worst-case offset from mid-bit | | about 30% margin left |

   57600 (31.1 cycles per bit) is thin but possible. 115200 is not: the
   hunt granularity alone uses up the margin. Conditions:
   - Nothing may take CPU cycles mid-byte: `sei` always, DMC off, OAM DMA
     only inside the NMI, and the APU frame IRQ inhibited. **The converter
     forces bit 6 on in every `$4017` write in the stream.**
   - Never use a read-modify-write instruction on `$4017`. Its write would
     hit the APU frame counter. The receiver uses `lda` only.
   - The host sends **2 stop bits**, which adds about 46 cycles between
     bytes, and the NES runs the CRC over the whole burst after it arrives.
     Between bytes the receiver only stores, indexes and counts before it
     starts hunting again.
7. **The NMI doubles as the receive timeout.** The NES requests only as many
   bytes as fit before the next vblank. If the host is late anyway, the NMI
   still fires on time and plays the frame. If it interrupted a receive
   window, it rewrites its return address to `rx_abort`. Music never stalls,
   the hunt loop stays at 9 cycles with no timeout counter, and the damaged
   burst fails its CRC and is requested again.

## Architecture

```text
 .vgm/.vgz --(tools/vgm2jbs.py)--> .jbs stream  (desktop, offline)

 host (desktop+FTDI or StickS3)               NES (NROM-256)
 ------------------------------               ----------------------------
 holds the .jbs for each track                NMI, every vblank:
 answers each request with one burst            decode one frame from ring
                                                 -> APU registers
                                                 read controller 1
                                              main loop, after NMI:
      <---- REQ(seq, credit) ----------------    if ring space >= threshold:
      ---- BURST(seq, len, data, CRC) ------>      send REQ, receive burst,
                                                   CRC ok -> commit to ring
```

### Stream format (`.jbs`, jukebox stream)

This is a byte stream of records. The converter writes it, the host sends it
in bursts, and the NES decodes one frame per NMI. The byte values below are
proposals, finalized in `docs/PROTOCOL.md` during phase 1.

```text
0nnnnnnn  n>=1  wait n frames with no writes
00000000        the next write record does NOT advance a frame
                (chains two write records in one frame, for order-sensitive frames)
1ggggggg        write record, then advance one frame. Bits select groups:
                  g0 pulse1   $4000-$4003     g4 DMC   $4010-$4013 (v1: $4011 only)
                  g1 pulse2   $4004-$4007     g5 $4015 status/enable
                  g2 triangle $4008,$400A,$400B
                  g3 noise    $400C,$400E,$400F   g6 $4017 frame counter
                For each set group, in apply order: one submask byte
                (low nibble = which of the group's registers), then values.
```

Apply order within a record is `$4015` first, then channels in ascending
order, then `$4017`. A typical frame comes to about 1 + 2-3 groups × (1 + ~2)
= 7-10 bytes.

Control records, carried in-band and handled by the host rather than stored
long-term, are reserved in `$80` with no group bits set, plus an extension
byte: end of track, loop point, and track metadata. These are finalized in
phase 1.

### Converter rules (`tools/vgm2jbs.py`)

- Parse the VGM header (v1.61+). Check that the NES APU clock at `0x84` is
  nonzero. Handle `.vgz` by gunzipping it. Follow the loop offset. Honor
  `0xB4 aa dd` and the waits `0x61`, `0x62`, `0x63`, `0x70-0x7F`.
- Quantize each write's sample timestamp (44100 Hz) onto the NTSC frame grid
  (60.0988 Hz). This keeps the tempo of PAL rips.
- For a PAL rip (clock 1662607), rescale pulse, triangle and noise periods to
  NTSC pitch.
- Remove redundant writes only on registers without side effects. **Never
  deduplicate `$4003`, `$4007`, `$400B` or `$400F`.** Writing them restarts
  the length counter and envelope (and the pulse phase), and games repeat
  those writes on purpose to retrigger notes.
- When one register gets several writes in one NTSC frame, keep the last one,
  but keep a trigger if any of those writes was a trigger register.
- If the fixed apply order would give a different end-of-frame APU state or
  trigger set than the original order, emit chained records with `0x00`.
- Begin every track with `$4015=$0F`. A rip that starts after the game
  enabled its channels never writes `$4015`, and was silent on the console
  (found on hardware with Castlevania's Vampire Killer).
- Force bit 6 on in every `$4017` write. That disables the APU frame
  interrupt, which would otherwise take cycles mid-byte from the receiver.
- Drop `$4010`, `$4012`, `$4013` and `$4015` bit 4. Keep `$4011` as a plain
  register, except in frames with more than 4 writes to it (raw PCM). Report
  dropped DMC activity in a summary, so a rip that relies on DPCM is obvious.
- Output the `.jbs` plus a JSON report: frames, bytes, mean and p99 bytes per
  frame, the worst 60-frame window, dropped writes, and the loop point.

**Checking the converter:** a Python model of APU register state (not audio)
replays the original VGM and the `.jbs` side by side. It asserts that register
values and trigger events match at every frame boundary, apart from the
reported drops.

## Link protocol v1 (`docs/PROTOCOL.md`, 38400 8N2 host to NES)

The wiring is identical to nes-radar, for both the FTDI cable and the StickS3
NPN hat.

**NES to host request, 4 bytes:**

```text
$4A ('J'), SEQ, CREDIT, CHECK          CHECK = $A5 ^ $4A ^ SEQ ^ CREDIT
```

- `SEQ` is the burst the NES wants next. If it equals the last burst sent,
  the host resends that burst. If it is one more, the host sends new data.
  This covers lost requests, lost bursts, and CRC failures without a separate
  NAK.
- `CREDIT` is the largest payload the NES can take, computed from free ring
  space and the time left before vblank.
- More ops follow the same frame shape: `$48` ('H') HELLO/reset, and `$42`
  ('B') button events (next and previous track, pause).

**Host to NES burst:**

```text
$A5, SEQ, LEN, PAYLOAD[LEN], CRC_HI, CRC_LO
```

The CRC is CRC-16/CCITT-FALSE over `SEQ` through the payload, the same
algorithm as nes-radar but table-driven on the NES (512 bytes of ROM, about
30 cycles per byte). It runs over the whole burst after the last byte
arrives, about 0.7 ms for 40 bytes, never between bytes. Payload bytes are written directly at the ring's tail.
The tail is committed only once the CRC is good, so a bad burst is never
visible to the decoder.

**Timing contract:**

- The host must start a burst within `T_turn` of the request's last stop bit.
  `T_turn` is measured in phase 3 for both hosts.
- The host sends bytes back to back with 2 stop bits and no other guard.
  The lean receiver does nothing between bytes except store, index and
  count. The NES sends its requests with 1 stop bit; the host UART accepts
  either.
- The NES idles OUT0 at mark. Controller reads in the NMI briefly drop OUT0,
  and the host may see that as noise. The host decoder scans for the `$4A`
  frame with a valid check byte and resyncs one byte at a time, the same
  approach as nes-radar's `nes_uart_request.py`.
- **Session:** the NES sends HELLO. The host resets `SEQ`. The NES fills the
  ring without playing until it passes a threshold (for example, 768 of 1024
  bytes, about 1 s at 38400), then starts playback.
- **Looping and track changes** happen on the host. It restreams from the
  loop point and inserts track-boundary control records. The NES decoder
  never seeks.

## NES ROM design (`nes/`)

- **Mapper:** NROM-256 (mapper 0, 32 KB PRG, 8 KB CHR). No bank switching is
  needed. Assembled with ca65/ld65, like nes-radar.
- **RAM map:** zero page for player state and the screen's bars; `$0100`
  stack; `$0200-$03FF` player, link and screen state, including a 64-entry
  staging list (there are no sprites, so no OAM shadow);
  **`$0400-$07FF` 1 KB ring buffer**. Using a whole number of pages keeps
  wrap-around cheap.
- **Ring indices** (built in phase 2): head is the decoder's and tail is the
  link's, each a two-byte address. The main loop publishes tail through
  `tail_prev` and a one-byte `tail_busy` flag, so the NMI always sees a
  consistent tail. It reads head high byte first, so a torn head can only
  understate free space. `nes/jukebox.s` explains both.
- **Staging** (built in phase 2): the NMI decodes a whole frame into a
  staging list before touching the APU. If the ring runs dry partway, it
  writes nothing, leaves head alone, and counts an underrun.
- **NMI:** save registers, read controller 1 and write to the PPU while
  vblank lasts, decode exactly one frame (or consume one frame of a wait),
  work out the screen's bars for the next vblank, and increment a frame
  counter. On
  underrun, write nothing: the notes hold, and an underrun counter
  increments. If `rx_active` is set, rewrite the stacked return address to
  `rx_abort` before `rti`.
- **Main loop:** wait for the frame counter to change. Handle buttons (send a
  `B` request). If ring space is at least the minimum burst, compute
  `CREDIT = min(space, bytes_that_fit(time_left))`, send the request, set
  `rx_active`, receive, verify the CRC, commit, and clear `rx_active`.
- **Screen** (built in phase 6, `nes/ui.inc`): the title, the game's
  and the track's names and length from control records in the stream, a
  clock, a status line, and 28 bars driven by the APU writes. Background tiles only. Everything is drawn
  from the NMI, so the main loop's request keeps its fixed place after it.
- **Timing-critical routines** (`rx_byte`, `tx_byte`, and the start-bit
  hunt) live on their own pages in the `RXTX` segment, so no branch pays the
  page-crossing cycle. `tests/test_serial_timing.py` measures every read and
  write they make on py65, which charges page-crossing penalties, against
  the ideal bit centers at their linked addresses.

## Repository layout

```text
PLAN.md                 this file
README.md               written in phase 1
docs/PROTOCOL.md        stream format and link protocol
tools/vgm2jbs.py        converter
tools/apu_model.py      register-state model used by the tests
tools/gen_crc_table.py  CRC-16 lookup tables for the link ROM
nes/                    jukebox.s (player), ui.inc (screen and controller),
                        fake_link.inc, serial_link.inc, nrom256.cfg
                        (Makefile at the root)
tools/gen_ui.py         tiles, the screen's layout and tables for ui.inc
tools/embed_song.py     song -> build/song.bin + song.inc for the ROM
tools/demo_song.py      original demo tune, so builds need no rips
tools/pcm.py            sampled sound: rates, bytes, and the .pcm file
tools/gen_pcm.py        the link ROM's routines that play it, one per rate
tools/wav2pcm.py, mp32pcm.py, pcm_preview.py
                        make a .pcm file; hear one without a console
host/                   protocol.py (link protocol, host side); the desktop
                        streamer comes in phase 4
firmware/stick/         MicroPython port of host/ for the StickS3, and for
                        the StickC Plus2 as a stand-in (its own README)
tests/                  pytest: converter, protocol, both ROMs on py65, a
                        cycle-exact serial line model, and the Stick
                        firmware against the desktop host
```

Copyrighted VGM rips are never committed. Tests build synthetic VGMs in code,
and local rips go in the git-ignored `music/` directory.

## Phases and milestones

Each phase ends with something runnable. Everything before phase 3 needs no
serial hardware.

1. **Format and converter.** Write `docs/PROTOCOL.md`. Implement `vgm2jbs.py`
   and `apu_model.py` with tests on synthetic VGMs: triggers, deduplication,
   quantization, PAL rescale, loop points, and chained records. Run it on real
   rips in `music/` and read the bytes-per-frame reports to confirm the 7-13
   estimate. *Exit:* equivalence tests pass, and the reports on at least 5
   real rips show p99 bytes per frame under 30. **Done.**
2. **Standalone player ROM (no link).** An NROM-256 ROM with one `.jbs` built
   into PRG, decoded from the NMI through the same ring-buffer path, fed by a
   memcpy "fake link". Run the decoder on py65 in pytest and compare its APU
   writes with `apu_model`. *Exit:* correct playback in an emulator (Mesen2
   recommended) and on a flash cart. **Built and tested on py65:** all five
   rips play frame-exact, with stress and targeted-NMI tests on the ring
   handoff. **Done:** confirmed by ear in Mesen 2 and on real hardware.
3. **Link at 38400, in two parts.**

   **3a. Offline, before the hardware arrives.** Everything that does not
   need a real wire, tested on py65 with a cycle-exact model of the serial
   line (`$4017` reads see the host's bits at the exact CPU cycle; `$4016`
   writes are decoded as the host's UART would):
   - the lean RX and TX routines, with sweeps of baud error, start-bit phase
     and stop bits that report the measured sampling margin;
   - the link-mode ROM: requests, credits, bursts into the ring, CRC, and
     the NMI cutting off a late burst;
   - a Python host protocol module (`host/`), and a whole-system
     simulation joining it to the ROM through the line model, with lost,
     corrupted and late bytes.

   **Done.** `make` builds `build/jukebox_link.nes` beside the standalone
   ROM. Measured in simulation:
   - samples land within 0.12 bit of center at every start-bit phase;
     reception survives host baud error from -4.25% to +6.5%;
   - transmit bits land within 0.62 cycles of ideal and decode at ±3%;
   - full 24-byte bursts land before the next NMI with host turnaround up to
     6.0 ms, which is the budget phase 3b must measure against;
   - late hosts, corrupted and dropped burst bytes, corrupted requests, and
     2% baud error both ways all keep the music frame-exact. The simulation
     found two bugs first: requests went out only every other frame after
     an abort, and a song shorter than the prefill never started.

   **3b. On hardware.** Try `build/jukebox_link.nes` with the desktop host
   first. For finer diagnosis, a loopback ROM: the host sends patterned bursts, the NES
   checks the CRC and replies, the host logs errors and measures `T_turn`.
   Test the FTDI cable first, then the StickS3. *Decides:* 38400 or 57600,
   the `T_turn` budget, and whether mark idle with noisy controller reads is
   acceptable or OUT0 should rest at break with a mark guard (the radar
   approach).
4. **Desktop test host.** `host/jukebox.py`: track list, VGM → `.jbs` on the
   fly, the request/burst server, looping, and next/previous track, over
   the FTDI cable. It is a test fixture, not part of the product: the known
   good cable and the simulation-verified protocol code mean the first
   hardware session tests only the NES side. Keep it lean; tune the FTDI
   latency timer only if resends get in the way of testing. *Exit:* music
   plays over the link on a real console, with the resend rate and reply
   time recorded.

   **Built and tested in simulation.** `host/jukebox.py` streams a playlist
   (`host/playlist.py`) from files or directories, converting rips as it
   loads them. Keys: n, p, r, q. Looping tracks play their loop `--loops`
   times, then the next track follows directly in the same stream (each
   starts with an APU init), always cut at a frame boundary. The status
   line counts requests, bursts, resends and line noise, and shows the
   program's own reply time. Testing it against slow hosts in the
   simulation found and fixed:
   - resends re-sliced by the new credit duplicated stream bytes when an
     older copy was the one committed; resends are now identical;
   - a host steadily slower than about 6 ms got no bursts through at all;
     the NES now waits for the marker across NMIs, times out after 4
     frames, and moves its request later in the frame after a miss;
   - end-of-track was permanent, so a playlist could not continue past it;
     the NES now stays silent until more stream arrives.

   A track change was heard only after the NES's buffer played out (a
   few seconds). The flush burst added in phase 5 makes it immediate; the
   keys are now n, p, s (stop), r (play from the start) and q.

   **Done on hardware:** all five rips play over the FTDI cable on a real
   NES. Resends were 50-60% of requests with the FTDI chip's default
   16 ms latency timer. A first attempt to lower the timer set it to
   232 ms by mistake (macOS takes milliseconds, not microseconds), which
   gave over 80% resends and underruns; `--log` showed reads arriving
   232 ms apart. Chasing that in the simulation found two real ROM bugs,
   both fixed: the request after a late burst did not wait for an NMI
   (a host replying in 6-10 ms lost every other burst), and a burst with
   a damaged length byte could overwrite unplayed music. The NES now also
   reports its link counters to the host.

   **Measured with the timer at 1 ms:** 625 data requests in 40 s with no
   resends, and none of the NES's counters (cut-offs, timeouts, rejects,
   CRC errors, underruns) moved. The request delay stayed at 0, so the
   whole reply, USB included, fits the 6 ms budget. Phase 4's exit is met.

5. **StickS3 host (the product).** Port `host/protocol.py` and
   `host/playlist.py` to MicroPython the way nes-radar does, with parity
   tests against the desktop modules. Convert `.jbs` on the Mac at deploy
   time and store it on the Stick's flash. The LCD shows the track, and the
   buttons control it. *Exit:* music plays from the Stick on a real
   console with no underruns, and the resend rate and reply time are
   recorded. (This was first a 30-minute endurance run with zero
   underruns. The project is a proof of concept, so that run was dropped.)
   *Risk:*
   MicroPython's reply time. If it is too slow, move the reply path to a
   UART RX IRQ handler. If the Stick misbehaves, the desktop test host
   tells whether the fault is on the Stick side or the NES side.

   **Done on the StickC Plus2**, in `firmware/stick/`; the StickS3 is
   still to try. One firmware
   serves the StickS3 and the StickC Plus2 that stands in for it until an
   S3 arrives; `board.py` picks the pins (S3: TX G8, RX G1; Plus2: TX G26,
   RX G36). The hat is the same circuit, but its TX wire sits on a
   different slot for each board, because G0 is on slot 3 of one and slot
   5 of the other.
   - The ports send the same bytes as the desktop modules under random
     requests, noise, resends, skips and restarts, and play frame-exact on
     the simulated NES at 1 ms and 12 ms reply times.
   - For the reply-time risk, the next burst is built while the line is
     idle, so the usual reply is a comparison and one `uart.write`. The
     buttons, the screen (one row at a time) and a forced garbage
     collection run right after a burst goes out.
   - Having read one burst ahead, the Stick applies a track skip one burst
     later than the desktop host, and a NES reset next to a track boundary
     can restart the following track.
   - `tools/deploy.sh` converts the music and copies everything;
     `tools/link_monitor.py` tests the NES-to-Stick direction by itself.

   **On the Plus2, over about two minutes of play:** 1433 bursts with no
   resends, and no cut-offs, timeouts, rejects, CRC errors or underruns
   counted by the NES. Replies took 0.9 ms on average and 3.9 ms at worst,
   `uart.write` 0.1 ms, and the longest garbage collection 3 ms. An
   earlier build ran its idle chores at any time and had about 2.5%
   resends, all bursts cut off by the NES's NMI; running them where no
   request can be due removed those. The longest chore was 20 ms, thought
   to be the USB log line, which is now timed by itself.

   That meets the exit on the Plus2. **Still to do, when an S3 is on
   hand:** move the hat's TX wire to slot 5 and repeat the bring-up steps
   in `firmware/stick/README.md`. Its RX stage has a 100 kΩ base
   resistor, the slowest part of the link at 38400, so scope its edges if
   requests fail to decode there.

   **A throughput test for the Stick and the NES: built, and run on the
   Plus2.** It measures the highest rate at which the link stays reliable,
   so the margin over what music needs (about 3-5 bytes per frame) is a
   number and not an estimate. It lives by itself in
   [`throughput/`](throughput/README.md): a test ROM with receive and send
   routines for a ladder of rates from 9622 baud up, and a Stick script
   that climbs them in each direction, backs off to the fastest rate that
   passes a long trial, and shows the trial in progress on both screens.
   The Stick is in charge there, the reverse of this link, and commands
   always travel at 9622 baud.

   **On a real NES with the Plus2**, with 1024-byte trials: 298296 baud
   to the NES, which is 6 CPU cycles a bit and the fastest the console can
   sample, and 223722 baud from it, where the next rate up failed. To get
   there the test grew two faster receivers: one that samples in 6 cycles
   and counts on what the unused bits of `$4017` read, and one that tracks
   the start bit instead of hunting for it. So 57600 has a very wide margin
   on this hat, which answers phase 3b's choice for the Plus2. The limit
   to the NES is the console's CPU, not the wire: a rate one step past it,
   which needs 120% of the CPU, failed as it should. The jukebox's own
   receiver passed up to 149148 baud in those runs; the test has since
   dropped it for the faster one at every rate. **Still to do:** the S3.

   **Done on the Plus2: start stopped, stop, and instant track
   changes.** Two to-do entries asked for no music until a button is
   pressed, and for the power button to stop and the front button to
   restart. Both rest on one addition to the link, the *flush burst*
   (`docs/PROTOCOL.md`): a burst with marker `$5A` that makes the NES drop
   what it has buffered, silence the APU, and refill before it plays.
   - The Stick starts stopped and answers every request with an empty
     flush burst, so the NES stays silent without timing out.
   - Button A plays the current track from its start. While playing, A and
     B change track, and the power button stops.
   - A NES reset restarts the track if one was playing, and stays stopped
     if not.
   - A stop or a change is heard at once, and the music returns after the
     prefill (about half a second), where it used to take the few seconds
     the NES had buffered. This is the instant skip phase 6 wanted.
   - In simulation: frame-exact through stops, plays and jumps, with a
     noisy line and slow replies as well.
   - On a real NES with the Plus2: every button does what it should, and
     stops, plays and track changes are immediate. The power button is
     read as UIFlow's `M5.BtnPWR`; the S3's is still to try.

   **To do: investigate streaming digital audio.** Find out whether
   sampled sound (raw PCM through `$4011`) can be streamed to the NES
   over this interface. It is a non-goal for v1 because of the numbers:
   38400 baud with 2 stop bits carries at most about 3500 bytes a second,
   so about 3.5 kHz of 7-bit samples even if the NES did nothing else, and
   today the receiver stops for every NMI. Questions to answer: what
   sample rate is the least worth hearing; whether the UART link can reach
   it at 57600 or with a receive loop that writes `$4011` as bytes arrive;
   how samples keep steady timing when the bytes do not; and whether it
   needs the clocked link described under "Future enhancement", which is
   some 40 times faster.

   The throughput test has since put numbers on the UART: on the Plus2 it
   carries 298296 baud to the NES, about 27000 bytes a second, with a
   receiver that samples in 6 cycles. That is the rate of a bare receive
   loop with every cycle used, so it bounds what streaming can reach; at
   223722 baud (about 20000 bytes a second) a quarter of the CPU is free.
   Both are well past the 3500 this entry started from.

   **Investigated, built into the jukebox, and heard on a real NES.** Of
   the ways to make sampled sound on a stock cartridge:
   - *Raw PCM through `$4011`* is the one built. The write costs less than
     the store a receive loop already does (`sta $4011` and a branch are 6
     or 7 cycles; storing and counting a byte is 9 to 11), so it fits at
     every rate. A byte is a sample, the host sends each already scrambled
     the way the fast receiver unscrambles it, and bit 7, which `$4011`
     ignores, marks the end. The host's UART is the clock, so there is
     nothing to keep in step.
   - *The DMC playing DPCM* can only fetch from `$8000-$FFFF`, so it
     cannot play streamed data from RAM. A trick would work on plain NROM:
     pin byte n at `$C000 + 64n`, loop a 1-byte sample, and write each
     received byte to `$4012`, which the DMC reloads at every fetch. It is
     not worth building: 1-bit deltas at 33 kHz reach full level only up
     to about 170 Hz, the DMC eats bytes on the console's clock while the
     host sends on its own, and its fetches take cycles from the receiver.
   - *The pulse channels' volume* is a 4-bit DAC gated by a duty sequencer
     that cannot be stopped: 31 levels from both, for two writes a sample.
     *The noise channel's* is gated by a random bit. Neither is of use.

   A sound is a track in the playlist (`docs/PROTOCOL.md`, part 4). Its
   place in the stream is a sound record; when the NES plays it, it asks
   for the sound, the host answers with a go burst, and from there the
   NES turns its NMI off and writes each byte to `$4011` as it arrives,
   at one of six rates from 7748 to 20338 samples a second, until a byte
   marked as the last. `tools/wav2pcm.py` and `tools/mp32pcm.py` make the
   files, both hosts play them, and `tools/pcm_preview.py` renders what
   the console's DAC would put out.
   - In simulation: every sample reaches the DAC at every start-bit phase
     and with the host's clock 1% off; the music on either side of a sound
     stays frame-exact; a go burst that is lost, damaged or cut short is
     asked for again and the sound plays once; a console that cannot play
     a sound says so and is sent past it; and a console left in a sound
     is freed by the next host to start.
   - A full-scale tone has its noise 41 to 46 dB down in band.
   - While a sound plays the console does nothing else: no screen
     updates, no controller, no clock.

   **On a real NES with the Plus2:** a 30-second clip from an MP3, at
   10169 samples a second, sounded right. So MicroPython keeps the UART
   fed from flash at 10 KB a second, and the go burst, the change of rate
   and the way back to the music all work there.

   **Still to try on hardware:** the other five rates, 20338 samples a
   second above all, where the Stick must find 20 KB a second; the Stick's
   buttons during a sound; the desktop host, and whether an FTDI cable
   takes these baud rates; and the S3.

   **Looked at and left out, this being a prototype:** a running clock
   and the controller during a sound. Both are possible at the three
   slower rates (21, 16 and 14 cycles a bit), where the gaps between a
   byte's samples are 8 cycles or more: the stream routine would poll
   `$2002` for vblank once a byte, and in the vblanks it finds count
   frames, read controller 1, and write the clock's digits, a fixed-length
   step to a gap, with X and Y only, since A holds the byte. A press would
   have the NES leave the sound by itself and send something the host
   cannot miss, as the host is not listening at 38400. At 12 cycles a bit
   and under the gaps are too short. Button A alone can be read with OUT0
   at rest, in 8 cycles, at four of the six rates. A clock on the Stick's
   own screen would cost next to nothing.
6. **Polish, including the user interface.** UI enhancements were
   deliberately deferred until the link works, because screen updates must
   fit around the receive window that phase 3 defines. Planned: a
   title/metadata screen with the track name, track number and position,
   controller navigation (next, previous, pause), and link and buffer
   status (underruns, CRC retries). Also fade-out by scaling envelope
   volumes on the StickS3.

   **Done: the screen and the controller.** Built, tested in simulation,
   and seen working on hardware: the screen, the clocks, the controller
   and the Stick's buttons all do what they should.
   - Both ROMs show the title, the game's name and the track's name on a
     line each, a clock (position / length), a status line (waiting for
     the link, press Start, loading; blank once a track is on the screen),
     and 28 bars that follow the music. While the music is paused or
     stopped the clock flashes. Under the title, in a 3 x 5 font, is a
     credit line. `tools/gen_ui.py` makes the tiles, the nametable and the
     tables, and can write the screen as a PNG.
   - The names and the length arrive in the stream: three control records
     (`$80 $03`, `$02`, `$04`), which the hosts put ahead of each track.
     They are drawn as the track's first notes play, so they are right
     however much the NES had buffered. Nothing changed in the `.jbs`
     files. The NES's clock counts the frames it plays from the length
     record on.
   - The Stick shows the same clock. The NES does not report its position,
     so the Stick works it out: the NES plays a frame per vblank from the
     moment its buffer reached the prefill. Its screen lost the NES
     counters row (they stay in the USB log) and says plain `STOPPED`.
   - The bars are drawn from the stream's APU writes, not from sound. Each
     channel lights the bar for its pitch to its volume, and bars fall by
     themselves. Length counters, envelopes, the triangle's linear counter
     and `$4015` are followed, so a note the console stops is stopped on
     the screen. Sweeps are not followed.
   - Controller 1: Right and Left change the track, Start or A pauses and
     resumes (a *pause burst*, `$3C`: the NES holds the music and keeps
     its buffer, so it goes on from the same frame). The Stick's buttons
     now do the same three things: A pauses, B is previous, power is next. The NES sends a button request (`$42`) and the host acts on
     it, the desktop host and the Stick alike. On the standalone ROM Start
     pauses.
   - Reading the controller means pulling OUT0 low, which is the serial
     line. The read is one low pulse of 94 cycles at the start of the NMI;
     the host's UART receives it as `$FE` once a frame, and both decoders
     pass over it without counting noise. In the simulation it never comes
     within 12 bit times of a request, and decodes cleanly at ±3% baud.

   **What the screen costs the link.** All of it runs in the NMI, before
   the main loop's request: the PPU writes must be in vblank, and nothing
   may run during a burst. Measured on py65 over the five rips: the NMI's
   median went from about 0.2 ms to 1.1 ms (2000 cycles) and its 99th
   percentile from 1 ms to about 2 ms; a track's opening frame, which also
   copies the title, runs to 4.4 ms. PPU writes end at most 1200 cycles
   into the 2273 of vblank. A frame draws the title, or the status line,
   or the changed bars of one half of the display, which is what keeps
   that bounded.

   The host's reply budget fell from 6.5 ms to 5.5 ms. (The earlier 6.0 ms
   figure came from a harness that started each frame when the NMI handler
   returned, which hid the handler's time; it now starts frames a fixed
   period apart.) The Stick's replies measured 0.9 ms on average and
   3.9 ms at worst, so there is room, but less. `CREDIT_MAX` 20 in place
   of 24 would give 7 ms, at the cost of a prefill of 38 frames for 32.

   **Not yet measured on hardware:** the resend share and the NES's
   counters with the screen running, to compare with phase 5's figures;
   whether the hosts' noise counts stay still with a `$FE` arriving every
   frame; and how far the Stick's clock drifts from the NES's.

   **Still to do here:** the track's number, the link's counters on the
   screen, and fade-out.
7. **Optional: preload and DPCM.** Target a board with 8 KB PRG-RAM, or a
   flash cart that provides it, for a larger buffer or whole-loop preload
   with LZ-compressed `.jbs`. For DPCM: a cartridge with RAM or writable
   flash in `$C000-$FFFF` to load sample blocks (VGM data block type `0xC2`),
   then re-verify receive timing, because DMC DMA takes cycles from the CPU.

## Future enhancement: clocked link (controller emulation)

This is not scheduled. Revisit it after phase 3 if the UART link is
marginal or more bandwidth is wanted.

Every `$4017` read pulses port 2's CLK pin, which is what a controller's 4021
shift register uses to present its next bit. If the host watches CLK and puts
the next bit on D0 after each pulse, it behaves like a controller, and the NES
sets the pace:

- No baud rate and no cycle counting. An NMI or DMA in the middle only pauses
  the transfer, it doesn't corrupt it.
- About 8-12 cycles per bit in a read loop, roughly 150-200 kbps. D3 and D4 on
  port 2 could carry 2 more bits per read. (The throughput test later got
  the UART link itself to 6 cycles per bit, 298 kbps on the wire, so on
  rate alone this is no longer ahead; what it still offers is that an NMI
  only pauses a transfer.)
- Wiring: add CLK on pin 2, with another level-shifting stage. Suggested
  roles: OUT0 as select, CLK as clock, D0 (and D3/D4) as data.
- The host must have the next bit ready within a few microseconds of each
  CLK pulse. That rules out MicroPython (its ESP32 SPI is master-only) and
  the FTDI cable. Candidates are an ESP32 hardware SPI slave written in
  ESP-IDF or Arduino, or an RP2040, whose PIO state machines can emulate a
  4021 exactly.
- NES-to-host requests need a new path, because OUT0 becomes the select
  line. Options are OUT0 pulse patterns, or UART only between transfers.

The stream format, ring buffer, NMI player and converter carry over
unchanged. Only the link layer changes.

## Risks and open decisions

- **Host turnaround (`T_turn`)** is the biggest unknown, especially under
  MicroPython. Phase 3 measures it before anything depends on it.
- **Receive margin at 38400:** 9 cycles of hunt jitter against a 46.6-cycle
  bit, and the ESP32's baud accuracy. The loopback spike's error rate is the
  test.
- **VGM coverage:** some rips update the APU more than once per frame. The
  quantization report flags these.
- **License:** code adapted from nes-radar (the TX technique, the CRC, and
  the host decoder) is GPL-3.0 there. Decide whether nes-jukebox is GPL-3.0
  as well, or reimplements those parts.
- **Validation boundary:** as in nes-radar, offline tests prove instruction
  timing and byte formats only. Voltage levels, USB latency and real sampling
  margin need real-console acceptance, recorded per host.
