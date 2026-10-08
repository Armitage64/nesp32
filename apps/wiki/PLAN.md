# NESpedia: a Wikipedia reader for the NES

> **October 2026: the Stick's side has moved to [nesp32](../..).** This
> plan is the record of how NESpedia was designed and brought up with a
> MicroPython firmware and a link protocol of its own. The ROM's design
> below still stands. The firmware it describes (`firmware/stick/`), its
> protocol and its tests are gone from this tree, though not from its
> history: the text code was ported to C as nesp32's WIKI service, and the
> link is nesp32's. See [`README.md`](README.md) and
> [`docs/PROTOCOL.md`](docs/PROTOCOL.md) for how things are now.

## Context

`../jukebox` proved the controller-port-2 link between a stock NTSC NES
and an M5Stack Stick (UIFlow 2.0 MicroPython, NPN level-shifter hat), and its
`throughput/` test put numbers on it. This project uses that same hat and
wiring for a different job: type a search term on the NES, have the Stick
fetch the Wikipedia article over Wi-Fi, strip it to plain text, and read it
on the NES with smooth scrolling.

Everything is new, built from the jukebox's and nes-radar's patterns.

**Status: all five phases are done. It works on a real NES with a StickC
Plus2.** Each phase below says what was found.

**Guiding rule (from review): throughput is not critical. Where there is a
choice, take the safer and simpler one over the faster one.**

### What the throughput data says, and what it decides

Measured on a real NES with a StickC Plus2 (`../jukebox/throughput/README.md`):

| Direction | Fastest stable | Limit |
|---|---|---|
| Stick to NES, fast receivers | 298296 baud | the console's CPU |
| Stick to NES, the jukebox's kind of receiver | 149148 baud (12 cycles/bit) | every rate it was given passed |
| NES to Stick | 223722 baud (8 cycles/bit) | hat RX stage / UART |

- The fast receivers buy speed by assuming `$4017` reads `$40` at rest and
  by leaving bytes scrambled for a table to fix. This project does not need
  the speed, so it does not use them.
- Nothing may take cycles mid-byte, so an NMI must never land inside a
  receive. The jukebox sized each exchange to fit between vblanks and let
  the NMI abort a late one (`rx_abort`).
- Changing the ESP32 UART's rate leaves a junk byte in its receiver.
- MicroPython replied in 0.9 ms on average, 3.9 ms at worst.

Decisions:

1. **The jukebox's plain receiver** (`lda $4017 / lsr / ror`, a 9-cycle
   start-bit hunt): no assumption about the port's unused bits, no
   unscramble table, and the most hours on hardware.
2. **One rate, both ways, never changed: 21 cycles/bit, 85227 baud.** It is
   on the ladder both directions passed on hardware, 1.75 times below where
   this receiver was still passing and 2.6 times below the NES-to-Stick
   limit. It is not 38400 because of decision 4: a whole line has to fit in
   the part of a frame left after the header, and this is the slowest ladder
   rate that leaves the Stick more than its worst measured reply time. One
   shared constant sets it for both sides.
3. **The article lives on the Stick; the NES pulls it a line at a time.**
   The NES has 2 KB of RAM; the default article is over 100 KB. The Stick
   wraps the text into fixed 28-byte lines, so line *n* is a slice at
   `28 * n`, and the NES asks by line number, at most one line per frame.
4. **The jukebox's header stays on screen, so the text scrolls under a
   split.** Rows 0-7 are the header; rows 8-29 are a 22-row, 28-column text
   window. The ROM waits for a sprite-0 hit in the header each frame and
   then sets the text's scroll. The link exchange runs after the split, in
   the ~20000 cycles before the next vblank:

   | Step | Cycles |
   |---|---|
   | Request, 7 bytes, 8N1 | 1470 |
   | Reply, 36 bytes, 8N2 | 8316 |
   | Left for the Stick's turnaround | ~9300 (5.2 ms, measured in simulation; the jukebox's Stick took 3.9 at worst) |

   Checking the CRC is not timing-critical and runs after the receive.
