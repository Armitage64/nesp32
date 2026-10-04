# NES Jukebox

Stream music from NES `.vgm` rips to a real NES over the controller-2
serial link from [nes-radar](../nes-radar), and play it on the console's own
APU.

A proof of concept, and work in progress. See [`PLAN.md`](PLAN.md) for the design and phases, and
[`docs/PROTOCOL.md`](docs/PROTOCOL.md) for the stream format and link.

## Status

- **Phase 1, done:** the converter from `.vgm`/`.vgz` to the `.jbs` jukebox
  stream.
- **Phase 2, built:** a player ROM with one song built in, decoded from the
  NMI through the ring buffer the serial link will fill later. It is tested
  on a 6502 emulator (py65), where every song plays frame-exact, and
  confirmed by ear in Mesen 2 and on real hardware.
- **Phase 3a, done:** the serial link ROM, `build/jukebox_link.nes`, and the
  host side of the link protocol. Verified against a cycle-exact model of
  the serial line, including late hosts, line noise and baud error.
- **Phase 4, done:** the desktop test host, `host/jukebox.py`. It plays
  all five test rips on a real NES over the FTDI cable with no resends. It
  is for testing and diagnosis; the product's host will be the M5StickS3
  (phase 5).
- **Phase 5, done on the Plus2:** the Stick firmware, in
  [`firmware/stick`](firmware/stick/README.md). It runs on the M5StickS3,
  and on an M5StickC Plus2 as a stand-in until an S3 is on hand. It has
  played music on a real NES from the Plus2 with no resends; the S3 is
  still to try.
- **Phase 6, working:** the console's screen and controller. Both ROMs
  show the title, the game and track names, a clock, a status line and
  bars that follow the music, and controller 1 plays, pauses and changes
  tracks. See "The screen" below.
- **Link throughput, measured:** a separate test ROM and Stick script in
  [`throughput`](throughput/README.md) find the fastest rate the link
  holds in each direction. On a real NES with the Plus2: 298296 baud to
  the console (about 27000 bytes a second), where its CPU has no cycles
  left, and 223722 baud from it. A receiver built the way the jukebox's
  is passed up to 149148 baud, about four times the 38400 it runs at.

## Building the ROM

Needs [cc65](https://cc65.github.io/) (`ca65`, `ld65`).

```sh
make                                      # original demo tune
make SONG="music/01 Running About.vgz"    # any rip, or a .jbs
```

`make` builds two ROMs: `build/jukebox.nes` with the song built in, and
`build/jukebox_link.nes`, which fetches the song over controller port 2.

The standalone ROM is `build/jukebox.nes` (NROM-256, mapper 0). Open it in an emulator
such as Mesen, or copy it to a flash cart. A song can be up to 24 KB of
stream, which covers every rip tried so far (6-14 KB).

## The screen

![The screen while a track plays](docs/screen.png)

Both ROMs show the same screen: the title, the game a track came from and
the track's name on a line each, a clock with the position and the track's
length, a status line, and 28 bars that follow the music. The clock counts
the frames the console has played, so it stops when the music does.

The bars are not a spectrum of the sound, which the console cannot hear.
They are drawn from what the stream writes to the APU: each channel lights
the bar for its pitch (four bars to the octave, C1 at the left) to the
height of its volume, and the bars then fall by themselves. The noise
channel sits on the right by its period.

Controller 1:

| Button | Link ROM | Standalone ROM |
|---|---|---|
| **Start** or **A** | pause, resume; from stopped, play the current track from its start | pause, resume |
| **Right** | next track, and play it | |
| **Left** | previous track, and play it | |

While the music is paused or stopped the clock flashes.

On the link ROM the controller only asks: the press goes to the host as a
button request, and the host changes the track as it does for its own
buttons, so the name on the screen changes when the new track's first
frame plays, about half a second later.

The tiles, the screen's layout and the lookup tables all come from
`tools/gen_ui.py`, which `make` runs. `tools/gen_ui.py build --preview
screen.png` writes the still screen as a picture, to check a change to the
layout without a console.

For debugging, [Mesen 2](https://www.mesen.ca/) can import
`build/jukebox.dbg` (cc65 debug info), so its debugger, memory viewer and
watch list show the ROM's labels, such as `head`, `tail`, `underruns` and
`stream_error`. A write breakpoint on `$4000-$4017` stops at each frame's APU
writes.

## Streaming to a NES (test host)

The desktop streamer is a test and diagnosis tool; the finished jukebox's
host is the M5StickS3. With the link ROM running on the console and the
serial cable from nes-radar connected:

```sh
.venv/bin/pip install -r host/requirements.txt   # pyserial
.venv/bin/python host/jukebox.py --list-ports
.venv/bin/python host/jukebox.py --port /dev/cu.usbserial-XXXX music/
```

Keys: `n` next track, `p` previous, space to pause and resume, `s` stop,
`r` play the current track from its start (also after a stop), `q` quit. `--loops N` sets how many
times a looping track plays before the next one, `--repeat` starts the
playlist over at the end, and `--stopped` starts silent until `r`, as the
Stick does. The status line shows
requests, bursts and **resends**; a resend is a burst the NES missed, and a
steady trickle of them means the host is replying too slowly (see
docs/PROTOCOL.md, Timing). A track change, stop or restart is heard within
about a second: the host's next burst tells the NES to drop the music it
has buffered.

The status line ends with the NES's own counters, which say *why* bursts
were asked for again: `aborts` (a burst was cut off by the next vblank, so
the reply came too late), `timeouts` (no reply arrived), `rejects` and
`crc_errors` (bytes were damaged on the wire), and `underruns`. They are
totals since the program first heard from the console. `--log FILE` writes every read and
request with its time, which is the first thing to look at when resends are
high.

The program asks the USB serial driver for 1 ms of receive latency
(`--latency-ms`, 0 to leave it alone). With an FTDI cable's default of 16 ms
about half of all requests are repeats, though the music still plays; at
1 ms the same cable ran with none.

## Streaming from a Stick

```sh
firmware/stick/tools/deploy.sh          # converts music/ and copies it over
```

See [`firmware/stick/README.md`](firmware/stick/README.md) for the hat's
wiring on each board, setup, and the order to bring things up on hardware.

## Converting music

```sh
python3 tools/vgm2jbs.py music/*.vgz --out-dir build/jbs
python3 tools/vgm2jbs.py song.vgm -o song.jbs --report song.json
```

Each conversion prints the stream size and bytes per frame (mean, 99th
percentile, maximum, worst second), plus anything it had to drop, such as
DMC writes and data blocks, FDS writes, or other chips.

VGM rips are copyrighted. Keep them in `music/`, which git ignores.

## Tests

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

`make test` does the same. The ROM tests build both ROMs and run them on
py65, so they need cc65; they skip without it. The full suite takes several
minutes, mostly the serial link simulation.

The tests build synthetic VGM files in code. The central test encodes
random register writes, decodes the stream, and checks with the APU
write-order model that every frame, including a second pass through the
loop, has the same effect as the original writes.
