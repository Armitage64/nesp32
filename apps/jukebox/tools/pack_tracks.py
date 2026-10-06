#!/usr/bin/env python3
"""Convert music and sound to the files a nesp32 plays.

    tools/pack_tracks.py OUT_DIR music/ more.vgz song.mp3 ...

Writes OUT_DIR/00.jbs, 01.jbs, ... in playlist order (directories are read
in name order), with .pcm in place of .jbs for sampled sound, and removes
the files left there from an earlier run. The nesp32 plays them in the
order of their names, and passes over one it cannot make sense of, so
everything it relies on is checked here: each stream decodes, and each loop
offset is a frame boundary.

tools/deploy.py does this and then puts the files on a nesp32.

Sound is big: a minute at the default rate is 610 KB of the nesp32's
flash, of which it has 3968 KB for files.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import jbs  # noqa: E402
import mp32pcm  # noqa: E402
import pcm  # noqa: E402
import vgm  # noqa: E402
import vgm2jbs  # noqa: E402
import wav2pcm  # noqa: E402

SOUND_SUFFIXES = (".pcm", ".wav", ".mp3")
MUSIC_SUFFIXES = (".vgm", ".vgz", ".jbs") + SOUND_SUFFIXES


def load_track(path):
    """Return (title, JbsFile) for a .vgm, .vgz or .jbs file, or (title,
    pcm.Sound) for a .pcm, .wav or .mp3 file."""
    name = path.lower()
    if name.endswith(SOUND_SUFFIXES):
        if name.endswith(".pcm"):
            with open(path, "rb") as handle:
                sound = pcm.Sound.from_bytes(handle.read())
        elif name.endswith(".wav"):
            sound = wav2pcm.from_wav(path)
        else:
            sound = mp32pcm.from_file(path)
        sound.title = sound.title or wav2pcm.title_of(path)
        return sound.title, sound
    if name.endswith(".jbs"):
        with open(path, "rb") as handle:
            song = jbs.JbsFile.from_bytes(handle.read())
    else:
        song, _ = vgm2jbs.convert(vgm.load(path))
    title = song.title or os.path.splitext(os.path.basename(path))[0]
    return title, song


def expand_paths(paths):
    """The files named, with each directory's music in the order of its
    names."""
    found = []
    for path in paths:
        if os.path.isdir(path):
            for name in sorted(os.listdir(path)):
                if name.lower().endswith(MUSIC_SUFFIXES):
                    found.append(os.path.join(path, name))
        else:
            found.append(path)
    return found


def pack(paths, out_dir):
    """Return [(file name, title, bytes of stream or samples)] for the
    tracks written."""
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
