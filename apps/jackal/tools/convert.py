#!/usr/bin/env python3
"""RayofJay's Jackal disassembly (ASM6) as ca65 source.

    convert.py DISASSEMBLY BASEROM OUT

DISASSEMBLY is the submodule's "ASM Source" directory, BASEROM the US
release with its iNES header, OUT the directory to write:

    header.asm   the iNES header, as MAIN.asm has it
    symbols.inc  the RAM, the registers, the sounds and the macros
    bank0.asm .. bank7.asm, one for each 16 KB bank, each in a segment of
                 its own (BANK0 .. BANK7) at its address (.org)
    jackal.asm   all of them, in the order MAIN.asm gives

What the disassembly leaves out, the graphics and the free space, it
marks with .PAD: each becomes an .incbin of the same bytes of BASEROM.
The .incbin names baserom.nes: ca65 finds it with --bin-include-dir.

ASM6 and ca65 differ in a few things the source uses:

- ASM6's anonymous labels, a run of - or + standing for the nearest one
  before or after with the same run, become labels of their own name.
- A label alone on its line needs no colon in ASM6.
- In ASM6, (expression),Y is absolute indexed when the expression is not
  on the zero page, and (expression) on its own is the expression; ca65
  reads both as indirect. The brackets go where the address is not on the
  zero page.
- An equate may carry a # (Name = #$2E); the value is what is meant.
- MACRO .. ENDM, db and dw are .macro .. .endmacro, .byte and .word.

Everything else is passed through, the comments too.
"""

import os
import re
import sys

ORDER_SYMBOLS = ["Macro", "RAM_Symbols", "STD_Symbols", "Sound", "JeepAttributes", "Global"]
ORDER_BANKS = ["Bank0", "Bank1", "Bank2", "Bank3", "Bank4", "Bank5", "Bank6", "Bank7"]
INES_HEADER = 16
BANK_SIZE = 0x4000

OPCODES = set("""
ADC AND ASL BCC BCS BEQ BIT BMI BNE BPL BRK BVC BVS CLC CLD CLI CLV CMP CPX
CPY DEC DEX DEY EOR INC INX INY JMP JSR LDA LDX LDY LSR NOP ORA PHA PHP PLA
PLP ROL ROR RTI RTS SBC SEC SED SEI STA STX STY TAX TAY TSX TXA TXS TYA
""".split())
BRANCHES = {"BCC", "BCS", "BEQ", "BMI", "BNE", "BPL", "BVC", "BVS", "JMP", "JSR"}

IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
ANON = re.compile(r"^([-+]+):?")
EQUATE = re.compile(r"^\s*(" + IDENT + r")\s*=\s*(.*)$")


def read(path):
    with open(path, encoding="latin-1") as handle:
        return handle.read().replace("\r", "").split("\n")


def split_comment(line):
    """The line's code and its comment (with the ;), outside of strings."""
    quote = False
    for index, char in enumerate(line):
        if char == '"':
            quote = not quote
        elif char == ";" and not quote:
            return line[:index], line[index:]
    return line, ""


def number(text):
    text = text.strip()
    if text.startswith("$"):
        return int(text[1:], 16)
    if text.startswith("%"):
        return int(text[1:], 2)
    if text.isdigit():
        return int(text)
    return None


