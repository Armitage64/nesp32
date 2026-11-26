#!/usr/bin/env python3
"""Make ca65 source of Tecmo Super Bowl from the ROM and tools/game.map.

    convert.py BASEROM DIRECTORY

The game's disassembly (third_party/Tecmo_Super_Bowl_NES_Disassembly) is
asm6f source, which ca65 cannot take. tools/import.py read it once, through
asm6f's listing, into tools/game.map: where each 8 KB bank sits, which
bytes are instructions, every label, the value of every other name, each
instruction's operand as the disassembly writes it, and the comments. No
bytes of the game are in the map: every byte here comes from the ROM.

Each instruction is decoded from the ROM, with its addressing mode as it
is there. Its operand is the disassembly's expression where that comes to
the same value, and a number where it does not (a macro's parameter, or
asm6f's own arithmetic). A branch or jump to a label in its own bank names
the label. Data is bytes, broken into lines where the disassembly has a
label or a comment.

asm6f's local labels (@name) belong to the stretch between two other
labels, as ca65's cheap local labels do, but asm6f counts labels that are
not written here (the disassembly's _F{ markers for folding), so each local
is checked: one that is used outside the stretch ca65 gives it, or that
shares its name with another in that stretch, gets a name of its own.

As in tools/convert.py of River City Ransom: each label asserts its
address, which ld65 checks, so a change that moves any of the game does
not link; and each run of $FF or $00 that is not code, FREE bytes or more,
is a label FREE_b_oooo, which an assembly that defines HAVE_FREE_b_oooo
and a macro FILL_FREE_b_oooo fills.

Made under the directory: src/tsb.asm (the 32 banks of 8 KB, each in its
own segment, BANK0 to BANK31), src/ram.inc (the names that are not
labels), src/header.asm (the iNES header) and chr.bin (the CHR ROM).
"""

import bisect
import os
import re
import sys

HEADER = 16
BANKS = 32
BANK_SIZE = 0x2000
FREE = 32
VECTORS = 0xFFFA

HERE = os.path.dirname(os.path.abspath(__file__))
MAP = os.path.join(HERE, "game.map")

MODES = {"imp": 1, "acc": 1, "imm": 2, "zp": 2, "zpx": 2, "zpy": 2, "izx": 2,
         "izy": 2, "rel": 2, "abs": 3, "abx": 3, "aby": 3, "ind": 3}
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

# Names ca65 keeps for itself, which no symbol may have.
RESERVED = {m for m, _ in OPCODES.values()} | {"A", "X", "Y", "S", "Z"}


def ca65_name(name, taken):
    """A name ca65 takes, as near the disassembly's as can be."""
    local = name.startswith("@")
    core = re.sub(r"[^A-Za-z0-9_]", "_", name.lstrip("@"))
    if not core or core[0].isdigit():
        core = "_" + core
    if core.upper() in RESERVED:
        core += "_"
    candidate = core
    number = 2
    while candidate in taken:
        candidate = "%s_%d" % (core, number)
        number += 1
    return ("@" if local else "") + candidate


# --- expressions --------------------------------------------------------------

TOKEN = re.compile(r"\s*(\$[0-9A-Fa-f]+|%[01]+|\d+|@?[A-Za-z_][\w\[\]{}.']*|<<|>>|==|!=|"
                   r"<=|>=|&&|\|\||[-+*/&|^~()<>!])")


class Unknown(Exception):
    pass


def tokenize(text):
    tokens = []
    at = 0
    text = text.rstrip()
    while at < len(text):
        match = TOKEN.match(text, at)
        if not match:
            raise Unknown(text)
        tokens.append(match.group(1))
        at = match.end()
    return tokens


