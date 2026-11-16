#!/usr/bin/env python3
"""Make ca65 source of River City Ransom from the ROM and the map of it here.

    convert.py BASEROM DIRECTORY

There is no disassembly of the game to start from, so this is one. Every
byte comes from the ROM. What is code is found by following it from where
it is known to start: the vectors, the places tools/game.map names, and
tools/entries.txt, the runs of instructions the game was seen to run on
the simulated console (tools/trace.py writes it), which are placed first.
Its tables of addresses are many, so following alone would miss much.
Everything else is data. Neither file holds any of the game: only
addresses, names and comments.

Each instruction is decoded from the ROM, with its addressing mode as it
is there, and its operand is written as a name where the address has one:
a label in the bank itself or in the fixed bank, a variable of
tools/game.map's, or a register. Anywhere else it is a number. Code in the
fixed bank that names an address in $8000-$BFFF does not know which bank
is there, and has a number.

The cartridge is an MMC3 with 128 KB of PRG. The game only ever switches
it 16 KB at a time, R6 and R7 to two 8 KB banks that make one pair
($FED1), and keeps the last pair at $C000, as the MMC3 does: so it is
written here as eight banks of 16 KB, the last fixed.

Two things are there for code to be added to the game without moving any
of it. Each run of $FF or $00 that is not code, FREE bytes or more, is a label of
its own, FREE_b_oooo (its bank and its offset), and an assembly that
defines HAVE_FREE_b_oooo and a macro FILL_FREE_b_oooo has the macro there,
with the rest of the run as it was: a macro that does not fit is an error.
(To ca65 a macro's name begins a call to it wherever it starts a line, a
label's place included, so the three names differ.) And each label asserts
its address, which ld65 checks, so a change to the game that moves any of
it does not link.

Made under the directory: src/rcr.asm (the eight banks, each in
its own segment), src/ram.inc (the map's variables and the registers),
src/header.asm (the ROM's iNES header), and chr.bin (its CHR ROM).
"""

import os
import re
import sys

BANKS = 8
BANK_SIZE = 0x4000
FIXED = BANKS - 1
HEADER = 16
FREE = 32               # the shortest run of $FF or $00 that is room for code
VECTORS = 0x3FFA        # in the fixed bank: NMI, reset, IRQ

HERE = os.path.dirname(os.path.abspath(__file__))
MAP = os.path.join(HERE, "game.map")
ENTRIES = os.path.join(HERE, "entries.txt")

# The official opcodes: mnemonic and addressing mode.
MODES = {
    "imp": 1, "acc": 1, "imm": 2, "zp": 2, "zpx": 2, "zpy": 2, "izx": 2,
    "izy": 2, "rel": 2, "abs": 3, "abx": 3, "aby": 3, "ind": 3,
}
OPCODES = {}


def _opcodes(mnemonic, *pairs):
    for code, mode in zip(pairs[::2], pairs[1::2]):
        OPCODES[code] = (mnemonic, mode)


_opcodes("ADC", 0x69, "imm", 0x65, "zp", 0x75, "zpx", 0x6D, "abs", 0x7D, "abx",
         0x79, "aby", 0x61, "izx", 0x71, "izy")
_opcodes("AND", 0x29, "imm", 0x25, "zp", 0x35, "zpx", 0x2D, "abs", 0x3D, "abx",
         0x39, "aby", 0x21, "izx", 0x31, "izy")
_opcodes("ASL", 0x0A, "acc", 0x06, "zp", 0x16, "zpx", 0x0E, "abs", 0x1E, "abx")
_opcodes("BIT", 0x24, "zp", 0x2C, "abs")
_opcodes("CMP", 0xC9, "imm", 0xC5, "zp", 0xD5, "zpx", 0xCD, "abs", 0xDD, "abx",
         0xD9, "aby", 0xC1, "izx", 0xD1, "izy")
