#!/usr/bin/env python3
"""Put the jukebox's tracks on a nesp32, over USB.

    tools/put_files.py tracks/ [more.jbs ...]              write them to the nesp32
    tools/put_files.py -p /dev/cu.usbserial-XXXX tracks/
    tools/put_files.py --image build/storage.bin tracks/   only make the image

The nesp32 keeps its files in a LittleFS filing system in the `storage`
partition (firmware/partitions.csv), and the jukebox's service plays the
.jbs and .pcm files in its `tracks` directory, in the order of their names.
This makes that filing system on this computer, with the files named and
nothing else, and writes the whole of it over whatever the nesp32 had: the
tracks named are the playlist.

The files are nes-jukebox's, and its tools make them (tools/deploy.py there
converts a directory of music and calls this). They are checked for being
tracks at all, since the nesp32 passes over one that is not; nothing here
knows what is inside them.

Needs littlefs-python to make the image and esptool to write it:

    pip install littlefs-python esptool

The nesp32 must be running nesp32's firmware, and restarts when the image
has been written. An image that would not fit says so before anything is
sent.
"""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PARTITIONS = os.path.join(HERE, "..", "firmware", "partitions.csv")
PARTITION = "storage"
DIRECTORY = "tracks"
BLOCK = 4096                    # esp_littlefs's, and the flash's erase size
NAME_MAX = 64                   # esp_littlefs's CONFIG_LITTLEFS_OBJ_NAME_LEN: the longest
                                # name the nesp32's filing system hands back, and its end
# The oldest layout LittleFS still writes. A firmware's LittleFS mounts
# what is its own version's or older, and formats what it cannot mount.
DISK_VERSION = 0x00020000
MAGICS = {".jbs": b"JBS\x1a", ".pcm": b"NPCM"}
BAUD = 460800


def partition(name=PARTITION, path=PARTITIONS):
    """(offset, size) of a partition, from the firmware's table."""
    with open(path) as handle:
        for line in handle:
            fields = [field.strip() for field in line.split("#", 1)[0].split(",")]
            if len(fields) >= 5 and fields[0] == name:
                return int(fields[3], 0), int(fields[4], 0)
    raise ValueError("no partition called %s in %s" % (name, path))


def tracks_in(paths):
    """The track files named, each directory's in the order of their names.
    Returns [(name on the nesp32, path)]; a name may be there once."""
    found = []
    for path in paths:
        if os.path.isdir(path):
            found += [os.path.join(path, name) for name in sorted(os.listdir(path))
                      if os.path.splitext(name)[1] in MAGICS]
        else:
            found.append(path)
    out = []
    for path in found:
        name = os.path.basename(path)
        magic = MAGICS.get(os.path.splitext(name)[1])
        if magic is None:
            raise ValueError("%s is not a .jbs or a .pcm file" % path)
        with open(path, "rb") as handle:
            if handle.read(len(magic)) != magic:
                raise ValueError("%s is not what its name says" % path)
        if len(name.encode("utf-8")) >= NAME_MAX:
            raise ValueError("%s: a name on the nesp32 is under %d bytes" % (path, NAME_MAX))
        if any(name == other for other, _ in out):
            raise ValueError("two files are called %s" % name)
        out.append((name, path))
    return out


def image(tracks, size):
    """A LittleFS image of `size` bytes with the tracks in it."""
    try:
        from littlefs import LittleFS, LittleFSError
    except ImportError:
        sys.exit("making the image needs littlefs-python: pip install littlefs-python")
    files = LittleFS(block_size=BLOCK, block_count=size // BLOCK, name_max=NAME_MAX,
                     disk_version=DISK_VERSION)
    files.mkdir(DIRECTORY)
    try:
        for name, path in tracks:
            with open(path, "rb") as source:
                with files.open("%s/%s" % (DIRECTORY, name), "wb") as handle:
                    handle.write(source.read())
    except LittleFSError as error:
        raise ValueError("the tracks do not fit in the nesp32's %d KB (%s)"
                         % (size // 1024, error))
    return bytes(files.context.buffer)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("paths", nargs="+", help="track files, or directories of them")
    parser.add_argument("-p", "--port", help="the nesp32's serial port; esptool finds one "
                        "by itself if there is only one")
    parser.add_argument("--image", help="write the image to this file and send nothing")
    args = parser.parse_args(argv)
    try:
        offset, size = partition()
        tracks = tracks_in(args.paths)
        if not tracks:
            raise ValueError("no .jbs or .pcm files named")
        data = image(tracks, size)
    except (OSError, ValueError) as error:
        print("put_files: %s" % error, file=sys.stderr)
        return 1
    total = sum(os.path.getsize(path) for _, path in tracks)
    print("%d tracks, %d KB of the nesp32's %d" % (len(tracks), (total + 1023) // 1024,
                                                   size // 1024))
    if args.image:
        with open(args.image, "wb") as handle:
            handle.write(data)
        print("wrote %s; it goes at 0x%X" % (args.image, offset))
        return 0
    path = os.path.join(os.environ.get("TMPDIR", "/tmp"), "nesp32-storage-%d.bin" % os.getpid())
    with open(path, "wb") as handle:
        handle.write(data)
    command = [sys.executable, "-m", "esptool"]
    if args.port:
        command += ["--port", args.port]
    command += ["--baud", str(BAUD), "write_flash", "0x%X" % offset, path]
    try:
        return subprocess.call(command)
    finally:
        os.remove(path)


if __name__ == "__main__":
    sys.exit(main())