class Expression:
    """asm6f's expression, as far as the disassembly's operands use it:
    its value, given a function from names to values, and the same in
    ca65's words, given a function from names to ca65's names."""

    BINARY = [("||",), ("&&",), ("|",), ("^",), ("&",), ("==", "!="),
              ("<", ">", "<=", ">="), ("<<", ">>"), ("+", "-"), ("*", "/")]

    def __init__(self, text):
        self.tokens = tokenize(text)
        self.at = 0
        self.tree = self.parse(0)
        if self.at != len(self.tokens):
            raise Unknown(text)

    def peek(self):
        return self.tokens[self.at] if self.at < len(self.tokens) else None

    def take(self):
        token = self.peek()
        self.at += 1
        return token

    def parse(self, level):
        if level == len(self.BINARY):
            return self.unary()
        left = self.parse(level + 1)
        while self.peek() in self.BINARY[level]:
            op = self.take()
            left = (op, left, self.parse(level + 1))
        return left

    def unary(self):
        token = self.take()
        if token is None:
            raise Unknown("end")
        if token in ("<", ">", "-", "~", "!"):
            return ("u" + token, self.unary())
        if token == "(":
            inner = self.parse(0)
            if self.take() != ")":
                raise Unknown("(")
            return ("()", inner)
        if token.startswith("$"):
            return ("n", int(token[1:], 16), token)
        if token.startswith("%"):
            return ("n", int(token[1:], 2), token)
        if token[0].isdigit():
            return ("n", int(token), token)
        if token[0] in "@_" or token[0].isalpha():
            return ("s", token)
        raise Unknown(token)

    def names(self, tree=None):
        tree = self.tree if tree is None else tree
        if tree[0] == "s":
            return [tree[1]]
        if tree[0] == "n":
            return []
        return [name for part in tree[1:] for name in self.names(part)]

    def value(self, lookup, tree=None):
        tree = self.tree if tree is None else tree
        kind = tree[0]
        if kind == "n":
            return tree[1]
        if kind == "s":
            return lookup(tree[1])
        if kind == "()":
            return self.value(lookup, tree[1])
        if kind[0] == "u":
            inner = self.value(lookup, tree[1])
            return {"u<": inner & 0xFF, "u>": (inner >> 8) & 0xFF, "u-": -inner,
                    "u~": ~inner, "u!": int(not inner)}[kind]
        left, right = self.value(lookup, tree[1]), self.value(lookup, tree[2])
        if kind == "/" and right == 0:
            raise Unknown("/0")
        return {"+": lambda: left + right, "-": lambda: left - right,
                "*": lambda: left * right, "/": lambda: left // right,
                "&": lambda: left & right, "|": lambda: left | right,
                "^": lambda: left ^ right, "<<": lambda: left << right,
                ">>": lambda: left >> right, "==": lambda: int(left == right),
                "!=": lambda: int(left != right), "<": lambda: int(left < right),
                ">": lambda: int(left > right), "<=": lambda: int(left <= right),
                ">=": lambda: int(left >= right), "&&": lambda: int(bool(left and right)),
                "||": lambda: int(bool(left or right))}[kind]()

    def text(self, rename, tree=None):
        tree = self.tree if tree is None else tree
        kind = tree[0]
        if kind == "n":
            return tree[2]
        if kind == "s":
            return rename(tree[1])
        if kind == "()":
            return "(" + self.text(rename, tree[1]) + ")"
        if kind[0] == "u":
            return kind[1] + self.text(rename, tree[1])
        return "%s %s %s" % (self.text(rename, tree[1]), kind, self.text(rename, tree[2]))


# --- the map --------------------------------------------------------------------

class Map:
    def __init__(self, path=MAP):
        self.bases = {}
        self.symbols = {}            # name: value
        self.code_runs = []          # (bank, offset, length)
        self.labels = {}             # (bank, offset): [name]
        self.notes = {}              # (bank, offset): [text]
        self.operands = {}           # (bank, offset): expression text
        self.comments = {}           # (bank, offset): text, at the end of the line
        with open(path) as handle:
            for line in handle:
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    continue
                kind, rest = line.split(" ", 1)
                if kind == "bank":
                    bank, base = rest.split()
                    self.bases[int(bank)] = int(base, 16)
                    continue
                if kind == "sym":
                    name, value = rest.split()
                    self.symbols[name] = int(value, 16)
                    continue
                where, _, text = rest.partition(" ")
                bank, address = where.split(":")
                bank = int(bank)
                key = (bank, int(address, 16) - self.bases[bank])
                if kind == "c":
                    self.code_runs.append((bank, key[1], int(text, 16)))
                elif kind == "l":
                    self.labels.setdefault(key, []).append(text)
                elif kind == "n":
                    self.notes.setdefault(key, []).append(text)
                elif kind in ("i", "d"):
                    expression, _, comment = text.partition(" ; ")
                    if text.startswith("; "):
                        expression, comment = "", text[2:]
                    if expression.strip():
                        self.operands[key] = expression.strip()
                    if comment.strip():
                        self.comments[key] = comment.strip()