_opcodes("CPX", 0xE0, "imm", 0xE4, "zp", 0xEC, "abs")
_opcodes("CPY", 0xC0, "imm", 0xC4, "zp", 0xCC, "abs")
_opcodes("DEC", 0xC6, "zp", 0xD6, "zpx", 0xCE, "abs", 0xDE, "abx")
_opcodes("EOR", 0x49, "imm", 0x45, "zp", 0x55, "zpx", 0x4D, "abs", 0x5D, "abx",
         0x59, "aby", 0x41, "izx", 0x51, "izy")
_opcodes("INC", 0xE6, "zp", 0xF6, "zpx", 0xEE, "abs", 0xFE, "abx")
_opcodes("JMP", 0x4C, "abs", 0x6C, "ind")
_opcodes("JSR", 0x20, "abs")
_opcodes("LDA", 0xA9, "imm", 0xA5, "zp", 0xB5, "zpx", 0xAD, "abs", 0xBD, "abx",
         0xB9, "aby", 0xA1, "izx", 0xB1, "izy")
_opcodes("LDX", 0xA2, "imm", 0xA6, "zp", 0xB6, "zpy", 0xAE, "abs", 0xBE, "aby")
_opcodes("LDY", 0xA0, "imm", 0xA4, "zp", 0xB4, "zpx", 0xAC, "abs", 0xBC, "abx")
_opcodes("LSR", 0x4A, "acc", 0x46, "zp", 0x56, "zpx", 0x4E, "abs", 0x5E, "abx")
_opcodes("ORA", 0x09, "imm", 0x05, "zp", 0x15, "zpx", 0x0D, "abs", 0x1D, "abx",
         0x19, "aby", 0x01, "izx", 0x11, "izy")
_opcodes("ROL", 0x2A, "acc", 0x26, "zp", 0x36, "zpx", 0x2E, "abs", 0x3E, "abx")
_opcodes("ROR", 0x6A, "acc", 0x66, "zp", 0x76, "zpx", 0x6E, "abs", 0x7E, "abx")
_opcodes("SBC", 0xE9, "imm", 0xE5, "zp", 0xF5, "zpx", 0xED, "abs", 0xFD, "abx",
         0xF9, "aby", 0xE1, "izx", 0xF1, "izy")
_opcodes("STA", 0x85, "zp", 0x95, "zpx", 0x8D, "abs", 0x9D, "abx", 0x99, "aby",
         0x81, "izx", 0x91, "izy")
_opcodes("STX", 0x86, "zp", 0x96, "zpy", 0x8E, "abs")
_opcodes("STY", 0x84, "zp", 0x94, "zpx", 0x8C, "abs")
for _m, _c in (("BPL", 0x10), ("BMI", 0x30), ("BVC", 0x50), ("BVS", 0x70),
               ("BCC", 0x90), ("BCS", 0xB0), ("BNE", 0xD0), ("BEQ", 0xF0)):
    OPCODES[_c] = (_m, "rel")
for _m, _c in (("BRK", 0x00), ("PHP", 0x08), ("CLC", 0x18), ("PLP", 0x28),
               ("SEC", 0x38), ("RTI", 0x40), ("PHA", 0x48), ("CLI", 0x58),
               ("RTS", 0x60), ("PLA", 0x68), ("SEI", 0x78), ("DEY", 0x88),
               ("TXA", 0x8A), ("TYA", 0x98), ("TXS", 0x9A), ("TAY", 0xA8),
               ("TAX", 0xAA), ("CLV", 0xB8), ("TSX", 0xBA), ("INY", 0xC8),
               ("DEX", 0xCA), ("CLD", 0xD8), ("INX", 0xE8), ("NOP", 0xEA),
               ("SED", 0xF8)):
    OPCODES[_c] = (_m, "imp")

# Where following an instruction stops: nothing comes after it.
ENDS = {"RTS", "RTI", "JMP", "BRK"}
# The instructions that write their operand: to ROM space, the mapper.
WRITES = {"STA", "STX", "STY", "INC", "DEC", "ASL", "LSR", "ROL", "ROR"}
# ca65's own words, which no name may be.
RESERVED = {"A", "X", "Y", "S"} | {m for m, _ in OPCODES.values()}