class Converter:
    def __init__(self, source, rom):
        self.source = source
        self.rom = rom
        self.equates = {}       # name: value, where it is a plain number
        self.anon_next = {}     # run: count of definitions so far
        self.anon_defs = []     # (run, index in the stream, name)

    # --- symbols ------------------------------------------------------------

    def symbols(self):
        out = ["; Jackal's symbols and macros, from RayofJay's disassembly",
               "; (tools/convert.py). Do not edit: build/src has the copy to patch.", ""]
        for name in ORDER_SYMBOLS:
            out.append("; ---- " + name + ".ASM")
            in_macro = False
            for line in read(os.path.join(self.source, "Code", name + ".ASM")):
                code, comment = split_comment(line)
                stripped = code.strip()
                match = re.match(r"^MACRO\s+(" + IDENT + r")\s*(.*)$", stripped)
                if match:
                    params = match.group(2).strip()
                    out.append(".macro " + match.group(1) + (" " + params if params else "") + comment)
                    in_macro = True
                    continue
                if stripped == "ENDM":
                    out.append(".endmacro" + comment)
                    in_macro = False
                    continue
                match = EQUATE.match(code)
                if match and not in_macro:
                    value = match.group(2).strip().lstrip("#").strip()
                    parsed = number(value)
                    if parsed is not None:
                        self.equates[match.group(1)] = parsed
                    out.append(match.group(1) + " = " + value + (" " + comment if comment else ""))
                    continue
                out.append(self.code_line(code, comment, None) if stripped else line)
        # ASM6 lets an equate be given again, and the last one is what the
        # code sees (all of them come before it): the others are left as
        # comments.
        last = {}
        for at, line in enumerate(out):
            match = EQUATE.match(line)
            if match and not line.startswith(";"):
                last[match.group(1)] = at
        for at, line in enumerate(out):
            match = EQUATE.match(line)
            if match and not line.startswith(";") and last[match.group(1)] != at:
                out[at] = "; (given again below) " + line
        return "\n".join(out) + "\n"

    # --- the banks ----------------------------------------------------------

    def gather(self):
        """Every bank's lines, as one stream, as ASM6 reads them."""
        stream = []
        for bank, name in enumerate(ORDER_BANKS):
            for line in read(os.path.join(self.source, "Code", name + ".ASM")):
                stream.append((bank, line))
        return stream

    def name_anonymous(self, stream):
        """A name for each anonymous label, and what each reference means."""
        defs = {}       # index in stream: name
        by_run = {}     # run: [(index, name)]
        for index, (_, line) in enumerate(stream):
            code, _ = split_comment(line)
            match = ANON.match(code)
            if match and (len(code) == len(match.group(0)) or code[len(match.group(0))] in " \t:" or match.group(0).endswith(":")):
                run = match.group(1)
                count = self.anon_next.get(run, 0)
                self.anon_next[run] = count + 1
                kind = "back" if run[0] == "-" else "fwd"
                label = "anon_%s%d_%d" % (kind, len(run), count)
                defs[index] = label
                by_run.setdefault(run, []).append((index, label))
        return defs, by_run

    @staticmethod
    def resolve(run, index, by_run):
        labels = by_run.get(run, [])
        if run[0] == "-":
            before = [label for at, label in labels if at <= index]
            if not before:
                raise SystemExit("no %s before line %d" % (run, index))
            return before[-1]
        after = [label for at, label in labels if at > index]
        if not after:
            raise SystemExit("no %s after line %d" % (run, index))
        return after[0]

    def operand(self, mnemonic, text, index, by_run):
        text = text.strip()
        if not text:
            return ""
        if mnemonic in BRANCHES and re.fullmatch(r"[-+]+", text):
            return self.resolve(text, index, by_run)
        if mnemonic == "JMP":
            return text
        match = re.fullmatch(r"\((.*)\)\s*(,\s*[XYxy])?", text)
        if match:
            inner, index_reg = match.group(1), (match.group(2) or "").replace(" ", "")
            if inner.rstrip().upper().endswith(",X"):
                return text                         # (zp,X)
            # The 6502 has (zp),Y alone: (expression),X and (expression) are
            # the expression, and (expression),Y is too off the zero page.
            if index_reg.upper() != ",Y" or not self.on_zero_page(inner):
                return inner.strip() + index_reg
        return text

    def on_zero_page(self, expression):
        value = self.evaluate(expression)
        return value is not None and value < 0x100

    def evaluate(self, expression):
        """The value of a sum of numbers and equates, or None."""
        total = 0
        for sign, term in re.findall(r"([-+]?)\s*([^-+\s]+)", expression.strip()):
            value = number(term)
            if value is None:
                value = self.equates.get(term)
            if value is None:
                return None
            total += -value if sign == "-" else value
        return total

    def code_line(self, code, comment, index, by_run=None, label_defs=None):
        stripped = code.strip()
        out_label = ""
        rest = code
        if label_defs is not None and index in label_defs:
            match = ANON.match(code)
            out_label = label_defs[index] + ":"
            rest = code[len(match.group(0)):].lstrip(":")      # ASM6 takes +:: too
        else:
            match = re.match(r"^(" + IDENT + r"):", code)
            if match:
                out_label = match.group(1) + ":"
                rest = code[len(match.group(0)):]
            else:
                match = re.match(r"^(" + IDENT + r")(\s|$)", code)
                if match and match.group(1).upper() not in OPCODES and match.group(1) not in ("db", "dw"):
                    out_label = match.group(1) + ":"
                    rest = code[len(match.group(1)):]
        body = rest.strip()
        if not body:
            line = out_label
        else:
            match = re.match(r"^(" + IDENT + r")\s*(.*)$", body)
            word = match.group(1) if match else body
            args = match.group(2) if match else ""
            if word == "db":
                args = args.replace("#", "")                    # ASM6 takes db #$13 too
                line = (out_label + "\t" if out_label else "\t") + ".byte " + args.strip()
            elif word == "dw":
                line = (out_label + "\t" if out_label else "\t") + ".word " + args.strip()
            elif word.upper() in OPCODES:
                operand = self.operand(word.upper(), args, index, by_run) if by_run is not None else args.strip()
                line = (out_label + "\t" if out_label else "\t") + word + (" " + operand if operand else "")
            else:
                line = (out_label + "\t" if out_label else "\t") + body    # a macro
        if comment:
            line = (line + " " if line.strip() else line) + comment
        return line

    def banks(self):
        stream = self.gather()
        label_defs, by_run = self.name_anonymous(stream)
        files = {bank: [] for bank in range(len(ORDER_BANKS))}
        base = {}
        for index, (bank, line) in enumerate(stream):
            code, comment = split_comment(line)
            stripped = code.strip()
            out = files[bank]
            if stripped.upper().startswith(".BASE"):
                address = number(stripped.split(None, 1)[1])
                base[bank] = address
                out.append('.segment "BANK%d"' % bank)
                out.append(".org $%04X" % address)
                continue
            if stripped.upper().startswith(".PAD"):
                address = number(stripped.split(None, 1)[1])
                offset = INES_HEADER + bank * BANK_SIZE
                out.append(
                    '\t.incbin "baserom.nes", $%X + (* - $%04X), $%04X - *%s'
                    % (offset, base[bank], address, " " + comment if comment else ""))
                out.append("\t.assert * = $%04X, error, \"bank %d: the gap ends at $%04X\"" % (address, bank, address))
                continue
            if not stripped:
                out.append(comment if comment else "")
                continue
            out.append(self.code_line(code, comment, index, by_run, label_defs))
        return files


