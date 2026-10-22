#!/usr/bin/env python3
"""Make ca65 source of TMNT II from Aaron Bottegal's disassembly and the ROM.

    convert.py DISASSEMBLY BASEROM DIRECTORY

The disassembly (a submodule at the top of this repository) is a listing
to read, not a source to build: its labels have characters no assembler
takes, many names are used more than once, and in places code is read
where there is data. So it is not translated line by line. Every byte
comes from the ROM. The listing says only which bytes are instructions and
which are data, what each address is called, and what the comments say.

Each instruction is decoded from the ROM, with its addressing mode as it is
there, and its operand is written as a name where the address has one that
the assembler can be trusted with: a label in the bank itself, in the bank
paired with it, or in the fixed banks, a variable, or a register. Anywhere
else it is a number. A line of the listing whose instruction is not the
ROM's is taken for data, as is anything the listing does not reach.

The game's MMC3 holds two switchable 8 KB banks at $8000 and $A000, which
it always switches together, an even bank and the odd one after it, and
the last two banks fixed at $C000 and $E000.

Two things are there for code to be added to the game without moving
any of it. Each run of $FF that nothing is listed in, FREE bytes or more,
is a label of its own, FREE_bb_oooo (its bank and its offset), and an
assembly that defines HAVE_FREE_bb_oooo and a macro FILL_FREE_bb_oooo has
the macro there, with the rest of the run still $FF: a macro that does not
fit is an error. (To ca65 a macro's name begins a call to it wherever it
starts a line, a label's place included, so the three names differ.) And each label
asserts its address, which ld65 checks, so a change to the game that moves
any of it does not link.

Made under the directory: src/tmnt2.asm (the 32 banks, each in its own
segment), src/ram.inc (the listing's variables and the registers),
src/header.asm (the ROM's iNES header), and chr.bin (its CHR ROM).
"""

import os
import re
import sys

BANKS = 32
BANK_SIZE = 0x2000
HEADER = 16
FREE = 32               # the shortest run of $FF that is room for code

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
MNEMONICS = {m for m, _ in OPCODES.values()}
# Instructions that write their operand: an address in ROM space there is
# one of the mapper's registers.
WRITES = {"STA", "STX", "STY", "INC", "DEC", "ASL", "LSR", "ROL", "ROR"}

# The listing's names for the registers. The PPU's and the APU's are in its
# variables file; the mapper's it uses without defining.
MMC3 = {
    "MMC3_BANK_CFG": 0x8000, "MMC3_BANK_DATA": 0x8001,
    "MMC3_MIRRORING": 0xA000, "MMC3_PRG_RAM": 0xA001,
    "MMC3_IRQ_LATCH": 0xC000, "MMC3_IRQ_RELOAD": 0xC001,
    "MMC3_IRQ_DISABLE": 0xE000, "MMC3_IRQ_ENABLE": 0xE001,
}
# a:, z: and f: are address-size prefixes to ca65.
RESERVED = MNEMONICS | {"A", "X", "Y", "S", "Z", "F"}

ADDRESS = re.compile(r"([0-9A-F]{2}):([0-9A-F]{4}), 0x[0-9A-F]{6}")


def legal(name):
    """The listing's name as an identifier ca65 takes."""
    name = re.sub(r"\[\d+\]", "", name)
    name = name.replace("?", "").replace("'", "").replace("*", "X")
    name = re.sub(r"[^A-Za-z0-9_]", "_", name)
    name = re.sub(r"__+", "_", name).strip("_") or "UNNAMED"
    if name[0].isdigit():
        name = "_" + name
    if name.upper() in RESERVED:
        name += "_"
    return name


def base(bank):
    if bank == BANKS - 1:
        return 0xE000
    if bank == BANKS - 2:
        return 0xC000
    return 0x8000 if bank % 2 == 0 else 0xA000


def visible(bank):
    """The banks mapped while code in this one runs."""
    if bank >= BANKS - 2:
        return [BANKS - 2, BANKS - 1]
    pair = bank - bank % 2
    return [bank, pair + (1 - bank % 2), BANKS - 2, BANKS - 1]


