#!/usr/bin/env python3
"""The game's background test for fast/probe.inc, made from the disassembly
at build time, so that none of the game's code is kept in this repository.

    probe.py BANK_FF.ASM OUT.INC

It takes the game's script 00, from ofs_006_EE54_00 to the end of its
test (tbl_EF73), as it is, in a scope of its own, and changes four
things: where it finds the tile in the stage's metatile, from the metatile
to the load of the tile ($EEF3-$EF27, the bank's metatile through a
pointer), is the macro fast_probe_tile (fast/probe.inc), which reads the
copy in the PRG RAM; each of its two RTSes is a jump to fast_probe_done,
which leaves the registers as execute_script would; and each call to one
of the small routines it works the point's place out with (INLINE) is
that routine itself in line, its labels its own and its RTS left out,
those it calls in line too.
"""

import re
import sys

# The disassembly's left-hand columns, as tools/prepare.py takes them off.
COLUMNS = re.compile(r".\s.\s.\s.\s.\s.\s0x......\s..:....:\s..\s..\s...", re.S)
TAG = re.compile(r"0x[0-9A-F]{6} 07:([0-9A-F]{4}):")
FIRST, LAST = "ofs_006_EE54_00:", "tbl_EF73:"
TILE_FROM, TILE_TO = 0xEEF3, 0xEF27     # replaced by fast_probe_tile
RETURNS = (0xEF5C, 0xEF72)
# The routines put in line where they are called. Each runs from its label
# to its first RTS, falling through into the next where it does.
INLINE = ("sub_F066", "sub_F068", "sub_F078", "sub_F098", "sub_F0A4", "sub_F0AD")
CALL = re.compile(r"^\s*JSR (\w+)")
LABEL = re.compile(r"^(\w+):")


def code(line):
    """A listing's line as ca65 takes it, its address after it."""
    tag = TAG.search(line)
    if not tag:
        return line
    return COLUMNS.sub("   ", line + "\n").rstrip("\n") + "  ; $" + tag.group(1)


def routine(lines, name):
    """The lines of a routine, from its label to its first RTS (left out)."""
    start = lines.index(name + ":")
    body = []
    for line in lines[start + 1:]:
        text = code(line)
        if re.match(r"^\s*RTS\b", text):
            return body
        body.append(text)
    raise ValueError("no RTS after " + name)


class Inliner:
    def __init__(self, lines):
        self.lines = lines
        self.copies = 0

    def expand(self, body):
        """The lines with each call to an INLINE routine replaced by it."""
        out = []
        for line in body:
            call = CALL.match(line)
            if call and call.group(1) in INLINE:
                out.extend(self.copy(call.group(1)))
            else:
                out.append(line)
        return out

    def copy(self, name):
        self.copies += 1
        suffix = "_in%d" % self.copies
        body = routine(self.lines, name)
        labels = {LABEL.match(line).group(1) for line in body if LABEL.match(line)}
        renamed = []
        for line in body:
            for label in labels:
                line = re.sub(r"\b%s\b" % label, label + suffix, line)
            renamed.append(line)
        end = "fast_inline_end" + suffix
        # A branch to the RTS's own label is a branch to the end.
        renamed = [re.sub(r"\b(bra_\w+_RTS%s)\b" % suffix, end, line) for line in renamed]
        renamed = [line for line in renamed if line != end + ":"]
        return ["; %s, in line" % name] + self.expand(renamed) + [end + ":"]


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
        body.append(code(line))
    assert tile_done and sum("fast_probe_done" in line for line in body) == len(RETURNS)
    inliner = Inliner(lines)
    body = inliner.expand(body)
    assert not any(CALL.match(line) and CALL.match(line).group(1) in INLINE for line in body)
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
