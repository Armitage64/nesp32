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

Non-goals for v1:

- DPCM sample playback. The DMC can only fetch from `$C000-$FFFF`, which is
  cartridge ROM, not NES RAM. See phase 7.
- Raw PCM through `$4011` (voice or drum streams). It is thousands of writes
  per second and cannot be streamed. Occasional `$4011` level writes are
  kept, because the level changes the triangle and noise mix.
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
   with a long cable. The CPU is the limit, and the budget holds:

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
- **RAM map:** zero page for player state; `$0100` stack; `$0200` OAM shadow;
  `$0300-$03FF` player and link state, including a 64-entry staging list;
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
- **NMI:** save registers, OAM DMA, decode exactly one frame (or consume one
  frame of a wait), read controller 1, and increment a frame counter. On
  underrun, write nothing: the notes hold, and an underrun counter
  increments. If `rx_active` is set, rewrite the stacked return address to
  `rx_abort` before `rti`.
- **Main loop:** wait for the frame counter to change. Handle buttons (send a
  `B` request). If ring space is at least the minimum burst, compute
  `CREDIT = min(space, bytes_that_fit(time_left))`, send the request, set
  `rx_active`, receive, verify the CRC, commit, and clear `rx_active`.
- **Screen (v1):** a static title screen, the track number and title from a
  metadata record, and debug counters for underruns, CRC failures and aborts,
  like nes-radar's `ERROR n` field.
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
nes/                    jukebox.s (player), fake_link.inc, serial_link.inc,
                        nrom256.cfg (Makefile at the root)
tools/embed_song.py     song -> build/song.bin + song.inc for the ROM
tools/demo_song.py      original demo tune, so builds need no rips
host/                   protocol.py (link protocol, host side); the desktop
                        streamer comes in phase 4
firmware/stick_s3/      MicroPython port of host/
tests/                  pytest: converter, protocol, both ROMs on py65, and
                        a cycle-exact serial line model
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
   time recorded. The long endurance run belongs to the StickS3 (phase 5).

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

   A track change is heard after the NES's buffer plays out (a few
   seconds). Instant skip needs a flush command on the NES, which belongs
   with the UI in phase 6. **Still to do on hardware:** play over the link
   and record the resend rate and reply time.

5. **StickS3 host (the product).** Port `host/protocol.py` and
   `host/playlist.py` to MicroPython the way nes-radar does, with parity
   tests against the desktop modules. Convert `.jbs` on the Mac at deploy
   time and store it on the Stick's flash. The LCD shows the track, and the
   buttons control it. *Exit:* 30 minutes of continuous playback on
   hardware with zero underruns; resends logged and recovered. *Risk:*
   MicroPython's reply time. If it is too slow, move the reply path to a
   UART RX IRQ handler, or prebuild bursts so a reply is a single
   `uart.write`. If the Stick misbehaves, the desktop test host tells
   whether the fault is on the Stick side or the NES side.
6. **Polish, including the user interface.** UI enhancements were
   deliberately deferred until the link works, because screen updates must
   fit around the receive window that phase 3 defines. Planned: a
   title/metadata screen with the track name, track number and position,
   controller navigation (next, previous, pause), and link and buffer
   status (underruns, CRC retries). Also fade-out by scaling envelope
   volumes on the StickS3.
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
  port 2 could carry 2 more bits per read.
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
