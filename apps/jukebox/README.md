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

- **Sampled sound, heard on a real NES:** a playlist can hold recordings
  as well as music. The link ROM plays them through `$4011`, the console's
  7-bit DAC, at 7748 to 20338 samples a second, fed a byte a sample at up
  to 223722 baud. Converters from WAV and MP3, both hosts and the ROM are
  built and tested on the simulated console. On a real one, a 30-second
  clip from an MP3, sent by a StickC Plus2, sounded right at 10169 samples
  a second and at 20338, the fastest; the four rates between and below,
  and the desktop host, are untried there.
  See "Sampled sound" below.

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

## Sampled sound

The link ROM can also play recordings: speech, a song off a CD, anything
sampled. A sound track sits in a playlist beside the music. When its turn
comes the console shows its name and `SAMPLED SOUND`, and then plays it
through `$4011`, its 7-bit DAC, as the bytes arrive: one byte a sample, at
a baud rate of its own. **It has played on a real NES from a StickC
Plus2** at the default rate and at the fastest; the other four rates, and
the desktop host, have only run in simulation.

```sh
tools/mp32pcm.py song.mp3 music/song.pcm            # or tools/wav2pcm.py song.wav ...
tools/mp32pcm.py song.mp3 music/song.pcm --period 8 --title "Band - Song"
tools/wav2pcm.py --tone 440 music/tone.pcm          # a test tone
tools/pcm_preview.py music/song.pcm build/song_nes.wav
```

- `mp32pcm.py` has no decoder of its own: it runs `ffmpeg` if there is
  one, and macOS's `afconvert` otherwise. It takes whatever they read.
  `wav2pcm.py` needs nothing, and is slow on a long file (about a third
  of the file's length).
- `--period` picks the rate, in CPU cycles a bit: 21, 16 (the default,
  10169 samples a second), 14, 12, 10 or 8 (20338). A minute is 465 KB at
  the slowest and 1220 KB at the fastest.
- `--seconds` keeps only that much from the start, for a Stick with
  little flash to spare.
- `--title` is what the console shows, "game - track" as for music. It
  defaults to the file's name.
- `pcm_preview.py` writes a WAV of what the console's DAC would put out,
  from the ROM's own routine on the simulated console. It is the way to
  hear a file without a console: an emulator has nothing on its controller
  port to send the bytes. It plays the first 10 seconds unless told
  otherwise. In it a full-scale tone has its noise 41 to 46 dB down within
  the band the rate carries, which is what 7 bits through the DAC's curve
  give; the console's own output filter is not modelled.

Both hosts take `.pcm` files in a playlist, and `.wav` and `.mp3` files
too, which they convert at the default rate as they load them.

While a sound plays the console does nothing else: its screen stands still,
with the bars down and the clock at 0:00, and its controller is not read. A key on the test host, or a button on the
Stick, stops the sound and then does what it always does. See
[`docs/PROTOCOL.md`](docs/PROTOCOL.md), part 4.

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

VGM rips are copyrighted, and so are most recordings. Keep them in
`music/`, which git ignores, as it does `.pcm` files anywhere.

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