REGISTERS = {
    "PPUCTRL": 0x2000, "PPUMASK": 0x2001, "PPUSTATUS": 0x2002, "OAMADDR": 0x2003,
    "OAMDATA": 0x2004, "PPUSCROLL": 0x2005, "PPUADDR": 0x2006, "PPUDATA": 0x2007,
    "SQ1_VOL": 0x4000, "SQ1_SWEEP": 0x4001, "SQ1_LO": 0x4002, "SQ1_HI": 0x4003,
    "SQ2_VOL": 0x4004, "SQ2_SWEEP": 0x4005, "SQ2_LO": 0x4006, "SQ2_HI": 0x4007,
    "TRI_LINEAR": 0x4008, "TRI_LO": 0x400A, "TRI_HI": 0x400B,
    "NOISE_VOL": 0x400C, "NOISE_LO": 0x400E, "NOISE_HI": 0x400F,
    "DMC_FREQ": 0x4010, "DMC_RAW": 0x4011, "DMC_START": 0x4012, "DMC_LEN": 0x4013,
    "OAMDMA": 0x4014, "APU_STATUS": 0x4015, "JOY1": 0x4016, "JOY2": 0x4017,
}


def base(bank):
    return 0xC000 if bank == FIXED else 0x8000


def where(bank, address):
    """The bank an address is in, as code in `bank` sees it; None for
    $8000-$BFFF seen from the fixed bank, and for what is not ROM."""
    if address >= 0xC000:
        return FIXED
    if address >= 0x8000 and bank != FIXED:
        return bank
    return None


def decode(prg, bank, offset):
    """(mnemonic, mode, size, operand) of the instruction at an offset of a
    bank, or None if its byte is no official opcode or it runs off the
    bank's end."""
    data = prg[bank * BANK_SIZE:(bank + 1) * BANK_SIZE]
    opcode = OPCODES.get(data[offset])
    if opcode is None:
        return None
    mnemonic, mode = opcode
    size = MODES[mode]
    if offset + size > BANK_SIZE:
        return None
    if size == 1:
        value = None
    elif size == 2:
        value = data[offset + 1]
        if mode == "rel":
            value = (base(bank) + offset + 2 + (value ^ 0x80) - 0x80) & 0xFFFF
    else:
        value = data[offset + 1] | data[offset + 2] << 8
    return mnemonic, mode, size, value


class Code:
    """What of the PRG is code: {(bank, offset): (mnemonic, mode, size,
    operand)}, as the runs of it the game was seen to run place it, and as
    following it from there and from the entries finds more."""

    def __init__(self, prg, inline=None):
        self.prg = prg
        self.code = {}
        self.covered = set()            # (bank, offset): every byte of an instruction
        # Routines that take bytes after the JSR that calls them, and return
        # past them: {address in the fixed bank: how many}.
        self.inline = inline or {}
        self.args = {}                  # (bank, offset): bytes a JSR's routine takes there

    def place(self, bank, address):
        """The instruction at an address, unless one already found has any
        of its bytes. Its size, or None if it is no instruction."""
        offset = address - base(bank)
        instruction = decode(self.prg, bank, offset)
        if instruction is None:
            return None
        size = instruction[2]
        if (bank, offset) in self.args:
            return None
        if not any((bank, offset + at) in self.covered for at in range(size)):
            self.code[(bank, offset)] = instruction
            self.covered.update((bank, offset + at) for at in range(size))
        return size

    def successors(self, bank, offset):
        """Where code goes from the instruction at an offset: its branch's
        or call's target, and the next instruction unless it ends a path."""
        mnemonic, mode, size, value = self.code[(bank, offset)]
        out = []
        if mode == "rel" or (mnemonic in ("JSR", "JMP") and mode == "abs"):
            out.append((bank, value))
        if mnemonic == "JSR" and value in self.inline:
            self.args[(bank, offset + size)] = self.inline[value]
            size += self.inline[value]
        if mnemonic not in ENDS:
            out.append((bank, base(bank) + offset + size))
        return out

    def follow(self, bank, address):
        """Follow the code from an address: its branches and calls into
        what its bank can see, until each path ends. A path that comes to
        a byte that is part of another instruction already found ends
        there."""
        todo = [(bank, address)]
        while todo:
            bank, address = todo.pop()
            bank = where(bank, address)
            if bank is None:
                continue
            offset = address - base(bank)
            if (bank, offset) in self.code or (bank, offset) in self.covered:
                continue
            if self.place(bank, address) is None or (bank, offset) not in self.code:
                continue
            todo.extend(self.successors(bank, offset))


