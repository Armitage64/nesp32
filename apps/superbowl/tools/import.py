#!/usr/bin/env python3
"""Make tools/game.map from the disassembly of Tecmo Super Bowl.

    import.py ASM6F DISASSEMBLY BASEROM MAP

The disassembly (third_party/Tecmo_Super_Bowl_NES_Disassembly) is asm6f
source, whose macros ca65 cannot take as they are: they choose an
instruction by how far a label is that comes later, and use asm6f's own
words. So it is not converted line by line. asm6f assembles it, once, here
(the build does not need asm6f), and this reads what it lists: for each line
that makes bytes, where they are in the ROM and whether they are an
instruction, with the macros' lines one by one, and every name the source
gives a value. tools/convert.py then makes ca65 source of the ROM with them.

The map holds addresses, names and comments, none of the game's bytes:
asm6f's listing has each line's first bytes, which are checked against the
ROM here and left out.

The disassembly takes the ROM as TSB.nes beside its master_build.asm, for
its graphics and samples, so it is assembled in a copy, in a temporary
directory.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

HEADER = 16
PRG_SIZE = 0x40000
BANK = 0x2000

MNEMONICS = set("""ADC AND ASL BCC BCS BEQ BIT BMI BNE BPL BRK BVC BVS CLC CLD CLI CLV
CMP CPX CPY DEC DEX DEY EOR INC INX INY JMP JSR LDA LDX LDY LSR NOP ORA PHA PHP PLA
PLP ROL ROR RTI RTS SBC SEC SED SEI STA STX STY TAX TAY TSX TXA TXS TYA""".split())

LINE = re.compile(r"^([0-9A-F]{5}) (.{26})(.*)$")


def assemble(asm6f, disassembly, baserom, work):
    shutil.copytree(disassembly, work, ignore=shutil.ignore_patterns(".git"))
    shutil.copy(baserom, os.path.join(work, "TSB.nes"))
    subprocess.run([asm6f, "-L", "-f", "-q", "master_build.asm", "out.nes", "out.lst"],
                   cwd=work, check=True)
    with open(os.path.join(work, "out.nes"), "rb") as handle, open(baserom, "rb") as rom:
        if handle.read() != rom.read():
            raise SystemExit("the disassembly does not assemble to %s" % baserom)
    symbols = {}
    with open(os.path.join(work, "out.lua"), encoding="latin-1") as handle:
        for line in handle:
            name, _, value = line.strip().partition(" = ")
            if value.startswith("0x"):
                symbols[name] = int(value, 16)
    with open(os.path.join(work, "out.lst"), encoding="latin-1") as handle:
        return symbols, handle.read().splitlines()


def split_comment(text):
    """(code, comment) of a line of source; a ; in quotes is not one."""
    quote = None
    for at, char in enumerate(text):
        if quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == ";":
            return text[:at], text[at + 1:]
    return text, ""


def clean(comment):
    comment = comment.strip().strip(";").strip()
    comment = re.sub(r"[^\x20-\x7E]", "'", comment)
    return comment if re.search(r"[A-Za-z0-9]", comment) else ""


def operand(code):
    """The expression of an instruction's operand as the source has it,
    without its addressing mode's marks; None if it has none."""
    parts = code.split(None, 1)
    if len(parts) < 2:
        return None
    text = parts[1].strip()
    if not text or text.upper() == "A":
        return None
    if text.startswith("#"):
        return text[1:].strip()
    text = re.sub(r",\s*[XxYy]\s*$", "", text)
    if text.startswith("(") and text.endswith(")") and text.count("(") == 1:
        text = text[1:-1]
    text = re.sub(r",\s*[XxYy]\s*$", "", text)
    return text.strip()


def read(lines, rom, symbols):
    """The listing's lines that are the PRG's, in order: (offset in the
    file, address, length or 0, source)."""
    rows = []
    in_enum = False
    for line in lines:
        match = LINE.match(line)
        source = match.group(3) if match else line[32:] if len(line) > 32 else ""
        directive = source.strip().upper()
        if directive.startswith(".ENUM"):
            in_enum = True
            continue
        if directive.startswith(".ENDE"):
            in_enum = False
            continue
        if not match or in_enum:
            continue
        shown = match.group(2).strip()
        truncated = shown.endswith("..")
        shown = bytes(int(b, 16) for b in shown.rstrip(".").split())
        rows.append([int(match.group(1), 16), shown, truncated, source])
    out = []
    offset = HEADER          # the header's lines have no address
    for at, (address, shown, truncated, source) in enumerate(rows):
        length = len(shown)
        if truncated:
            following = next(row for row in rows[at + 1:] if row[1] or row[0] != address)
            length = following[0] - address
        if length and rom[offset:offset + len(shown)] != shown:
            raise SystemExit("listing and ROM differ at $%05X: %s" % (offset, source.strip()))
        out.append((offset, address, length, source))
        offset += length
        if offset >= HEADER + PRG_SIZE:
            break
    if offset != HEADER + PRG_SIZE:
        raise SystemExit("the listing's PRG ends at $%X" % offset)
    return out


