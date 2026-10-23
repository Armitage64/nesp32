#!/usr/bin/env python3
"""The game's writing of a metatile's tiles into the PPU's buffer, for
fast/columns.inc, made from the disassembly at build time, so that none of
the game's code is kept in this repository.

    columns.py BANK_FF.ASM OUT.INC

As the screen scrolls the game builds each new column or row of the
background from the stage's metatiles, and for each metatile writes its
tiles into the PPU's buffer from $EC26 on, a call to sub_ECE7 (or
sub_ECE6, one on) for each tile. This takes $EC26 to the end of sub_ECE7
as it is, in a scope of its own, with each of those calls the routine in
line: a JSR to it its body, a JMP to it its body and an RTS. A branch to
it is to its own copy, kept at the end as the game has it. With the
bodies in line some branches are too far for a branch: one to the RTS is
the other branch over an RTS of its own, and the one that is always taken
(sub_ECD0's BNE, "jmp") a JMP.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from probe import TAG, Inliner, code  # noqa: E402

FIRST, LAST = 0xEC26, 0xECEF    # from loc_EC26 to sub_ECE7's RTS
TILE = ("sub_ECE6", "sub_ECE7")
JMP_TILE = {"loc_ECE7": "sub_ECE7"}
RETURN = "bra_ECEF_RTS"
INVERSE = {"BEQ": "BNE", "BNE": "BEQ", "BCC": "BCS", "BCS": "BCC",
           "BMI": "BPL", "BPL": "BMI", "BVC": "BVS", "BVS": "BVC"}


class TileInliner(Inliner):
    def expand(self, body):
        out = []
        for line in body:
            words = line.split()
            if len(words) >= 2 and words[0] == "JSR" and words[1] in TILE:
                out.extend(self.copy(words[1]))
            elif len(words) >= 2 and words[0] == "JMP" and words[1] in JMP_TILE:
                out.extend(self.copy(JMP_TILE[words[1]]) + ["    RTS"])
            else:
                out.append(line)
        return out


def main(source, out):
    with open(source, encoding="latin-1") as handle:
        lines = handle.read().split("\n")
    body = []
    inside = False
    for line in lines:
        tag = TAG.search(line)
        address = int(tag.group(1), 16) if tag else None
        if address == FIRST:
            inside = True
            # The labels just before the first line are its own.
            while body and body[-1].endswith(":"):
                body.pop()
        if inside:
            body.append(code(line))
        elif address is None and line.endswith(":") and not body:
            pass
        if address == LAST:
            break
        if not inside and line.endswith(":"):
            body.append(line)
        elif not inside:
            body = []
    assert inside and body
    body = TileInliner(lines).expand(body)
    fixed = []
    for n, line in enumerate(body):
        words = line.split()
        if len(words) >= 2 and words[0] in INVERSE and words[1] == RETURN:
            skip = "fast_returned_%d" % n
            fixed += ["    %s %s" % (INVERSE[words[0]], skip), "    RTS", skip + ":"]
        elif len(words) >= 3 and words[0] == "BNE" and words[2:4] == [";", "jmp"]:
            fixed.append("    JMP %s" % words[1])
        else:
            fixed.append(line)
    body = fixed
    with open(out, "w") as handle:
        handle.write("; Made by tools/columns.py from the disassembly's bank_FF.asm. Not to\n"
                     "; be edited, or kept.\n.scope fast_columns_game\n")
        handle.write("\n".join(body))
        handle.write("\n.endscope\n")


if __name__ == "__main__":
    main(*sys.argv[1:3])