class Map:
    """tools/game.map: names, comments, and where code begins.

        code  B:ADDR  NAME   comment      code, and its name
        entry B:ADDR                      code, with no name
        run   B:ADDR  LAST                instructions seen run, one after
                                          another from ADDR to the one at LAST
        inline B:ADDR N NAME comment      code that takes N bytes after the JSR
                                          that calls it, and returns past them
        data  B:ADDR  NAME   comment      a name for data
        ram   ADDR    NAME   comment      a variable, or the first of several
        note  B:ADDR         comment      a comment over the line there

    B is the bank (7 the fixed one); a name of - is none."""

    def __init__(self, paths):
        self.labels = {}       # (bank, offset) -> name
        self.comments = {}     # (bank, offset) -> [comment]
        self.entries = []      # (bank, address)
        self.runs = []         # (bank, first address, last instruction's)
        self.inline = {}       # routine's address -> bytes it takes after its JSR
        self.ram = {}          # address -> name
        self.ram_comments = {}
        for path in paths:
            if os.path.isfile(path):
                self._read(path)

    def _read(self, path):
        with open(path) as handle:
            for number, line in enumerate(handle, 1):
                line = line.rstrip()
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                words = line.split(None, 3)
                kind = words[0]
                if kind == "ram":
                    address = int(words[1], 16)
                    self.ram[address] = words[2]
                    if len(words) > 3:
                        self.ram_comments[address] = words[3]
                    continue
                if kind == "inline":
                    words = line.split(None, 4)
                    bank, address = words[1].split(":")
                    self.inline[int(address, 16)] = int(words[2])
                    self.labels[(int(bank), int(address, 16) - base(int(bank)))] = words[3]
                    if len(words) > 4:
                        self.comments.setdefault(
                            (int(bank), int(address, 16) - base(int(bank))), []).append(words[4])
                    self.entries.append((int(bank), int(address, 16)))
                    continue
                if kind == "run":
                    bank, first = words[1].split(":")
                    self.runs.append((int(bank), int(first, 16), int(words[2], 16)))
                    continue
                match = re.match(r"([0-7]):([0-9A-Fa-f]{4})$", words[1])
                if not match:
                    raise SystemExit("%s:%d: not B:ADDR: %s" % (path, number, words[1]))
                bank, address = int(match.group(1)), int(match.group(2), 16)
                key = (bank, address - base(bank))
                if kind in ("code", "entry"):
                    self.entries.append((bank, address))
                rest = words[2:]
                if kind == "note":
                    rest = ["-"] + [" ".join(words[2:])] if len(words) > 2 else []
                if kind != "entry" and rest:
                    if rest[0] != "-":
                        self.labels[key] = rest[0]
                    if len(rest) > 1:
                        self.comments.setdefault(key, []).append(rest[1])


def find_code(prg, runs, entries=(), inline=None):
    """The code: the runs of it that the game was seen to run, placed
    first, whatever following another path would make of their bytes;
    then what following each of their instructions, the entries, in the
    order given, and the vectors reaches."""
    code = Code(prg, inline)
    for bank, start, last in runs:
        address = start
        while address <= last:
            address += code.place(bank, address)
    for bank, offset in list(code.code):
        code.successors(bank, offset)       # the inline bytes after each call
    for bank, offset in list(code.code):
        for target in code.successors(bank, offset):
            code.follow(*target)
    for bank, address in entries:
        code.follow(bank, address)
    for vector in range(3):
        code.follow(FIXED, fixed_word(prg, VECTORS + 2 * vector))
    return code


