#!/usr/bin/env python3
"""The nesp32's version: VERSION's number, and whether this is its release.

    tools/version.py              the text the nesp32 shows: 0.2.0, or
                                  0.2.0-dev for anything but that release
    tools/version.py describe     the commit, as git names it
    tools/version.py header OUT   nesp_version.h, for the firmware (C)
    tools/version.py inc OUT      nesp_version.inc, for the cartridge (ca65):
                                  its menu compares it with the firmware's
                                  and the web site's

A build is the release when the commit is the one tagged v and VERSION's
number (v0.2.0), and nothing in the tree is changed from it. Any other
build is after it, or on its way, and says so: -dev. Its numbers are still
the release's, since a ROM that asks for a version means a release.

VERSION changes only in a release's own commit (tools/release.py). The
header is rewritten only if its contents changed, so a build that has it
does not compile again for nothing.
"""

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
SOURCE = os.path.join(ROOT, "VERSION")


def number():
    """VERSION's number, as it is: 0.2.0, or 0.3.0-rc.1."""
    with open(SOURCE) as f:
        text = f.read().strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?", text):
        sys.exit("VERSION: %r is not a version such as 0.2.0" % text)
    return text


def numbers():
    """The major, minor and patch numbers, which the hello reply carries."""
    return tuple(int(part) for part in re.match(r"(\d+)\.(\d+)\.(\d+)", number()).groups())


def git(*args):
    try:
        return subprocess.check_output(["git", "-C", ROOT] + list(args), text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def is_release():
    """Whether this is the commit tagged with VERSION's number, unchanged."""
    return git("describe", "--tags", "--exact-match", "--dirty") == "v" + number()


def text():
    return number() if is_release() else number() + "-dev"


def describe():
    return git("describe", "--always", "--dirty", "--tags") or "unknown"


def header():
    major, minor, patch = numbers()
    return ("/* Made by tools/version.py from VERSION: do not edit. */\n"
            "#ifndef NESP_VERSION_H\n"
            "#define NESP_VERSION_H\n\n"
            "#define NESP_FIRMWARE_MAJOR %d\n"
            "#define NESP_FIRMWARE_MINOR %d\n"
            "#define NESP_FIRMWARE_PATCH %d\n"
            "#define NESP_FIRMWARE_TEXT \"%s\"\n\n"
            "#endif\n" % (major, minor, patch, text()))


def inc():
    major, minor, patch = numbers()
    return ("; Made by tools/version.py from VERSION: do not edit.\n"
            "NESP_VERSION_MAJOR = %d\n"
            "NESP_VERSION_MINOR = %d\n"
            "NESP_VERSION_PATCH = %d\n" % (major, minor, patch))


def write(path, contents):
    """Write `path` only if its contents changed."""
    try:
        with open(path) as f:
            if f.read() == contents:
                return
    except OSError:
        pass
    with open(path, "w") as f:
        f.write(contents)


if __name__ == "__main__":
    if sys.argv[1:] == []:
        print(text())
    elif sys.argv[1:] == ["describe"]:
        print(describe())
    elif len(sys.argv) == 3 and sys.argv[1] == "header":
        write(sys.argv[2], header())
    elif len(sys.argv) == 3 and sys.argv[1] == "inc":
        write(sys.argv[2], inc())
    else:
        sys.exit(__doc__)