5. **One nametable is the NES's line cache.** With vertical mirroring,
   nametable 0 is a 30-row ring of text (line *n* in row `n mod 30`) and
   nametable 1 holds the header and the search screen. 23 rows can show, so
   7 are spare for lines fetched ahead of the view. Scrolling is clamped to
   what is loaded, so a late or lost reply only pauses the scroll and never
   shows a stale row.
6. **Scroll speed is capped at 4 pixels a frame**, one line every other
   frame, so half the frames are spare for a repeat.
7. **Read while it arrives.** The plan was fetch, then read. On hardware
   the wait before any text was long, so the Stick now offers an article
   as soon as its first 28 lines are laid out, and the console learns its
   growing length from every reply (docs/PROTOCOL.md). Laying out made the
   Stick slow to answer, and so the scroll jerky, for as long as a long
   article took to come in; so the Stick now fetches only a few pages ahead
   of the reader (`fetch.py`), and makes the search again, passing over
   the lines it has, if the paused connection is dropped.

## Screens

Header, on both screens, as `../jukebox/tools/gen_ui.py` builds it
(`big_letter`, `small_text`, `SMALL_FONT`, `PALETTE_LOGO`, `palette_rows`):

- **`NESpedia`** in the 2 x 2-tile logo letters on row 3, centered, in the
  logo palette's three blues with the shadow.
- **`RETRO BITS (2026)`** in the 3 x 5 small font on row 6, in the middle blue.
- The jukebox's font has capitals only. Lowercase glyphs are added (the body
  text needs them anyway), so the logo reads `NESpedia` as written; all
  capitals is a one-constant change if it looks better.

```text
 SEARCH (nametable 1)               READER (header + nametable 0)
 row 3   N E S p e d i a            row 3   N E S p e d i a
 row 6    RETRO BITS (2026)         row 6    RETRO BITS (2026)
 row 10  SEARCH                     ---- split at scanline 64 ----
 row 12  [Nintendo Entertainment…]  rows 8-29: 22 lines of 28 columns,
 row 14+ on-screen keyboard                    scrolled by the pixel
 row 24  status / message
 row 26  help line                  sprites: scroll thumb at the right edge
```

Controller 1:

| | Search | Reader |
|---|---|---|
| Up / Down | move over the keys | scroll, 2 px a frame |
| Left / Right | move over the keys | page up / down, animated at 4 px a frame |
| A | type the key | page down |
| B | backspace | page up |
| Select | lower / upper case | back to search |
| Start | search | top of the article |

The field holds 30 characters and starts as `Nintendo Entertainment System`,
which is 29: one more than a line of the article, so the field is two
columns wider than the text and the link's limit is 30.

## Architecture

```text
 NES (NROM-256, ca65)                       Stick (UIFlow 2.0 MicroPython)
   ---- SEARCH id, "Nintendo Ent..." ---->  Wi-Fi from UIFlow's NVS settings
        (again every 8 frames, as a poll)   HTTPS GET en.wikipedia.org API
   ---- LINE n  (at most one a frame) --->  stream JSON -> ASCII -> wrap to
   <--- 36-byte reply ---------------------  28-byte lines in a RAM buffer
```

### Link protocol (`docs/PROTOCOL.md`)

Wiring, inversion and pins are the jukebox's (`firmware/stick/nesjuke/board.py`).
CRC is CRC-16/CCITT-FALSE, as on both earlier links.

```text
NES -> Stick, 8N1   $57, OP, LEN, PAYLOAD[LEN], CRC_HI, CRC_LO
Stick -> NES, 8N2   $A5, STATE, LINE_LO, LINE_HI, TOTAL_LO, TOTAL_HI,
                    TEXT[28], CRC_HI, CRC_LO          always 36 bytes
```

| OP | Payload | Reply |
|---|---|---|
| SEARCH | an id, and the query, up to 30 characters | the state of that search; `LINE` is `$FF` and the id |
| LINE | line number, 16 bits | that line; `LINE` echoes the number, so a stale reply is passed over |

