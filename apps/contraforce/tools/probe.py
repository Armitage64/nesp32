#!/usr/bin/env python3
"""The game's background test for fast/probe.inc, made from the disassembly
at build time, so that none of the game's code is kept in this repository.

    probe.py BANK_FF.ASM OUT.INC

It takes the game's script 00, from ofs_006_EE54_00 to the end of its
test (tbl_EF73), as it is, in a scope of its own, and changes three
things: where it finds the tile in the stage's metatile, from the metatile
to the load of the tile ($EEF3-$EF27, the bank's metatile through a
pointer), is the macro fast_probe_tile (fast/probe.inc), which reads the
copy in the PRG RAM; and each of its two RTSes is a jump to
fast_probe_done, which leaves the registers as execute_script would.
"""

import re
import sys

# The disassembly's left-hand columns, as tools/prepare.py takes them off.
COLUMNS = re.compile(r".\s.\s.\s.\s.\s.\s0x......\s..:....:\s..\s..\s...", re.S)
TAG = re.compile(r"0x[0-9A-F]{6} 07:([0-9A-F]{4}):")
FIRST, LAST = "ofs_006_EE54_00:", "tbl_EF73:"
TILE_FROM, TILE_TO = 0xEEF3, 0xEF27     # replaced by fast_probe_tile
RETURNS = (0xEF5C, 0xEF72)


def main(source, out):
    with open(source, encoding="latin-1") as handle:
        lines = handle.read().split("\n")
    start = lines.index(FIRST)
    end = lines.index(LAST, start)
    body = []
    tile_done = False
    for line in lines[start:end]:
        tag = TAG.search(line)
        address = int(tag.group(1), 16) if tag else None
        if address is not None and TILE_FROM <= address <= TILE_TO:
            if not tile_done:
                body.append("    fast_probe_tile")
                tile_done = True
            continue
        if address is None and TILE_FROM <= last_address(body) < TILE_TO and line.strip():
            continue                    # a label or comment within what is replaced
        if address in RETURNS:
            body.append("    JMP fast_probe_done")
            continue
        body.append(COLUMNS.sub("   ", line + "\n").rstrip("\n") if tag else line)
        if address is not None:
            body[-1] = body[-1] + "  ; $%04X" % address
    assert tile_done and sum("fast_probe_done" in line for line in body) == len(RETURNS)
    with open(out, "w") as handle:
        handle.write("; Made by tools/probe.py from the disassembly's bank_FF.asm. Not to be\n"
                     "; edited, or kept.\n.scope fast_probe_game\n")
        handle.write("\n".join(body))
        handle.write("\n.endscope\n")


def last_address(body):
    for line in reversed(body):
        found = re.search(r"; \$([0-9A-F]{4})$", line)
        if found:
            return int(found.group(1), 16)
        if line == "    fast_probe_tile":
            return TILE_FROM
    return 0


if __name__ == "__main__":
    main(*sys.argv[1:3])