class Variables:
    """The listing's RAM, and the registers, by address."""

    def __init__(self, path):
        self.equates = dict(MMC3)
        self.ram = {}          # address -> (name, offset)
        names = set()
        address = 0
        with open(path) as handle:
            for line in handle:
                code = line.split(";")[0].strip()
                if not code:
                    continue
                if code.startswith(".rsset"):
                    address = int(code.split()[1], 16)
                    continue
                match = re.match(r"(.+?):\s+\.(rs|equ)\s+\$?(\w+)$", code)
                if not match:
                    continue
                label, kind, value = match.groups()
                if label.startswith("R_**"):
                    name = None
                else:
                    name = legal(label)
                if kind == "equ":
                    self.equates[name] = int(value, 16)
                    continue
                size = int(value)
                if name is None or name in names:
                    name = "RAM_%04X" % address
                names.add(name)
                for offset in range(size):
                    self.ram.setdefault(address + offset, (name, offset))
                address += size
        self.ram_names = names
        self.by_value = {}
        for name, value in self.equates.items():
            self.by_value.setdefault(value, name)

    def name(self, value):
        if value in self.ram:
            name, offset = self.ram[value]
            return name if offset == 0 else "%s+%d" % (name, offset)
        return None


class Bank:
    """One bank of the listing, as what is where."""

    def __init__(self, number, path, rom):
        self.number = number
        self.base = base(number)
        self.rom = rom[number * BANK_SIZE:(number + 1) * BANK_SIZE]
        self.labels = {}       # offset -> [listing's names]
        self.comments = {}     # offset -> [a label's comments]
        self.remarks = {}      # offset -> an instruction's comment
        self.code = {}         # offset -> (mnemonic, mode, size)
        self.pointers = {}     # offset -> ("<" or ">", listing's name)
        self.mismatches = 0
        self._read(path)

    def _read(self, path):
        offset = 0
        # After a line that is not the ROM's, where the lines that follow
        # are is not known until a label says.
        lost = False
        with open(path) as handle:
            lines = handle.read().splitlines()
        for line in lines:
            code, _, comment = line.partition(";")
            code = code.rstrip()
            comment = comment.strip()
            if not code.strip():
                continue
            if not code[0].isspace():
                if not code.endswith(":"):
                    continue
                match = ADDRESS.search(comment)
                if match and int(match.group(1), 16) == self.number:
                    offset = int(match.group(2), 16)
                    lost = False
                    self._forget_from(offset)
                elif lost:
                    continue
                self.labels.setdefault(offset, []).append(code[:-1])
                note = ADDRESS.sub("", comment).strip(" ,")
                note = re.sub(r"^\[\d+\],?\s*", "", note)
                if note:
                    self.comments.setdefault(offset, []).append(note)
                continue
            if lost or offset >= BANK_SIZE:
                continue
            words = code.split()
            if comment:
                self.remarks[offset] = comment
            if words[0] == ".db":
                offset += 1
                continue
            pointer = re.match(r"(LOW|HIGH)\((.+)\)$", words[0])
            if pointer:
                kind = "<" if pointer.group(1) == "LOW" else ">"
                self.pointers[offset] = (kind, pointer.group(2))
                offset += 1
                continue
            opcode = OPCODES.get(self.rom[offset])
            if opcode is None or opcode[0] != words[0]:
                # Not the ROM's instruction: data, until the listing's
                # next address says where its lines are.
                self.mismatches += 1
                lost = True
                continue
            mnemonic, mode = opcode
            size = MODES[mode]
            if offset + size > BANK_SIZE:
                offset += 1
                continue
            self.code[offset] = (mnemonic, mode, size)
            offset += size

    def _forget_from(self, offset):
        """Instructions that a label at this offset says were misread."""
        for at in [at for at in self.code if at + self.code[at][2] > offset]:
            del self.code[at]
        for at in [at for at in self.pointers if at >= offset]:
            del self.pointers[at]

    def operand(self, offset):
        mnemonic, mode, size = self.code[offset]
        if size == 1:
            return None
        if size == 2:
            value = self.rom[offset + 1]
            if mode == "rel":
                value = (self.base + offset + 2 + (value ^ 0x80) - 0x80) & 0xFFFF
            return value
        return self.rom[offset + 1] | self.rom[offset + 2] << 8