- Every reply is the same length: one receive routine, a fixed count.
- `STATE`: `IDLE`, `NO_WIFI`, `FETCHING`, `READY`, `NOT_FOUND`, `ERROR`.
- **SEARCH is also the poll.** The console sends the same search, with the
  same id, every 8 frames until it ends. The Stick fetches when the id or
  the words are new and otherwise reports. This replaced the STATUS request
  first planned: with a separate poll, a lost SEARCH followed by a STATUS
  would have been answered READY for the *previous* article.
- `TEXT` bytes are tile numbers: ASCII, with bit 7 set on heading lines (the
  same glyphs in a second colour). With `ERROR` it is a message for the
  console's status line.
- No reply, a bad marker, a bad CRC or a reply cut off by the NMI all mean
  the same thing: ask again. While the Stick is inside the TLS handshake it
  does not answer; the console keeps `SEARCHING...` up and keeps asking,
  and gives up with a message after 30 s of silence.
- A good LINE reply that says the Stick is not READY means it has lost the
  article; the console goes back to the search screen and says so.

### NES ROM (`nes/`)

- **`nespedia.s`**: reset, NMI, and the states SEARCH, LOADING, OPENING
  (the ring's first lines are being fetched) and READER; messages go on the
  search screen's status line. The NMI does OAM, at most one 28-tile row, the header's scroll, and the
  controller read (one 94-cycle low on OUT0 a frame, as `ui_vblank` in
  `../jukebox/nes/ui.inc`; the Stick's decoder passes over the junk byte).
- **`split.inc`**: sprite 0 sits on a lit pixel of the credit line, in its
  colour, so it cannot be seen. The main loop waits for the hit, counts to
  the hblank before scanline 64, and writes the text's scroll with the
  `$2006/$2005/$2005/$2006` sequence. A bounded wait, so a missed hit costs
  a frame and not a hang.
- **`serial_link.inc`**: send a request, receive 36 bytes, check.
  `tools/gen_link.py` writes the cycle-timed routines at the shared period
  (`build/link.inc`), from the generators in
  `../jukebox/throughput/tools/gen_rates.py` (`receiver`, `sender`,
  `delay`, `one_page`), with the receive made a fixed-count block: 25
  cycles from a byte's last sample to the next hunt. The NMI ends an
  exchange that runs late by returning to `rx_abort`, as in
  `../jukebox/nes/serial_link.inc`. `fake_link.inc` is the standalone
  ROM's host: the same four routines, served from PRG.
- **`reader.inc`**: `top_line` (16 bits) and `fine` (0-7) are the position;
  `lo_line`..`hi_line` is what the ring holds. Each frame: move toward the
  target if the next row is loaded; ask for the next line in the direction
  of travel if fewer than 3 are in hand. A good reply goes to a staging
  buffer that the next NMI writes to a row outside the window.
- **`keyboard.inc`**: the field and the key grid on nametable 1.
- **`tools/gen_screen.py`**: tiles, the search screen's nametable, the
  layout's constants and preview PNGs. Tiles `$20-$7F` are the font in
  white; `$A0-$FF` the same in the logo's blue, for headings and for the
  keys, of which the one under the cursor is white; the logo and credit
  tiles take what is left.

### Stick firmware (`firmware/stick/neswiki/`)

Plain Python that runs on the desktop under pytest and unchanged on the
Stick, with a thin hardware module, as in the jukebox:

| Module | Purpose |
|---|---|
| `linkrate.py` | the one period, baud and frame sizes; `gen_link.py` reads it too |
| `proto.py` | frames, table-driven CRC, a request decoder that resyncs a byte at a time |
| `wikitext.py` | the API URL; a streaming scanner fed chunks of the JSON body that finds `"title"` and `"extract"`, decodes JSON escapes and UTF-8, and maps to ASCII (accents to base letters, typographic quotes and dashes, `?` for the rest) |
| `wrap.py` | greedy wrap to 28 columns into a preallocated bytearray; `== Heading ==` lines become flagged heading lines with a blank line before |
| `server.py` | answers requests from the buffer, through a port object (`read`, `write`); whoever owns it does the fetching |
| `net.py` | Wi-Fi and HTTPS, from `../../../nes-radar/firmware/stick_s3/nesradar/net.py`: raw socket and `ssl`, HTTP/1.0 so the body is never chunked, a User-Agent (Wikimedia requires one), optional `/flash/ca.der` |
| `board.py`, `ui.py`, `device.py` | pins and UART per board, the LCD, the main loop (UIFlow only) |

- One request searches and fetches:
  `action=query&generator=search&gsrsearch=<q>&gsrlimit=1&prop=extracts&explaintext=1&format=json&formatversion=2`.
  Wikipedia turns the page into text; the Stick strips the JSON, the
  character set and the layout. Checked against a recorded reply in phase 1.
- The body is read in 1 KB chunks, and the UART is served between chunks so
  the console's poll gets `FETCHING`.
- Every article ends with two lines naming Wikipedia and its licence.
- The article buffer is allocated once at start (256 KB, about 9000 lines)
  and reused; a longer article ends there with a line saying so.
- Wi-Fi credentials come from UIFlow's NVS (`uiflow_wifi()` in nes-radar's
  `device.py`), never from a file. `set_wifi.py`, `stick_repl.py`,
  `deploy.sh` and `restore_uiflow.sh` are copied from the earlier projects.
- LCD: Wi-Fi state, the article's title, lines, requests and bad frames.

The repo stands alone: these pieces are copied and adapted, not imported by
relative path, with a note of where each came from.

## Phases

Each ends with something runnable; 1 to 3 need no serial hardware.

1. **Scaffold and text pipeline.** `git init`, `.gitignore`, Makefile, venv
   (`pytest`, `py65`, `pyserial`), `PLAN.md` (this document), `docs/PROTOCOL.md`.
   `wikitext.py`, `wrap.py` and `tools/wiki_preview.py "query"`, which fetches
   with `urllib` and prints the 28-column lines. *Exit:* the default article
   reads well in a terminal; fixture tests pass.
   **Done.** The API's reply is as expected (title, then extract, raw
   UTF-8), so one request is enough. The default article is 62 KB of reply
   and about 2530 lines. A search that finds nothing has no `query` in its
   reply.
