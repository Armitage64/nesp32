# NES Jukebox

Stream music from NES `.vgm` rips to a real NES over the controller-2
serial link from [nes-radar](../../../nes-radar), and play it on the console's own
APU.

The link ROM's host is a [nesp32](../..): one firmware for every NES
application that uses the hat on controller port 2. The jukebox is this ROM
and nesp32's JUKE service, with its RAW service for sampled sound; there is
no firmware of its own here any more.

A proof of concept, and work in progress. See [`PLAN.md`](PLAN.md) for the
design and phases, and [`docs/PROTOCOL.md`](docs/PROTOCOL.md) for the
stream format and how the ROM uses the link.

## Status

**The link ROM plays from nesp32's firmware on hardware**: an M5StickS3 on
the MiSTer's NES core. Three tracks of music and one of sampled sound, at
20338 samples a second, sounded right; tracks changed from the controller
and from the nesp32's buttons, also in the middle of a sound, and followed
one another by themselves. In about 15000 requests the nesp32 sent no reply
twice, the console's buffer never ran dry, and the nesp32's slowest reply
took 474 microseconds. On the simulated console the same ROM and firmware
come out frame for frame and sample for sample, over a line that models
every bit, whatever is lost or damaged on the way. Still untried with a
nesp32: a real NES, the StickC Plus2, a long run, and the five slower
rates of sound.

| Part | State |
|---|---|
| Converter from `.vgm`/`.vgz` to the `.jbs` stream, and from WAV and MP3 to `.pcm` | done |
| Player ROM, with a song built in (`build/jukebox.nes`) | tested on py65, where every song plays frame-exact; confirmed by ear in Mesen 2 and on a real NES |
| The screen and the controller, on both ROMs | tested on py65; they worked on a real NES before the link changed, and are unchanged |
| Link ROM (`build/jukebox_link.nes`): the ROM on nesp32's library, and nesp32's JUKE and RAW services | working on a StickS3 with the MiSTer's NES core, at 85227 baud; tested together over a cycle-exact simulated line |
| Sampled sound through `$4011`, at 7748 to 20338 samples a second | heard from a nesp32 on the MiSTer at the fastest rate, and the routines played on a real NES under the old firmware; all six rates are tested on the simulated line |
| Link throughput (`throughput/`) | a ROM that climbs the rates each way through nesp32's RAW service. On a StickS3 with the MiSTer's NES core it reached 298296 baud to the console and 223722 from it, the rates it measured on a real NES before it moved, with a MicroPython script of its own on a StickC Plus2 |

Until October 2026 the jukebox had a link protocol of its own, at 38400
baud, a MicroPython firmware for the Stick, and a desktop streamer for an
FTDI cable. **That is what played on a real NES**: music from a StickC
Plus2 with no resends, and a 30-second clip of sampled sound at 10169 and
at 20338 samples a second. All of it is in this repository's history, and
what bringing it up found is in [`PLAN.md`](PLAN.md). The sound routines,
the player, the screen and the stream format are unchanged from then; the
link under them is nesp32's.

## Building the ROM

