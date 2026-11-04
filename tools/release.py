#!/usr/bin/env python3
"""Cut a release of the nesp32's firmware and cartridge (docs/RELEASING.md).

    tools/release.py 0.2.0          on a new branch release-0.2.0 from
                                    origin/main: VERSION says 0.2.0, and
                                    CHANGELOG.md's Unreleased is 0.2.0's,
                                    in one commit for a pull request
    tools/release.py notes 0.2.0    0.2.0's section of CHANGELOG.md, for
                                    the GitHub release
    tools/release.py pack OUT       what the GitHub release holds, from this
                                    tree's builds: nesp32-0.2.0.nes, and each
                                    board's firmware as nesp32-s3-0.2.0.zip
                                    and nesp32-plus2-0.2.0.zip (its files and
                                    flasher_args.json, which say where each
                                    goes), as tools/gen_web.py --release reads
                                    them

Merging the pull request is the release. The workflow then tags the merged
commit v0.2.0, builds the firmware and the cartridge from it, attaches them
to a GitHub release, and puts them on the web site.
"""

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

import version

CHANGELOG = os.path.join(version.ROOT, "CHANGELOG.md")
UNRELEASED = "## Unreleased\n"


def sections(text):
    """CHANGELOG.md's head, and each `## ` section as (heading, body)."""
    parts = re.split(r"^(## .*\n)", text, flags=re.M)
    return parts[0], list(zip(parts[1::2], parts[2::2]))


def notes(number):
    _, found = sections(open(CHANGELOG).read())
    for heading, body in found:
        if re.match(r"## %s( |$)" % re.escape(number), heading.strip()):
            return body.strip() + "\n"
    sys.exit("CHANGELOG.md has no section for %s" % number)


def pack(out):
    number = version.number()
    os.makedirs(out, exist_ok=True)
    shutil.copyfile(os.path.join(version.ROOT, "build", "nesp32.nes"),
                    os.path.join(out, "nesp32-%s.nes" % number))
    for target, prefix in (("esp32s3", "s3"), ("esp32", "plus2")):
        directory = os.path.join(version.ROOT, "firmware", "build-" + target)
        with open(os.path.join(directory, "flasher_args.json")) as f:
            files = json.load(f)["flash_files"].values()
        with zipfile.ZipFile(os.path.join(out, "nesp32-%s-%s.zip" % (prefix, number)), "w",
                             zipfile.ZIP_DEFLATED) as archive:
            for name in ["flasher_args.json"] + sorted(files):
                archive.write(os.path.join(directory, name), name)


def git(*args):
    return subprocess.run(["git", "-C", version.ROOT] + list(args), check=True,
                          capture_output=True, text=True).stdout.strip()


def cut(number):
    if not re.fullmatch(r"\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?", number):
        sys.exit("%r is not a version such as 0.2.0" % number)
    if git("status", "--porcelain"):
        sys.exit("The tree has changes: commit or put them away first.")
    git("fetch", "origin", "main", "--tags")
    if git("tag", "-l", "v" + number):
        sys.exit("v%s is already a release." % number)
    changelog = git("show", "origin/main:CHANGELOG.md") + "\n"
    head, found = sections(changelog)
    if not found or found[0][0] != UNRELEASED or not found[0][1].strip():
        sys.exit("CHANGELOG.md's first section is not an Unreleased with something in it.")
    branch = "release-" + number
    git("switch", "-c", branch, "origin/main")
    found[0] = ("## %s — %s\n" % (number, datetime.date.today().isoformat()), found[0][1])
    with open(CHANGELOG, "w") as f:
        f.write(head + UNRELEASED + "\n" + "".join(h + b for h, b in found))
    with open(version.SOURCE, "w") as f:
        f.write(number + "\n")
    git("commit", "-m", "Release %s" % number, "--", "VERSION", "CHANGELOG.md")
    print("On %s: VERSION and CHANGELOG.md say %s. Read the notes over, push, and\n"
          "open a pull request; merging it makes the release." % (branch, number))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "notes":
        sys.stdout.write(notes(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] == "pack":
        pack(sys.argv[2])
    elif len(sys.argv) == 2:
        cut(sys.argv[1])
    else:
        sys.exit(__doc__)
