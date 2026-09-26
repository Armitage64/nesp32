# NES Jukebox

Stream music from NES `.vgm` rips to a real NES over the controller-2
serial link from [nes-radar](../nes-radar), and play it on the console's own
APU.

Work in progress. See [`PLAN.md`](PLAN.md) for the design and phases, and
[`docs/PROTOCOL.md`](docs/PROTOCOL.md) for the stream format and link.

## Status

Phase 1 is implemented: the converter from `.vgm`/`.vgz` to the `.jbs`
jukebox stream, and its tests. There is no ROM or host streamer yet.

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
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest
```

The tests build synthetic VGM files in code. The central test encodes
random register writes, decodes the stream, and checks with the APU
write-order model that every frame, including a second pass through the
loop, has the same effect as the original writes.
