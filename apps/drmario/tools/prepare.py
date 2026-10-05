#!/usr/bin/env python3
"""Strip the disassembly's left-hand columns so ca65 can read it.

A port of preparations.lua. Each source is written to the build directory
as copy_<name>, which is the name bank_FF.asm includes.

    prepare.py BUILD_DIR FILE...
"""

import os
import re
import sys

# "C - - - - - 0x01D803 07:D7F3: AD F0 05" becomes three spaces. As in the
# Lua, a dot matches a newline too: a line with fewer than three bytes takes
# its last ones from what follows.
COLUMNS = re.compile(
    r".\s.\s.\s.\s.\s.\s0x......\s..:....:\s..\s..\s...", re.S)


def main(argv):
    build = argv[1]
    for path in argv[2:]:
        with open(path, encoding="latin-1", newline="") as source:
            text = source.read()
        target = os.path.join(build, "copy_" + os.path.basename(path))
        with open(target, "w", encoding="latin-1", newline="") as copy:
            copy.write(COLUMNS.sub("   ", text))


if __name__ == "__main__":
    main(sys.argv)
