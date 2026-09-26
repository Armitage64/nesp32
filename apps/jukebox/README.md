# NES Jukebox

Stream music from NES `.vgm` rips to a real NES over the controller-2
serial link from [nes-radar](../nes-radar), and play it on the console's own
APU.

Work in progress. See [`PLAN.md`](PLAN.md) for the design and phases, and
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
- **Phase 4, built:** the desktop streamer, `host/jukebox.py`. Tested
  against the simulated NES; waiting on the serial hardware to try for
  real.

## Building the ROM

Needs [cc65](https://cc65.github.io/) (`ca65`, `ld65`).

```sh
make                                      # original demo tune
make SONG="music/01 Running About.vgz"    # any rip, or a .jbs
```

`make` builds two ROMs: `build/jukebox.nes` with the song built in, and
`build/jukebox_link.nes`, which fetches the song over controller port 2.

The standalone ROM is `build/jukebox.nes` (NROM-256, mapper 0). Open it in an emulator
such as Mesen, or copy it to a flash cart. The screen stays blank dark blue;
the music is the point. A song can be up to 24 KB of stream, which covers
every rip tried so far (6-14 KB).

For debugging, [Mesen 2](https://www.mesen.ca/) can import
`build/jukebox.dbg` (cc65 debug info), so its debugger, memory viewer and
watch list show the ROM's labels, such as `head`, `tail`, `underruns` and
`stream_error`. A write breakpoint on `$4000-$4017` stops at each frame's APU
writes.

## Streaming to a NES

With the link ROM running on the console and the serial cable from
nes-radar connected:

```sh
.venv/bin/pip install -r host/requirements.txt   # pyserial
.venv/bin/python host/jukebox.py --list-ports
.venv/bin/python host/jukebox.py --port /dev/cu.usbserial-XXXX music/
```

Keys: `n` next track, `p` previous, `r` restart, `q` quit. `--loops N`
sets how many times a looping track plays before the next one, and
`--repeat` starts the playlist over at the end. The status line shows
requests, bursts and **resends**; a resend is a burst the NES missed, and a
steady trickle of them means the host is replying too slowly (see
docs/PROTOCOL.md, Timing). Track changes are heard after the few seconds of
music the NES has already buffered.

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
py65, so they need cc65; they skip without it. The full suite takes about
two minutes, mostly the serial link simulation.

The tests build synthetic VGM files in code. The central test encodes
random register writes, decodes the stream, and checks with the APU
write-order model that every frame, including a second pass through the
loop, has the same effect as the original writes.