# --- the converter --------------------------------------------------------------

class Converter:
    def __init__(self, rom, path=MAP):
        self.rom = rom
        self.prg = rom[HEADER:HEADER + BANKS * BANK_SIZE]
        self.map = Map(path)
        self.bases = self.map.bases
        self.code = {}               # (bank, offset): (mnemonic, mode, size, value)
        self.covered = set()
        for bank, offset, length in self.map.code_runs:
            end = offset + length
            while offset < end:
                instruction = self.decode(bank, offset)
                if instruction is None or offset + instruction[2] > end:
                    raise SystemExit("no instruction at %d:%04X" % (bank, self.bases[bank] + offset))
                self.code[(bank, offset)] = instruction
                self.covered.update((bank, offset + at) for at in range(instruction[2]))
                offset += instruction[2]
        self.name_labels()

    def decode(self, bank, offset):
        data = self.prg[bank * BANK_SIZE:(bank + 1) * BANK_SIZE]
        opcode = OPCODES.get(data[offset])
        if opcode is None:
            return None
        mnemonic, mode = opcode
        size = MODES[mode]
        if size == 1:
            value = None
        elif size == 2:
            value = data[offset + 1]
            if mode == "rel":
                value = (self.bases[bank] + offset + 2 + (value ^ 0x80) - 0x80) & 0xFFFF
        else:
            value = data[offset + 1] | data[offset + 2] << 8
        return mnemonic, mode, size, value

    def name_labels(self):
        """ca65's names for the labels, and the stretch each local is in."""
        taken = set()
        self.symbol_names = {}
        for name in sorted(self.map.symbols):
            self.symbol_names[name] = ca65_name(name, taken)
            taken.add(self.symbol_names[name])
        self.label_names = {}        # (bank, offset): [ca65 name]
        self.globals = {}            # disassembly's name: (bank, offset)
        self.locals = {}             # (bank, name): [(offset, ca65 name, stretch)]
        self.aliases = {}            # (bank, offset): the name of a label of no stretch
        self.global_names = {}       # disassembly's name: ca65's
        self.stretch_starts = [[-1] for _ in range(BANKS)]
        self.stretch_numbers = [[0] for _ in range(BANKS)]
        self.global_at = [[(0, "BANK%d_START" % bank)] for bank in range(BANKS)]
        for bank in range(BANKS):
            stretch = 0
            in_stretch = set()
            taken.add("BANK%d_START" % bank)
            for key in sorted(k for k in self.map.labels if k[0] == bank):
                for name in self.map.labels[key]:
                    if name.startswith("@"):
                        new = ca65_name(name, in_stretch)
                        in_stretch.add(new.lstrip("@"))
                        self.locals.setdefault((bank, name), []).append((key[1], new, stretch))
                    else:
                        new = ca65_name(name, taken)
                        taken.add(new)
                        self.globals[name] = key
                        self.global_names[name] = new
                        stretch += 1
                        in_stretch = set()
                        self.stretch_starts[bank].append(key[1])
                        self.global_at[bank].append((key[1], new))
                        self.stretch_numbers[bank].append(stretch)
                    self.label_names.setdefault(key, []).append((new, stretch))
        self.taken = taken

    def stretch_at(self, bank, offset):
        """ca65's stretch for cheap locals at an offset of a bank."""
        starts = self.stretch_starts[bank]
        return \
            self.stretch_numbers[bank][bisect.bisect_right(starts, offset) - 1]

    def alias(self, bank, offset):
        """A name, of no stretch, for an address of a bank."""
        key = (bank, offset)
        if key not in self.aliases:
            self.aliases[key] = ca65_name("L%d_%04X" % (bank, self.bases[bank] + offset), self.taken)
            self.taken.add(self.aliases[key])
        return self.aliases[key]

    def target(self, bank, value):
        """A name for an address the code at bank refers to, if it is in
        this bank or the fixed one, at a line's start."""
        for number in (bank, 30, 31):
            base = self.bases[number]
            if base <= value < base + BANK_SIZE and (number == bank or number >= 30):
                offset = value - base
                if not self.boundary(number, offset):
                    return None
                for name, _ in self.label_names.get((number, offset), []):
                    if not name.startswith("@"):
                        return name
                return self.alias(number, offset)
        return None

    def boundary(self, bank, offset):
        for back in (1, 2):
            at = (bank, offset - back)
            if at in self.code and self.code[at][2] > back:
                return False
        return 0 <= offset < BANK_SIZE

    def operand_expression(self, bank, offset, mode, value):
        """The disassembly's operand, in ca65's words, if it comes to the
        value; None if not."""
        text = self.map.operands.get((bank, offset))
        if text is None:
            return None
        try:
            expression = Expression(text)
        except Unknown:
            return None
        here = self.stretch_at(bank, offset)
        renames = {}

        def lookup(name):
            if name.startswith("@"):
                options = self.locals.get((bank, name), [])
                raise_unknown = True
                for local_offset, new, stretch in options:
                    candidate = self.bases[bank] + local_offset
                    renames.setdefault(name, []).append((candidate, local_offset, new, stretch))
                    raise_unknown = False
                if raise_unknown:
                    raise Unknown(name)
                return None     # chosen below
            if name in self.globals:
                number, label_offset = self.globals[name]
                renames[name] = [(self.bases[number] + label_offset, label_offset, None, None)]
                return self.bases[number] + label_offset
            if name in self.map.symbols:
                return self.map.symbols[name]
            raise Unknown(name)

        locals_used = [n for n in expression.names() if n.startswith("@")]
        try:
            for name in expression.names():
                lookup(name)
        except Unknown:
            return None
        # Try each definition of each local the expression names.
        choices = [renames[name] for name in dict.fromkeys(locals_used)]
        names = list(dict.fromkeys(locals_used))

        def search(chosen):
            if len(chosen) < len(choices):
                for option in choices[len(chosen)]:
                    found = search(chosen + [option])
                    if found:
                        return found
                return None
            picked = dict(zip(names, chosen))

            def look(name):
                if name.startswith("@"):
                    return picked[name][0]
                return lookup(name)
            try:
                result = expression.value(look)
            except Unknown:
                return None
            if mode == "imm":
                ok = 0 <= result <= 0xFF
                ok = ok and result == value
            else:
                ok = result == value
            return picked if ok else None

        picked = search([])
        if picked is None:
            return None

        def rename(name):
            if name.startswith("@"):
                address, local_offset, new, stretch = picked[name]
                if stretch == here:
                    return new
                return self.alias(bank, local_offset)
            if name in self.global_names:
                return self.global_names[name]
            return self.symbol_names[name]
        return expression.text(rename)

    def operand_text(self, bank, offset):
        mnemonic, mode, size, value = self.code[(bank, offset)]
        if mode == "imp":
            return ""
        if mode == "acc":
            return " a"
        if mode == "rel":
            name = None
            base = self.bases[bank]
            if base <= value < base + BANK_SIZE and self.boundary(bank, value - base):
                local = self.local_at(bank, value - base, offset)
                name = local or self.target(bank, value)
            if name is None:
                return None
            return " " + name
        text = self.operand_expression(bank, offset, mode, value)
        if text is None and mnemonic in ("JMP", "JSR") and mode == "abs":
            text = self.target(bank, value)
        if mode == "imm":
            return " #" + (text or "$%02X" % value)
        if text is None:
            text = "$%02X" % value if size == 2 else "$%04X" % value
        if text.startswith("(") and mode not in ("izx", "izy", "ind"):
            text = "0 + " + text        # a ( first would be taken for indirect
        # ca65 picks zero page or absolute by the value, where it knows it
        # here: the names in ram.inc it does; labels may come later.
        known = set(self.symbol_names.values())
        names = re.findall(r"@?[A-Za-z_]\w*", text)
        if size == 2:
            prefix = "z:" if any(name not in known for name in names) else ""
        else:
            prefix = "a:" if value < 0x100 and mode != "ind" else ""
        return " " + {
            "zp": "{p}{t}", "zpx": "{p}{t},x", "zpy": "{p}{t},y",
            "abs": "{p}{t}", "abx": "{p}{t},x", "aby": "{p}{t},y",
            "izx": "({t},x)", "izy": "({t}),y", "ind": "({t})",
        }[mode].format(p=prefix, t=text)

    def local_at(self, bank, target, offset):
        """A cheap local's name at target, if ca65 can see it from offset."""
        here = self.stretch_at(bank, offset)
        for name, stretch in self.label_names.get((bank, target), []):
            if name.startswith("@") and stretch == here:
                return name
        return None

    def free_runs(self, bank):
        data = self.prg[bank * BANK_SIZE:(bank + 1) * BANK_SIZE]
        end = VECTORS - self.bases[bank] if bank == 31 else BANK_SIZE
        runs = {}
        start = None
        for offset in range(end + 1):
            empty = (offset < end and data[offset] in (0x00, 0xFF)
                     and (bank, offset) not in self.covered)
            if start is not None and (not empty or data[offset] != data[start] or
                                      (bank, offset) in self.map.labels or
                                      (bank, offset) in self.map.notes or
                                      (bank, offset) in self.map.comments):
                if offset - start >= FREE:
                    runs[start] = (offset - start, data[start])
                start = None
            if empty and start is None:
                start = offset
        return runs

    def bank_lines(self, bank, texts):
        base = self.bases[bank]
        lines = ['.segment "BANK%d"' % bank, ""]
        data = self.prg[bank * BANK_SIZE:(bank + 1) * BANK_SIZE]
        pending = []

        def flush():
            for start in range(0, len(pending), 16):
                lines.append("    .byte " + ",".join("$%02X" % b for b in pending[start:start + 16]))
            pending.clear()

        free = self.free_runs(bank)
        end = VECTORS - base if bank == 31 else BANK_SIZE
        offset = 0
        while offset < end:
            key = (bank, offset)
            names = self.label_names.get(key, [])
            notes = self.map.notes.get(key, [])
            alias = self.aliases.get(key)
            comment = self.map.comments.get(key)
            if names or notes or alias or comment or key in self.code or offset in free:
                flush()
            if notes and (names or alias):
                lines.append("")
            for note in notes:
                lines.append("; " + note)
            for name, _ in names:
                lines.append("%s:" % name)
            if offset == 0:
                lines.append("BANK%d_START:" % bank)
            if names or offset == 0:
                lines.append("    .assert * = $%04X, error" % (base + offset))
            if offset in free:
                length, fill = free[offset]
                label = "FREE_%d_%04X" % (bank, base + offset)
                lines += ["%s = * ; %d bytes of $%02X that are not code" % (label, length, fill),
                          "    .assert * = $%04X, error" % (base + offset),
                          ".ifdef HAVE_%s" % label,
                          "    FILL_%s" % label,
                          ".endif",
                          "    .res %d - (* - %s), $%02X" % (length, label, fill)]
                offset += length
                continue
            if key in self.code:
                mnemonic, mode, size, value = self.code[key]
                text = texts.get(offset)
                if text is None:
                    line = "    .byte " + ",".join("$%02X" % b for b in data[offset:offset + size])
                    line += " ; %s $%04X" % (mnemonic.lower(), value)
                else:
                    line = "    %s%s" % (mnemonic.lower(), text)
                if comment:
                    line = "%-40s ; %s" % (line, comment)
                lines.append(line)
                offset += size
                continue
            if comment:
                # The data's line: its bytes up to the next line's start.
                stop = offset + 1
                while stop < end and not self.starts(bank, stop, free):
                    stop += 1
                chunk = data[offset:stop]
                for start in range(0, len(chunk), 16):
                    line = "    .byte " + ",".join("$%02X" % b for b in chunk[start:start + 16])
                    if start == 0:
                        line = "%-40s ; %s" % (line, comment)
                    lines.append(line)
                offset = stop
                continue
            pending.append(data[offset])
            if len(pending) == 16:
                flush()
            offset += 1
        flush()
        if bank == 31:
            words = [data[VECTORS - base + 2 * at] | data[VECTORS - base + 2 * at + 1] << 8
                     for at in range(3)]
            names = [self.target(31, word) or "$%04X" % word for word in words]
            lines += ["", "VECTORS:", "    .assert * = $%04X, error" % VECTORS,
                      "    .addr " + ", ".join(names)]
        return lines

    def starts(self, bank, offset, free):
        key = (bank, offset)
        return (key in self.label_names or key in self.map.notes or key in self.aliases
                or key in self.map.comments or key in self.code or offset in free)

    def write(self, root):
        src = os.path.join(root, "src")
        os.makedirs(src, exist_ok=True)
        # Every operand first, and the vectors: naming one may give an
        # address a name.
        for at in range(3):
            word = VECTORS - self.bases[31] + 2 * at + 31 * BANK_SIZE
            self.target(31, self.prg[word] | self.prg[word + 1] << 8)
        texts = []
        for bank in range(BANKS):
            texts.append({offset: self.operand_text(bank, offset)
                          for (number, offset) in self.code if number == bank})
        banks = [self.bank_lines(bank, texts[bank]) for bank in range(BANKS)]
        with open(os.path.join(src, "tsb.asm"), "w") as out:
            out.write("; Made by tools/convert.py from the ROM and tools/game.map, which\n")
            out.write("; tools/import.py made from the disassembly. The bytes are the ROM's.\n\n")
            out.write('.include "ram.inc"\n\n')
            for lines in banks:
                out.write("\n".join(lines) + "\n\n")
            # Names for addresses the disassembly has no label for, or whose
            # local label ca65 cannot see from where it is used: here at the
            # end, as a label in the middle of a stretch would end it.
            out.write("; Names for addresses the code refers to.\n")
            for (bank, offset), alias in sorted(self.aliases.items()):
                starts = [at for at, _ in self.global_at[bank]]
                at, name = self.global_at[bank][bisect.bisect_right(starts, offset) - 1]
                out.write("%s = %s + $%X\n" % (alias, name, offset - at))
        with open(os.path.join(src, "ram.inc"), "w") as out:
            out.write("; The disassembly's names that are not labels, with their values.\n")
            for name in sorted(self.map.symbols, key=lambda n: (self.map.symbols[n], n)):
                out.write("%s = $%04X\n" % (self.symbol_names[name], self.map.symbols[name]))
        header = self.rom[:HEADER]
        with open(os.path.join(src, "header.asm"), "w") as out:
            out.write('.segment "HEADER"\n    .byte ' + ",".join("$%02X" % b for b in header) + "\n")
        with open(os.path.join(root, "chr.bin"), "wb") as out:
            out.write(self.rom[HEADER + BANKS * BANK_SIZE:])
        named = sum(1 for bank in range(BANKS) for t in texts[bank].values()
                    if t and re.search(r"[A-Za-z_]", t.replace(" a", "")))
        return len(self.code), named


def main(rom_path, root):
    with open(rom_path, "rb") as handle:
        rom = handle.read()
    converter = Converter(rom)
    count, named = converter.write(root)
    print("%d instructions, %d with a name in the operand; %d bytes of the PRG's %d are code"
          % (count, named, len(converter.covered), BANKS * BANK_SIZE))


if __name__ == "__main__":
    main(*sys.argv[1:])
