# National Public Radio

NPR's live radio stream on a NES, through the console's own sample
channel. A [nesp32](../..) on controller port 2 fetches the stream from the
Internet, decodes it, and sends it to the console a byte a sample; the ROM
writes each byte to `$4011`, the channel's 7-bit DAC, as it arrives: 20338
samples a second.

A proof of concept, with the one station. The sound's routines on the
console, and the way a sound takes the serial line over, are
[the jukebox's](../jukebox) sampled sound. What is new is on the nesp32:
its TUNER service, in [nesp32's `docs/PROTOCOL.md`](../../docs/PROTOCOL.md).

## Status

**It plays on hardware**: from a StickS3, speech was entirely clear, if
a little quiet, and in a first minute the nesp32's ring neither ran dry
nor dropped anything. No longer run has been made, and nothing was
measured. On a simulated console the ROM plays the station from nesp32's
own firmware code, over a line that models every bit: each sample the
nesp32 sends reaches the DAC, once and in order.

| Part | State |
|---|---|
| TUNER on the nesp32: the stream fetched, decoded (MP3), resampled and made into levels for the DAC | working on a StickS3; tested on a computer, with the test as the Internet |
| The ROM (`build/npr.nes`) | working on hardware with a StickS3; tested on py65 against that code, over the simulated line |
| A nesp32 decoding the stream as fast as it arrives | measured on a StickS3, with no console: 11.5% of one core ([nesp32's firmware](../../firmware/README.md), "The radio") |
| How it sounds | clear speech on hardware, and quiet. `tools/npr_preview.py` gives it without a console |

## Building

Needs [cc65](https://cc65.github.io/) (`ca65`, `ld65`), a C compiler,
Python 3, and nesp32, the top of this repository.

```sh
make            # build/npr.nes (NROM-256, mapper 0)
make test
```

## Playing

![The screen](docs/screen.png)

With the nesp32 on a Wi-Fi network (the [setup ROM](../setup) joins one)
and on controller port 2, start `build/npr.nes`. The screen's header is
nesp32's, with `NATIONAL PUBLIC RADIO` under the name; the nesp32's own
screen calls the program `NPR`.

| | |
|---|---|
| **Start** or **A** on the controller | tune in: `TUNING`, and a second or two later `ON THE AIR`. Pressed again while it is tuning, give it up |
| **A** on the controller, while the station plays | pause: `PAUSED`. Start or A plays it again, at once |
| **A** (front) on the nesp32 | tune in; and while the station plays or is paused, turn it off |

**While the station plays, A on the controller pauses it and the nesp32's
button stops it.** A console playing sampled sound does nothing else: its
screen stands still, and of its controller it looks at button A alone,
once a sample (the jukebox's `docs/PROTOCOL.md`, part 4, has how). Start
is not seen until the station is paused. Reset works too: the nesp32
hears the console say hello and ends the sound.

A paused station is fetched still, so that it plays again without tuning:
the nesp32 holds its last twelve seconds, and goes on from the oldest of
them. Paused for longer than that, it has skipped what fell between.
Pausing is tested on the simulated console and **has not been tried on
hardware**: each sample is looked for 3 CPU cycles later than it was when
the station was heard there.

The status line says what is wrong when something is: `WAITING FOR LINK`
when nothing answers, `UPDATE NESP32` when the firmware there has no TUNER,
`NO WI-FI`, and the nesp32's own words when the stream cannot be had or is
lost (`THE SITE DID NOT ANSWER`, `THE CONNECTION DROPPED`). Start tries
again.

The nesp32's screen shows `NPR` and how it stands; while the station
plays, `ON THE AIR` with the seconds it holds ready, and two counts that
should stay at 0 for hours at a time: `dry`, times it had nothing to send
and held the sound where it was, and `cut`, seconds dropped because the
station ran ahead of the console.

## Hearing it without a console

```sh
make -C ../.. host
tools/npr_preview.py --live 20 build/npr_nes.wav    # the station, for 20 seconds
tools/npr_preview.py some.mp3 build/some_nes.wav
```

The stream goes through the nesp32's own code, built for this computer,
and what it would put on the line is written as a WAV file of the DAC's
output: 7 bits through the DAC's curve, at 20338 samples a second. The
console's filters are not in it.

## Not done

- A long run, a real NES, and the StickC Plus2.
- More than one station, and a station's name or programme on the screen.
- Pausing, and the sound's new timing, on hardware.
- Start during the sound: only A is looked at.
- Loudness. A sample goes to the DAC at the level the station sent it, and
  speech uses about a third of the DAC's range; a gain that followed the
  programme would use more of the 7 bits.
- A stream that is lost is not fetched again by itself.
- The cartridge with this on it, on hardware: it is the sixth program there
  (nesp32's `make cart`), and starts from the menu on a simulated console.

## Tests

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

`make test` does the same, with nesp32's Python if it has one. The console
and the serial line are the jukebox's (`../jukebox/tests`), and the
station's stream is an MP3 of a tone from nesp32's `tests/fixtures`. They
need cc65 and skip without it.