class Converter:

    def __init__(self, listing, rom):
        self.rom = rom
        prg = rom[HEADER:]
        self.vars = Variables(os.path.join(listing, "TMNT2.variables.asm"))
        self.banks = [Bank(n, os.path.join(listing, "TMNT2.bank%02d.asm" % n), prg)
                      for n in range(BANKS)]
        self._name_labels()

    def _name_labels(self):
        """One identifier for each labelled address, unique in the ROM."""
        counts = {}
        for bank in self.banks:
            for offset, names in bank.labels.items():
                for name in names:
                    counts[legal(name)] = counts.get(legal(name), 0) + 1
        taken = set(self.vars.equates) | self.vars.ram_names
        self.names = {}        # (bank, offset) -> identifier
        self.by_listing = {}   # listing's name -> [(bank, offset)]
        for bank in self.banks:
            for offset in sorted(bank.labels):
                for name in bank.labels[offset]:
                    self.by_listing.setdefault(name, []).append((bank.number, offset))
                if not self._boundary(bank, offset):
                    continue
                name = legal(bank.labels[offset][0])
                if counts[name] > 1 or name in taken:
                    name = "%s_%02X_%04X" % (name, bank.number, offset)
                taken.add(name)
                self.names[(bank.number, offset)] = name

    def _boundary(self, bank, offset):
        """Whether a line of the output starts at this offset."""
        for back in (1, 2):
            if offset - back in bank.code and bank.code[offset - back][2] > back:
                return False
        return offset < BANK_SIZE

    def target(self, bank, value):
        """A name for an address in ROM space, as code in this bank sees it."""
        for number in visible(bank.number):
            other = self.banks[number]
            offset = value - other.base
            if 0 <= offset < BANK_SIZE and self._boundary(other, offset):
                key = (number, offset)
                if key not in self.names:
                    self.names[key] = "L_%02X_%04X_" % key
                return self.names[key]
        return None

    def operand_text(self, bank, offset):
        mnemonic, mode, size = bank.code[offset]
        value = bank.operand(offset)
        if mode == "imp":
            return ""
        if mode == "acc":
            return " a"
        if mode == "imm":
            return " #$%02X" % value
        if mode == "rel":
            # Only to a name in this bank: ca65 cannot reach another
            # segment, or an address with none, in a branch.
            offset = value - bank.base
            if 0 <= offset < BANK_SIZE and self._boundary(bank, offset):
                return " " + self.target(bank, value)
            return None
        name = None
        if value >= 0x8000 and mnemonic in WRITES:
            name = self.vars.by_value.get(value)
        elif value >= 0x8000:
            name = self.target(bank, value)
        elif value in self.vars.by_value and value >= 0x2000:
            name = self.vars.by_value[value]
        else:
            name = self.vars.name(value)
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

    def pointer_text(self, bank, offset):
        """A byte of an address the listing names, if the ROM agrees."""
        kind, name = bank.pointers[offset]
        byte = bank.rom[offset]
        candidates = sorted(self.by_listing.get(name, []),
                            key=lambda c: c[0] not in visible(bank.number))
        for number, at in candidates:
            other = self.banks[number]
            value = other.base + at
            if (value & 0xFF if kind == "<" else value >> 8) != byte:
                continue
            target = self.target(other, value)
            if target:
                return "%s%s" % (kind, target)
        return None

    def free_runs(self, bank):
        """{offset: length} of the runs of $FF that nothing is listed in:
        no instruction, no pointer, no label or comment after the first
        byte."""
        runs = {}
        start = None
        for offset in range(BANK_SIZE + 1):
            empty = (offset < BANK_SIZE and bank.rom[offset] == 0xFF
                     and offset not in bank.code and offset not in bank.pointers
                     and offset not in bank.remarks
                     and not any(at < offset < at + bank.code[at][2]
                                 for at in range(max(0, offset - 2), offset) if at in bank.code))
            inside = start is not None and (
                (bank.number, offset) in self.names or offset in bank.comments)
            if start is not None and (not empty or inside):
                if offset - start >= FREE:
                    runs[start] = offset - start
                start = None
            if empty and start is None:
                start = offset
        return runs

    def bank_lines(self, bank, texts, pointers):
        lines = ['.segment "BANK%02d"' % bank.number, ""]
        offset = 0
        data = []

        def flush():
            for start in range(0, len(data), 16):
                lines.append("    .byte " + ",".join("$%02X" % b for b in data[start:start + 16]))
            data.clear()

        free = self.free_runs(bank)
        while offset < BANK_SIZE:
            name = self.names.get((bank.number, offset))
            notes = bank.comments.get(offset, [])
            if name or notes:
                flush()
            if name:
                lines.append("%s: ; %02X:%04X" % (name, bank.number, offset))
                lines.append("    .assert * = $%04X, error" % (bank.base + offset))
            for note in notes:
                lines.append("    ; " + note)
            if offset in free:
                flush()
                length = free[offset]
                label = "FREE_%02X_%04X" % (bank.number, offset)
                lines += ["%s: ; %d bytes the game does not use" % (label, length),
                          "    .assert * = $%04X, error" % (bank.base + offset),
                          ".ifdef HAVE_%s" % label,
                          "    FILL_%s" % label,
                          ".endif",
                          "    .res %d - (* - %s), $FF" % (length, label)]
                offset += length
                continue
            if offset in bank.code:
                flush()
                mnemonic, mode, size = bank.code[offset]
                if texts[offset] is None:
                    target = bank.base + offset + 2 + (bank.rom[offset + 1] ^ 0x80) - 0x80
                    lines.append("    .byte $%02X,$%02X ; %s $%04X" % (
                        bank.rom[offset], bank.rom[offset + 1], mnemonic.lower(), target & 0xFFFF))
                else:
                    line = "    %s%s" % (mnemonic.lower(), texts[offset])
                    if offset in bank.remarks:
                        line = "%-31s ; %s" % (line, bank.remarks[offset])
                    lines.append(line)
                offset += size
                continue
            if pointers.get(offset) or offset in bank.remarks:
                flush()
                line = "    .byte " + (pointers.get(offset) or "$%02X" % bank.rom[offset])
                if offset in bank.remarks:
                    line = "%-31s ; %s" % (line, bank.remarks[offset])
                lines.append(line)
            else:
                data.append(bank.rom[offset])
                if len(data) == 16:
                    flush()
            offset += 1
        flush()
        return lines

    def write(self, root):
        src = os.path.join(root, "src")
        os.makedirs(src, exist_ok=True)
        # Every operand first: naming one may name an address in any bank.
        texts = [{at: self.operand_text(bank, at) for at in bank.code}
                 for bank in self.banks]
        pointers = [{at: self.pointer_text(bank, at) for at in bank.pointers}
                    for bank in self.banks]
        banks = [self.bank_lines(bank, texts[bank.number], pointers[bank.number])
                 for bank in self.banks]
        with open(os.path.join(src, "tmnt2.asm"), "w") as out:
            out.write("; Made by tools/convert.py from Aaron Bottegal's TMNT2 disassembly\n")
            out.write("; and the ROM. The bytes are the ROM's.\n\n")
            out.write('.include "ram.inc"\n\n')
            for lines in banks:
                out.write("\n".join(lines) + "\n\n")
        with open(os.path.join(src, "ram.inc"), "w") as out:
            for name, value in sorted(self.vars.equates.items(), key=lambda e: e[1]):
                out.write("%s = $%04X\n" % (name, value))
            seen = set()
            for address in sorted(self.vars.ram):
                name, offset = self.vars.ram[address]
                if offset == 0 and name not in seen:
                    seen.add(name)
                    out.write("%s = $%04X\n" % (name, address))
        header = self.rom[:HEADER]
        with open(os.path.join(src, "header.asm"), "w") as out:
            out.write('.segment "HEADER"\n    .byte ' +
                      ",".join("$%02X" % b for b in header) + "\n")
        prg = header[4] * 0x4000
        with open(os.path.join(root, "chr.bin"), "wb") as out:
            out.write(self.rom[HEADER + prg:])


def main(listing, rom_path, root):
    with open(rom_path, "rb") as handle:
        rom = handle.read()
    converter = Converter(listing, rom)
    converter.write(root)
    for bank in converter.banks:
        if bank.mismatches:
            print("bank %02d: %d lines of the listing are not the ROM's instructions, and taken for data"
                  % (bank.number, bank.mismatches))


if __name__ == "__main__":
    main(*sys.argv[1:])
