#!/usr/bin/env python3
"""Convert music and sound to the files the Stick plays.

    tools/pack_tracks.py OUT_DIR music/ more.vgz song.mp3 ...

Writes OUT_DIR/00.jbs, 01.jbs, ... in playlist order (directories are read
in name order), with .pcm in place of .jbs for sampled sound, and removes
the files left there from an earlier run. The Stick trusts these files, so
everything it relies on is checked here: each stream decodes, and each loop
offset is a frame boundary.

Sound is big: a minute at the default rate is 610 KB of the Stick's flash,
and all of it is copied over USB by deploy.sh.
"""

import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "host"))

import jbs  # noqa: E402
import pcm  # noqa: E402
from jukebox import expand_paths, load_track  # noqa: E402


def pack(paths, out_dir):
    """Return [(file name, title, stream bytes)] for the tracks written."""
    os.makedirs(out_dir, exist_ok=True)
    for name in os.listdir(out_dir):
        if name.endswith((".jbs", ".pcm")):
            os.remove(os.path.join(out_dir, name))
    written = []
    for path in expand_paths(paths):
        try:
            title, song = load_track(path)
            if isinstance(song, pcm.Sound):
                song.title = title
                name = "%02d.pcm" % len(written)
                with open(os.path.join(out_dir, name), "wb") as handle:
                    handle.write(song.to_bytes())
                written.append((name, title, len(song.samples)))
                continue
            starts = [start for start, _ in jbs.frame_units(song.stream)]
            if song.loop_frame is not None and song.loop_offset not in starts:
                raise ValueError("loop offset is not a frame boundary")
        except (OSError, ValueError) as error:
            print("skipping %s: %s" % (path, error), file=sys.stderr)
            continue
        song.title = title
        name = "%02d.jbs" % len(written)
        with open(os.path.join(out_dir, name), "wb") as handle:
            handle.write(song.to_bytes())
        written.append((name, title, len(song.stream)))
    return written


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    written = pack(args[1:], args[0])
    for name, title, size in written:
        print("%s  %6d bytes  %s" % (name, size, title))
    if not written:
        print("no playable tracks", file=sys.stderr)
        return 1
    print("%d tracks, %d bytes" % (len(written), sum(size for _, _, size in written)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