Needs [cc65](https://cc65.github.io/) (`ca65`, `ld65`), a C compiler,
Python 3, and [nesp32](../..), the top of this repository (or
`NESP32=`). The link's library for the console comes from it, and its
firmware's link and services are built for this computer, for the tests to
run the link ROM against.

```sh
make                                      # original demo tune
make SONG="music/01 Running About.vgz"    # any rip, or a .jbs
```

`make` builds two ROMs: `build/jukebox.nes` with the song built in, and
`build/jukebox_link.nes`, which asks a nesp32 on controller port 2 for
its music. It says hello to nesp32's firmware as `JUKE` and asks for the
JUKE and RAW services.

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

On the link ROM the controller only asks: the press goes to the nesp32 as
a button request, and the nesp32 changes the track as it does for its own
buttons, so the name on the screen changes when the new track's first
frame plays, about a quarter of a second later. A press is sent until it
is answered and done once, however noisy the line.

The link ROM's status line also says what is wrong with the other end:
`WAITING FOR LINK` when nothing answers, `UPDATE NESP32` when the firmware
there has no jukebox in it, and `NO MUSIC FOUND` when it has no tracks.

The tiles, the screen's layout and the lookup tables all come from
`tools/gen_ui.py`, which `make` runs. `tools/gen_ui.py build --preview
screen.png` writes the still screen as a picture, to check a change to the
layout without a console.

For debugging, [Mesen 2](https://www.mesen.ca/) can import
`build/jukebox.dbg` (cc65 debug info), so its debugger, memory viewer and
watch list show the ROM's labels, such as `head`, `tail`, `underruns` and
`stream_error`. A write breakpoint on `$4000-$4017` stops at each frame's APU
writes.

## Music on a nesp32

The nesp32 holds the tracks, as files in its flash. Rips (`.vgm`, `.vgz`)
need nothing from here any more: the nesp32 converts them itself, and a
StickS3 takes them as a USB drive (the top [README](../../README.md),
"Music for the jukebox"). What follows is for recordings, which are
converted here, and for writing a whole playlist at once. With the nesp32
on USB, and already running [nesp32's firmware](../../firmware/README.md):

```sh
pip install construct esptool
tools/deploy.py                              # everything in music/
tools/deploy.py music/a.vgz music/b.mp3      # these, in this order
tools/deploy.py -p /dev/cu.usbserial-XXXX music/
```

It converts the music to `.jbs` and the recordings to `.pcm` on this
computer (into `build/tracks`), and hands them to nesp32's
`tools/put_files.py`, which writes them over whatever tracks the nesp32
had. The files named are the playlist. There are 3968 KB for them.

Plug the hat into controller port 2 and start `build/jukebox_link.nes` on
the console. The order of powering up does not matter. Nothing plays until
a button says so:

| The nesp32's button | The controller | What it does |
|---|---|---|
| **A** (front) | **Start** or **A** | pause, resume. From stopped, play the track shown from its start |
| **B** (side) | **Left** | previous track, and play it |
| **Power**, tapped | **Right** | next track, and play it |
| **B**, held 2 s | | power off |

- A pause is heard within a frame or two and keeps what the NES has
  buffered, so the music goes on from the same place.
- A change of track is heard at once, and the music starts again after
  about a quarter of a second: the NES drops the seconds it had buffered.
- Resetting the NES stops the music: the ROM says hello again, and the
  nesp32 starts its service from nothing, at the track it was on.
- A looping track plays twice round its loop, and after the last track the
  first plays again.

The nesp32's screen shows the track being sent and `PLAYING`, `PAUSED`,
`STOPPED` or `SOUND`, with two counts that should stay at 0: `again`,
replies it had to send twice, and `dry`, frames the console found its
buffer empty.

Without a nesp32, nesp32's `host/serial_host.py --tracks build/tracks`
answers the console from a computer, on nes-radar's FTDI cable, with the
same firmware code. It has not been run on a cable.

## Sampled sound

The link ROM can also play recordings: speech, a song off a CD, anything
sampled. A sound track sits in a playlist beside the music. When its turn
comes the console shows its name and `SAMPLED SOUND`, and then plays it
through `$4011`, its 7-bit DAC, as the bytes arrive: one byte a sample, at
a baud rate of its own. **From a nesp32 a sound has played on the MiSTer's
NES core**, at the fastest rate, and in simulation at all six. The routines
that do it played on a real NES from a StickC Plus2, at the default rate
and at the fastest, under the MicroPython firmware this repository used to
have.

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
- `--seconds` keeps only that much from the start, for a nesp32 with
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

`tools/deploy.py` takes `.pcm` files in a playlist, and `.wav` and `.mp3`
files too, which it converts at the default rate. A minute at the default
rate is 610 KB of the nesp32's 3968: `--seconds` on the converters keeps a
clip short.

While a sound plays the console does nothing else: its screen stands still,
with the bars down and the clock at 0:00, and its controller is not read.
A button on the nesp32 ends the sound and then does what it always does,
except that A stops: a sound cannot be paused, and A again plays it from
its start. See [`docs/PROTOCOL.md`](docs/PROTOCOL.md), part 4.

A NES left in the middle of a sound (the nesp32 lost its power) waits for
the rest. Starting the nesp32 again frees it; so does Reset.

## Not done

- **The controller during a sound.** The console is deaf to it while a
  sound plays; only the nesp32's own buttons end one. Two ways to change
  that, neither begun:
  1. *A stops the sound.* With the line to the nesp32 at rest the
     controller keeps loading its buttons, and a plain read of `$4016`
     gives A as it is now: about 8 cycles a sample, and nothing on the
     line. The console then leaves the sound and pulls its line low, which
     it never does during a run otherwise, and the nesp32 takes anything
     it hears in the middle of one for "stop" (a small change to nesp32's
     RAW and JUKE). The controller works as always from there, so Left
     and Right are one more press away. Whether 8 cycles fit at 10 and at
     8 cycles a bit has not been worked out.
  2. *Every button.* Start, Left and Right are behind the controller's
     shift register, which is clocked only with that same line held low.
     The console would hold it low across eight samples and read a button
     with each, over and over: some 11 cycles a sample, the sound routines
     written again, and another way to say "stop", since the line would
     never be quiet. It probably does not fit at the fastest rate or two.
  Either moves every sample by a few cycles, and wants hearing again on a
  console.
- A real NES, the StickC Plus2 and a long run with nesp32's firmware, and
  sound at the five slower rates.
- The throughput test (`throughput/`) on a real NES with nesp32's
  firmware. It has run on the MiSTer.

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
py65, so they need cc65 and nesp32's tree; they skip without
either. The link ROM's tests run it against nesp32's own link and
services, built for this computer, over a model of the serial line that
is exact to the CPU cycle. The full suite takes about ten minutes, mostly
that simulation.

The tests build synthetic VGM files in code. The central test encodes
random register writes, decodes the stream, and checks with the APU
write-order model that every frame, including a second pass through the
loop, has the same effect as the original writes.
