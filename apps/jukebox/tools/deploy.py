#!/usr/bin/env python3
"""Put music on a nesp32, over USB.

    tools/deploy.py                               everything in music/
    tools/deploy.py music/a.vgz music/b.mp3       these, in this order
    tools/deploy.py -p /dev/cu.usbserial-XXXX music/

Converts the music to .jbs and the sound (.pcm, .wav, .mp3) to .pcm on this
computer (tools/pack_tracks.py, into build/tracks), and hands the files to
nesp32's tools/put_files.py, which writes them to the nesp32's flash in
place of whatever tracks it had. The tracks named are the playlist, in the
order given; a directory's are in the order of their names.

The nesp32 must already run nesp32's firmware (its firmware/README.md), at
the top of this repository, or wherever NESP32 says. That tool
needs littlefs-python and esptool:

    pip install littlefs-python esptool
"""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
NESP32 = os.path.abspath(os.environ.get("NESP32", os.path.join(ROOT, "..", "..")))

sys.path.insert(0, HERE)

import pack_tracks  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("paths", nargs="*", help="music and sound files, or directories of "
                        "them; with none, music/")
    parser.add_argument("-p", "--port", help="the nesp32's serial port, if esptool cannot "
                        "tell which it is")
    parser.add_argument("--out", default=os.path.join(ROOT, "build", "tracks"),
                        help="where the converted tracks go (build/tracks)")
    args = parser.parse_args(argv)
    put_files = os.path.join(NESP32, "tools", "put_files.py")
    if not os.path.exists(put_files):
        print("deploy: no nesp32 checkout at %s (set NESP32)" % NESP32, file=sys.stderr)
        return 1
    written = pack_tracks.pack(args.paths or [os.path.join(ROOT, "music")], args.out)
    for name, title, size in written:
        print("%s  %6d bytes  %s" % (name, size, title))
    if not written:
        print("deploy: no playable tracks", file=sys.stderr)
        return 1
    command = [sys.executable, put_files]
    if args.port:
        command += ["--port", args.port]
    return subprocess.call(command + [args.out])


if __name__ == "__main__":
    sys.exit(main())