2. **Reader ROM with a built-in article.** Header, font, the split, the
   30-row ring, scrolling, paging and the thumb, fed by a "fake link" that
   copies lines from PRG (the jukebox's `fake_link.inc` idea), so it runs in
   Mesen and on a flash cart. `tools/embed_article.py` builds the article
   from a text file. *Exit:* scrolls cleanly end to end in Mesen 2 with a
   steady header; py65 tests pass.
   **Built; passes on py65; not yet seen in an emulator.** No emulator is
   installed on the build machine, so Mesen is still to do. On the
   simulated console every frame of every reader test shows exactly the
   article's lines at the scroll's place, through random buttons and a host
   that fails 40% of the time; the split's last write lands on dots 283 to
   315 of the hblank it must hit (257 to 340) at every phase of the
   polling; and the NMI takes at most 1176 cycles of the vblank's 2273.
3. **Search screen.** Keyboard, field, default text, the states and
   messages. On the standalone ROM, Start opens the built-in article.
   **Built; passes on py65.**
4. **Link, in simulation.** `gen_link.py`, `link.inc`, `proto.py`,
   `server.py`, and the link ROM `build/nespedia_link.nes`. *Exit:* the
   whole-system test below passes.
   **Built; passes.** The link ROM and the Stick's real `server.py` run
   together over a cycle-exact line. Found on the way:
   - a line's reply lands with the Stick taking up to 5.0 ms, and is cut
     off at 5.25 (the first estimate was 5.7);
   - samples fall within 0.25 bit of mid-bit at every phase, and the
     Stick's clock may be 3% out either way;
   - a Stick answering in 1 ms never makes the scroll or a page's glide
     wait; one that is always late stops the scroll and nothing else;
   - damaged, cut, lost and junk-prefixed replies (35% of them) never
     reach the screen.
5. **Stick, on hardware (StickC Plus2).** `net.py`, `device.py`, deploy.
   Bring-up in the jukebox's order: boot check with the hat on, NES-to-Stick
   only, then a search. Record reply times, bad frames and aborts.
   **Done on a StickC Plus2:** searching, reading, and smooth scrolling by
   the line and by the page. The ROM needed no change to its link or its
   split; everything found was on the Stick, and in this order:
   - *No article ever came.* Storing a line into a slice of the article's
     buffer made MicroPython move the whole 256 KB after it, for every
     line, so a fetch took minutes and the console gave up after its 30
     seconds. Lines are now written through a view of the line alone.
   - *A long wait before any text.* The Stick had fetched everything
     before saying READY. It now offers an article once 28 lines are laid
     out (decision 7).
   - *Jerky scrolling while a long article came in.* The Stick now lays
     out only two pages ahead of the furthest line it has served, a piece
     of 96 bytes at a time, and while the console is asking every frame it
     starts a piece only in the 7 ms after a reply has gone out.
   - *Jerky scrolling still, with nothing being fetched.* Nearly half of
     all requests were found a frame late, in every log. The cause was
     `uart.read()`, which makes a new 256-byte buffer on every call, data
     or none. Called 600 times a second, that was 150 KB of garbage a
     second; UIFlow collects every 20 KB; and a collection takes 70 ms
     with the article's buffer in the heap (7 ms without). The Stick was
     collecting about half the time. It now asks `uart.any()` and reads
     into a buffer it keeps, and collects only when the console is quiet.
     This was found from the Stick's own log, which times every part of
     its loop (`firmware/stick/README.md`, "The USB log").
   - Two guesses made on the way were wrong and are worth knowing as
     such: that the heap was short of room (1.2 MB was free throughout),
     and that the housekeeping after each reply was the delay.

   Also from that session: the search screen's prompt and box, and the
   cursor's key shown by a palette whose colour pulses.

   The loop is also tested against stand-ins for UIFlow's modules
   (`tests/test_device.py`), which found before any hardware did that the
   server's idea of whether Wi-Fi was up did not follow the network.

   **Still to do:** the StickS3; a long session; Mesen.
6. **Later, unscheduled.** A list of search results to pick from, section
   jumps, history, the StickS3, a desktop host on the FTDI cable.

## Verification

- `make` builds `build/nespedia.nes` (standalone) and
  `build/nespedia_link.nes`; `make verify` checks size and header as
  `throughput/Makefile` does.
- `make test` (pytest):
  - **Serial timing**: every `$4017` read and `$4016` write of the generated
    routines against ideal bit centers at their linked addresses, across
    start-bit phases and host clock error (pattern:
    `throughput/tests/test_thru_rates.py`), reporting the margin.
  - **Text**: escapes, surrogate pairs, UTF-8 split across chunk boundaries,
    transliteration, long words, headings, not-found; one trimmed recorded
    API response as a fixture.
  - **Reader on py65**: with simulated controller input, the rows in the
    window always equal the article's lines at the scroll position; top and
    end clamp; paging lands on the right line; the split's writes fall at
    the same cycle after the hit every frame.
  - **Whole system**: the link ROM and the real `server.py` joined by a
    cycle-exact line with NMIs a fixed frame apart (adapted from
    `throughput/tests/thru_sim.py` and `../jukebox/tests/link_harness.py`):
    search, load, scroll through an article; then with dropped and damaged
    bytes, replies up to and past the budget, a Stick that goes silent
    mid-fetch, and a NES reset mid-article.
- By eye: `gen_screen.py --preview` for both screens beside
  `../jukebox/docs/screen.png`; the standalone ROM in Mesen 2.
- On hardware: the default search end to end; hold Down through the whole
  article and page both ways, with the Stick's log showing no bad frames.

## Risks

These were the risks before hardware. None of the three came to anything
on the Plus2:

- **The split.** A sprite-0 wait is jittery by a few cycles; the writes are
  aimed at hblank, and the row above the text is blank, to hide it.
- **Reply time under MicroPython with Wi-Fi up.** Once the Stick stopped
  making garbage it answers in a millisecond or two, as the jukebox's did.
- **Memory on the Plus2** (2 MB PSRAM) for TLS plus a 256 KB buffer: 1.2 MB
  is free with the buffer allocated. What the buffer costs is time, not
  room: every collection reads through it.
- **PAL** is out of scope, as before.