class Converter:

    def __init__(self, rom, paths=(ENTRIES, MAP)):
        self.rom = rom
        self.prg = rom[HEADER:HEADER + BANKS * BANK_SIZE]
        self.map = Map(paths)
        self.code = find_code(self.prg, self.map.runs, self.map.entries, self.map.inline)
        self.ram_by_value = dict((value, name) for value, name in self.map.ram.items())
        self.registers = dict((value, name) for name, value in REGISTERS.items())
        self.names = dict(self.map.labels)
        self.vectors = [fixed_word(self.prg, VECTORS + 2 * at) for at in range(3)]

    def data(self, bank):
        return self.prg[bank * BANK_SIZE:(bank + 1) * BANK_SIZE]

    def boundary(self, bank, offset):
        """Whether a line of the output can start at this offset: not inside
        an instruction, nor in the fixed bank's vectors."""
        if bank == FIXED and offset > VECTORS:
            return False
        for back in (1, 2):
            at = (bank, offset - back)
            if at in self.code.code and self.code.code[at][2] > back:
                return False
        return 0 <= offset < BANK_SIZE

    def target(self, bank, address):
        """A name for an address in ROM space, as code in this bank sees it."""
        number = where(bank, address)
        if number is None:
            return None
        offset = address - base(number)
        if not self.boundary(number, offset):
            return None
        key = (number, offset)
        if key not in self.names:
            self.names[key] = "L%d_%04X" % (number, address)
        return self.names[key]

    def operand_text(self, bank, offset):
        mnemonic, mode, size, value = self.code.code[(bank, offset)]
        if mode == "imp":
            return ""
        if mode == "acc":
            return " a"
        if mode == "imm":
            return " #$%02X" % value
        if mode == "rel":
            # Only to a name in this bank: ca65 cannot reach another
            # segment, or an address with none, in a branch.
            number = where(bank, value)
            if number == bank and self.boundary(bank, value - base(bank)):
                return " " + self.target(bank, value)
            return None
        name = None
        if value >= 0x8000:
            if mnemonic not in WRITES:
                name = self.target(bank, value)
        elif value >= 0x2000:
            name = self.registers.get(value) or self.ram_by_value.get(value)
        else:
            name = self.ram_by_value.get(value)
        if size == 2:
            text = name or "$%02X" % value
            prefix = ""
        else:
            text = name or "$%04X" % value
            # JMP's indirect is only ever absolute.
            prefix = "a:" if value < 0x100 and mode != "ind" else ""
        return " " + {
            "zp": "{p}{t}", "zpx": "{p}{t},x", "zpy": "{p}{t},y",
            "abs": "{p}{t}", "abx": "{p}{t},x", "aby": "{p}{t},y",
            "izx": "({p}{t},x)", "izy": "({p}{t}),y", "ind": "({p}{t})",
        }[mode].format(p=prefix, t=text)

    def free_runs(self, bank):
        """{offset: (length, fill)} of the runs of $FF or of $00 that are
        not code, and that no name or comment is in after the first byte."""
        data = self.data(bank)
        end = VECTORS if bank == FIXED else BANK_SIZE
        runs = {}
        start = None
        for offset in range(end + 1):
            if start is not None and offset < end and data[offset] != data[start]:
                if offset - start >= FREE:
                    runs[start] = (offset - start, data[start])
                start = None
            empty = (offset < end and data[offset] in (0x00, 0xFF)
                     and (bank, offset) not in self.code.covered)
            inside = start is not None and (
                (bank, offset) in self.names or (bank, offset) in self.map.comments)
            if start is not None and (not empty or inside):
                if offset - start >= FREE:
                    runs[start] = (offset - start, data[start])
                start = None
            if empty and start is None:
                start = offset
        return runs

    def bank_lines(self, bank, texts):
        lines = ['.segment "BANK%d"' % bank, ""]
        data = self.data(bank)
        offset = 0
        pending = []

        def flush():
            for start in range(0, len(pending), 16):
                lines.append("    .byte " + ",".join("$%02X" % b for b in pending[start:start + 16]))
            pending.clear()

        free = self.free_runs(bank)
        end = VECTORS if bank == FIXED else BANK_SIZE
        while offset < end:
            key = (bank, offset)
            name = self.names.get(key)
            notes = self.map.comments.get(key, [])
            if name or notes:
                flush()
            if notes and name:
                lines.append("")
            for note in notes:
                lines.append("; " + note)
            if name:
                lines.append("%s:" % name)
                lines.append("    .assert * = $%04X, error" % (base(bank) + offset))
            if offset in free:
                flush()
                length, fill = free[offset]
                label = "FREE_%d_%04X" % (bank, offset)
                lines += ["%s: ; %d bytes of $%02X that are not code" % (label, length, fill),
                          "    .assert * = $%04X, error" % (base(bank) + offset),
                          ".ifdef HAVE_%s" % label,
                          "    FILL_%s" % label,
                          ".endif",
                          "    .res %d - (* - %s), $%02X" % (length, label, fill)]
                offset += length
                continue
            if key in self.code.args and self.code.args[key] == 2 and not any(
                    (bank, offset + 1) == other for other in self.names):
                flush()
                value = data[offset] | data[offset + 1] << 8
                lines.append("    .addr " + (self.target(bank, value) or "$%04X" % value))
                offset += 2
                continue
            if key in self.code.code:
                flush()
                mnemonic, mode, size, value = self.code.code[key]
                if texts[offset] is None:
                    lines.append("    .byte $%02X,$%02X ; %s $%04X" % (
                        data[offset], data[offset + 1], mnemonic.lower(), value))
                else:
                    lines.append("    %s%s" % (mnemonic.lower(), texts[offset]))
                offset += size
                continue
            pending.append(data[offset])
            if len(pending) == 16:
                flush()
            offset += 1
        flush()
        if bank == FIXED:
            names = [self.target(FIXED, vector) or "$%04X" % vector for vector in self.vectors]
            lines += ["", "VECTORS:", "    .assert * = $%04X, error" % (0xC000 + VECTORS),
                      "    .addr " + ", ".join(names)]
        return lines

    def write(self, root):
        src = os.path.join(root, "src")
        os.makedirs(src, exist_ok=True)
        # Every operand first: naming one may name an address in any bank.
        texts = [{offset: self.operand_text(bank, offset)
                  for (number, offset) in self.code.code if number == bank}
                 for bank in range(BANKS)]
        for vector in self.vectors:
            self.target(FIXED, vector)
        for (bank, offset), count in self.code.args.items():
            if count == 2:
                data = self.data(bank)
                self.target(bank, data[offset] | data[offset + 1] << 8)
        banks = [self.bank_lines(bank, texts[bank]) for bank in range(BANKS)]
        with open(os.path.join(src, "rcr.asm"), "w") as out:
            out.write("; Made by tools/convert.py from the ROM and tools/game.map. The bytes\n")
            out.write("; are the ROM's.\n\n")
            out.write('.include "ram.inc"\n\n')
            for lines in banks:
                out.write("\n".join(lines) + "\n\n")
        with open(os.path.join(src, "ram.inc"), "w") as out:
            for name, value in sorted(REGISTERS.items(), key=lambda e: e[1]):
                out.write("%s = $%04X\n" % (name, value))
            for address in sorted(self.map.ram):
                line = "%s = $%04X" % (self.map.ram[address], address)
                if address in self.map.ram_comments:
                    line = "%-31s ; %s" % (line, self.map.ram_comments[address])
                out.write(line + "\n")
        header = self.rom[:HEADER]
        with open(os.path.join(src, "header.asm"), "w") as out:
            out.write('.segment "HEADER"\n    .byte ' +
                      ",".join("$%02X" % b for b in header) + "\n")
        prg = header[4] * 0x4000
        with open(os.path.join(root, "chr.bin"), "wb") as out:
            out.write(self.rom[HEADER + prg:])


def fixed_word(prg, offset):
    at = FIXED * BANK_SIZE + offset
    return prg[at] | prg[at + 1] << 8


def main(rom_path, root):
    with open(rom_path, "rb") as handle:
        rom = handle.read()
    converter = Converter(rom)
    converter.write(root)
    print("%d bytes of the PRG's %d are code" % (len(converter.code.covered), BANKS * BANK_SIZE))


if __name__ == "__main__":
    main(*sys.argv[1:])
