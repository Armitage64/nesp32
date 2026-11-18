#!/usr/bin/env python3
"""Build the ROMs that are not on the cartridge, the ones players make from
their own copy of a game with a BPS patch, and put them in one directory.

    tools/build_roms.py OUT [NAME ...]

The ROMs are those of PATCHES in tools/gen_web.py, the list the web site's
patches page is made from, so a game added there is built here too. Each
patch apps/<app>/dist/<name>.bps is made by its app's `make bps` from
apps/<app>/build/<name>.nes, which is built here by the app's own Makefile,
in its own build directory, and copied to OUT/<name>.nes. NAME, if given,
builds only those: drmario_net, or the app's directory, drmario.

Most of the games are built from the player's own ROM, baserom.nes in the
app's directory (each app's Makefile says which), and most from a
disassembly, a submodule under third_party/. One without either is passed
over and named at the end, with what it needs; a build that fails stops nothing else, and makes
this exit with an error at the end.
"""

import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from gen_web import PATCHES  # noqa: E402


def roms():
    """Each patch's (app directory, ROM's name), as PATCHES has them."""
    out = []
    for patch, _ in PATCHES:
        app = os.path.join(ROOT, os.path.dirname(os.path.dirname(patch)))
        out.append((app, os.path.splitext(os.path.basename(patch))[0]))
    return out


def baserom(app):
    """The game's ROM the app's Makefile builds from by default, if it has
    one, as a path: None for one built from a disassembly alone."""
    with open(os.path.join(app, "Makefile")) as f:
        found = re.search(r"^BASEROM\s*\?=\s*(\S+)", f.read(), re.M)
    return os.path.join(app, found.group(1)) if found else None


def submodules(app):
    """The submodules under third_party/ the app's Makefile names that are
    not checked out, as paths from the top."""
    with open(os.path.join(ROOT, ".gitmodules")) as f:
        paths = re.findall(r"^\s*path\s*=\s*(.+?)\s*$", f.read(), re.M)
    with open(os.path.join(app, "Makefile")) as f:
        makefile = f.read()
    return [path for path in paths
            if path in makefile
            if not os.listdir(os.path.join(ROOT, path))]


def main(out, names):
    wanted = roms()
    if names:
        unknown = [n for n in names
                   if not any(n in (name, os.path.basename(app)) for app, name in wanted)]
        if unknown:
            sys.exit("No ROM %s in PATCHES (tools/gen_web.py): there are %s." % (
                ", ".join(unknown), ", ".join(name for _, name in wanted)))
        wanted = [(app, name) for app, name in wanted
                  if name in names or os.path.basename(app) in names]
    os.makedirs(out, exist_ok=True)
    make = os.environ.get("MAKE", "make")
    built, skipped, failed = [], [], []
    for app, name in wanted:
        where = os.path.relpath(app, ROOT)
        base = baserom(app)
        if base and not os.path.exists(base):
            skipped.append("%s (no %s)" % (name, os.path.relpath(base, ROOT)))
            continue
        missing = submodules(app)
        if missing:
            skipped.append("%s (git submodule update --init %s)" % (name, " ".join(missing)))
            continue
        print("== %s/build/%s.nes" % (where, name), flush=True)
        target = os.path.join("build", name + ".nes")
        # BUILD by name: one given to the make that ran this would be the
        # app's too, through MAKEFLAGS.
        if subprocess.call([make, "-C", app, "BUILD=build", target]) != 0:
            failed.append(name)
            continue
        shutil.copyfile(os.path.join(app, target), os.path.join(out, name + ".nes"))
        built.append(name)
    print("%s: %s" % (os.path.relpath(out), ", ".join(built) or "nothing built"))
    if skipped:
        print("passed over: %s" % ", ".join(skipped))
    if failed:
        sys.exit("failed: %s" % ", ".join(failed))


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1].startswith("-"):
        sys.exit(__doc__)
    main(os.path.abspath(sys.argv[1]), sys.argv[2:])