def main():
    source, rom_path, out = sys.argv[1:4]
    with open(rom_path, "rb") as handle:
        rom = handle.read()
    converter = Converter(source, rom)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "symbols.inc"), "w") as handle:
        handle.write(converter.symbols())
    header = []
    for line in read(os.path.join(source, "MAIN.asm")):
        code, comment = split_comment(line)
        if code.strip().startswith(".INCSRC"):
            continue
        header.append(converter.code_line(code, comment, None) if code.strip() else line)
    with open(os.path.join(out, "header.asm"), "w") as handle:
        handle.write('; The iNES header, as MAIN.asm has it.\n.segment "HEADER"\n' + "\n".join(header) + "\n")
    for bank, lines in converter.banks().items():
        with open(os.path.join(out, "bank%d.asm" % bank), "w") as handle:
            handle.write("; Jackal's bank %d, from RayofJay's disassembly (tools/convert.py).\n" % bank)
            handle.write("\n".join(lines) + "\n")
    with open(os.path.join(out, "jackal.asm"), "w") as handle:
        handle.write("; Jackal, from RayofJay's disassembly (tools/convert.py): all of it\n")
        handle.write("; in one unit, as ASM6 assembles it.\n\n")
        handle.write('.include "symbols.inc"\n.include "header.asm"\n')
        for bank in range(len(ORDER_BANKS)):
            handle.write('.include "bank%d.asm"\n' % bank)


if __name__ == "__main__":
    main()
