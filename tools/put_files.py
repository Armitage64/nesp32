#!/usr/bin/env python3
"""Put the jukebox's tracks on a nesp32, over USB.

    tools/put_files.py music/ [more.vgz ...]               write them to the nesp32
    tools/put_files.py -p /dev/cu.usbserial-XXXX music/
    tools/put_files.py --image build/storage.bin music/    only make the image

A StickS3 needs none of this: the setup ROM makes a drive of it, and the
music is copied there. This is for a StickC Plus2, which cannot be one, and
for writing a whole playlist in one go.

The nesp32 keeps its files in a FAT filing system, wear levelled, in the
`storage` partition (firmware/partitions.csv), and the jukebox's service
plays what is in its `tracks` directory, in the order of the names: rips of
games' music as they are (.vgm, .vgz), and nes-jukebox's own .jbs and .pcm
(its tools/deploy.py makes those of sampled sound). This makes that filing
system on this computer, with the files named and nothing else, and writes
the whole of it over whatever the nesp32 had: the tracks named are the
playlist. They are checked for being tracks at all, since the nesp32 passes
over one that is not; nothing here knows what is inside them.

The image is made by ESP-IDF's own tool for it, so IDF_PATH must say where
ESP-IDF is (~/esp/esp-idf if it does not), and this Python needs what that
tool does, with esptool to write the image:

    pip install construct esptool

That tool keeps a long name in small letters: "01 Title.vgz" is
"01 title.vgz" on the nesp32. A rip's own title is what the jukebox shows.

The nesp32 must be running nesp32's firmware, and restarts when the image
has been written. An image that would not fit says so before anything is
sent.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PARTITIONS = os.path.join(HERE, "..", "firmware", "partitions.csv")
PARTITION = "storage"
DIRECTORY = "tracks"
IDF = os.environ.get("IDF_PATH", os.path.join(os.path.expanduser("~"), "esp", "esp-idf"))
FATFS = os.path.join(IDF, "components", "fatfs")
SECTOR = 512                    # the firmware's CONFIG_WL_SECTOR_SIZE, and its wear
WEAR_MODE = "safe"              # levelling's mode (firmware/sdkconfig.defaults)
MAGICS = {".jbs": b"JBS\x1a", ".pcm": b"NPCM", ".vgm": b"Vgm ", ".vgz": b"\x1f\x8b"}
BAUD = 460800


def partition(name=PARTITION, path=PARTITIONS):
    """(offset, size) of a partition, from the firmware's table."""
    with open(path) as handle:
        for line in handle:
            fields = [field.strip() for field in line.split("#", 1)[0].split(",")]
            if len(fields) >= 5 and fields[0] == name:
                return int(fields[3], 0), int(fields[4], 0)
    raise ValueError("no partition called %s in %s" % (name, path))


def suffix(name):
    return os.path.splitext(name)[1].lower()


def tracks_in(paths):
    """The track files named, each directory's in the order of their names.
    Returns [(name on the nesp32, path)]; a name may be there once."""
    found = []
    for path in paths:
        if os.path.isdir(path):
            found += [os.path.join(path, name) for name in sorted(os.listdir(path))
                      if suffix(name) in MAGICS and not name.startswith(".")]
        else:
            found.append(path)
    out = []
    for path in found:
        name = os.path.basename(path)
        magic = MAGICS.get(suffix(name))
        if magic is None:
            raise ValueError("%s is not a .vgm, .vgz, .jbs or .pcm file" % path)
        with open(path, "rb") as handle:
            if handle.read(len(magic)) != magic:
                raise ValueError("%s is not what its name says" % path)
        if any(name.lower() == other.lower() for other, _ in out):
            raise ValueError("two files are called %s" % name)
        out.append((name, path))
    return out


def image(tracks, size):
    """A wear-levelled FAT image of `size` bytes with the tracks in it."""
    tool = os.path.join(FATFS, "wl_fatfsgen.py")
    if not os.path.exists(tool):
        raise ValueError("no ESP-IDF at %s to make the image with (set IDF_PATH)" % IDF)
    work = tempfile.mkdtemp(prefix="nesp32-files-")
    try:
        os.makedirs(os.path.join(work, "files", DIRECTORY))
        for name, path in tracks:
            shutil.copyfile(path, os.path.join(work, "files", DIRECTORY, name))
        out = os.path.join(work, "storage.bin")
        made = subprocess.run(
            [sys.executable, tool, os.path.join(work, "files"), "--output_file", out,
             "--partition_size", str(size), "--sector_size", str(SECTOR),
             "--wl_mode", WEAR_MODE, "--long_name_support"],
            capture_output=True, text=True)
        if made.returncode != 0:
            said = made.stderr.strip().splitlines()[-1] if made.stderr.strip() else "no reason"
            if "No module named" in said:
                raise ValueError("making the image needs more of this Python (%s): "
                                 "pip install construct" % said)
            raise ValueError("the tracks do not fit in the nesp32's %d KB (%s)"
                             % (size // 1024, said))
        with open(out, "rb") as handle:
            return handle.read()
    finally:
        shutil.rmtree(work, ignore_errors=True)


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
            raise ValueError("no tracks named")
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