def write_map(rows, symbols, macros, path):
    banks = {}
    labels = []
    entries = []          # (bank, address, kind, text)
    code_runs = []        # [bank, address, length]
    notes = []
    for offset, address, length, source in rows:
        if offset < HEADER:
            continue
        prg = offset - HEADER
        bank = prg // BANK
        if length and bank not in banks:
            banks[bank] = address - prg % BANK
        if not length:
            code, comment = split_comment(source)
            word = code.strip().split(None, 1)[0] if code.strip() else ""
            label = word.rstrip(":")
            at_column_0 = code[:1] not in ("", " ", "\t")
            if label and (word.endswith(":") or at_column_0) and \
                    re.match(r"^@?[A-Za-z_][\w\[\]{}]*$", label) and \
                    (label.startswith("@") or symbols.get(label) == address) and \
                    not label.startswith("_F"):
                labels.append((bank, prg, address, label))
                comment = clean(comment)
                if comment:
                    notes.append((bank, prg, address, comment))
                continue
            if not code.strip():
                text = clean(comment)
            elif word in macros:
                # A macro's call: its instructions follow, line by line.
                text = "(macro) " + " ".join(code.split())
                if clean(comment):
                    text += "  ; " + clean(comment)
            else:
                continue        # asm6f's own words: IF, ENDIF, =, ...
            if text:
                notes.append((bank, prg, address, text))
            continue
        code, comment = split_comment(source)
        words = code.split()
        is_code = bool(words) and words[0].upper() in MNEMONICS
        comment = clean(comment)
        if is_code:
            if code_runs and code_runs[-1][0] == bank and \
                    code_runs[-1][1] + code_runs[-1][2] == prg:
                code_runs[-1][2] += length
            else:
                code_runs.append([bank, prg, length])
            expression = operand(code.strip())
            if expression and not re.fullmatch(r"\$[0-9A-Fa-f]+|%[01]+|\d+", expression):
                entries.append((bank, prg, "i", expression + (" ; " + comment if comment else "")))
            elif comment:
                entries.append((bank, prg, "i", "; " + comment))
        elif comment:
            entries.append((bank, prg, "d", "; " + comment))
    label_values = {name for _, _, _, name in labels}

    def where(bank, prg):
        return "%d:%04X" % (bank, banks[bank] + prg % BANK)

    with open(path, "w") as out:
        out.write("# Tecmo Super Bowl (USA): names and comments for tools/convert.py, made\n")
        out.write("# by tools/import.py from the disassembly's listing. Addresses, names\n")
        out.write("# and comments only, none of the game's bytes. Each line:\n#\n")
        out.write("#   bank B ADDR          the 8 KB bank B is at ADDR\n")
        out.write("#   sym NAME VALUE       a name the source gives a value, not a label\n")
        out.write("#   c B:ADDR LENGTH      a run of instructions\n")
        out.write("#   l B:ADDR NAME        a label\n")
        out.write("#   n B:ADDR TEXT        a comment over the line there\n")
        out.write("#   i B:ADDR EXPR ; TEXT the instruction there: its operand as the source\n")
        out.write("#                        has it, and its comment (either may be missing)\n")
        out.write("#   d B:ADDR ; TEXT      a comment on the data there\n\n")
        for bank in sorted(banks):
            out.write("bank %d %04X\n" % (bank, banks[bank]))
        out.write("\n")
        for name in sorted(symbols):
            if name in label_values or name.startswith("@") or name.startswith("_F"):
                continue
            out.write("sym %s %X\n" % (name, symbols[name]))
        out.write("\n")
        for bank, prg, length in code_runs:
            out.write("c %s %X\n" % (where(bank, prg), length))
        out.write("\n")
        merged = sorted(
            [(bank, prg, 0, "l", name) for bank, prg, _, name in labels]
            + [(bank, prg, 1, "n", text) for bank, prg, _, text in notes]
            + [(bank, prg, 2, kind, text) for bank, prg, kind, text in entries],
            key=lambda e: (e[0], e[1]))
        for bank, prg, _, kind, text in merged:
            out.write("%s %s %s\n" % (kind, where(bank, prg), text))


def main(asm6f, disassembly, baserom, path):
    with open(baserom, "rb") as handle:
        rom = handle.read()
    with tempfile.TemporaryDirectory() as temp:
        symbols, lines = assemble(asm6f, disassembly, baserom, os.path.join(temp, "tsb"))
    rows = read(lines, rom, symbols)
    macros = set()
    for line in lines:
        match = re.match(r"\s*\.MACRO\s+(\S+)", line[32:] if len(line) > 32 else "", re.I)
        if match:
            macros.add(match.group(1))
    write_map(rows, symbols, macros, path)


if __name__ == "__main__":
    main(*sys.argv[1:])
