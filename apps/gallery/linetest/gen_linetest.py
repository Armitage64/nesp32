#!/usr/bin/env python3
"""The line-palette test ROM's timed code, and its pictures' banks.

    gen_linetest.py OUT_DIR [--off-dot N] PICTURE...

Each PICTURE is BASE, for BASE.bin (the converter's picture: CHR, then the
nametable), BASE.pal (16 colours) and BASE.sched (240 pairs: the palette
entry to change before that line, or $FF for none, and its colour). Bank 0
is a test pattern made here; the pictures follow.

Writes OUT_DIR/timed.s (the code that is timed to the cycle: the sync to
the PPU, the frame loop and the line kernel, at $C000 of the fixed bank),
and OUT_DIR/bankN.bin (16 KB each).

Every frame is timed from the moment the PPU sets its vblank flag (dot 1
of line 241), which the sync finds to within a cycle. A line's palette
colour is changed in the horizontal blank before it, with rendering off:

    stx PPUMASK     rendering off (X: the next line's low address byte, whose
                    bits 3 and 4 are clear)       <- at --off-dot of line y-1
    sty PPUADDR     $3F00 + the entry (the $3F went before, in the line)
    sta PPUDATA     the colour
    lda #hi
    sta PPUADDR     the address of line y, fine Y 0 to 3 only
    stx PPUADDR
    lda #$08
    sta PPUMASK     rendering on, 72 dots after it went off

so only lines whose fine Y is 0 to 3 can have one. Rendering comes back
before dot 328, where the PPU moves to the line's second tile; the first
is hidden by PPUMASK's left column."""
import argparse
import os

DOTS = 341
VBL_LINE = 241
X0 = 24                 # the frame loop starts this many cycles after the flag is set
FRAME_A, FRAME_B = 29781, 29780     # two frames: 59561 cycles with rendering on
SYNC_PERIOD = 29780     # a frame with rendering off is 29780 2/3: the read creeps earlier
SYNC_FIRST = 29789      # from the coarse sync's read to the first fine one
OFFSETS = 25            # timing offsets the controller can choose, in cycles
CENTRE = 12
SPLIT_LINE = 119        # PPUCTRL's write for the second pattern table, before line 120
SPLIT_DOT = 300
MASK_ON = 0x08          # background, its left column hidden; no sprites
RAM_LO = 0x0300         # each line's entry ($FF: none), copied from the bank
RAM_COL = 0x0400
ZP_3F = 0x10            # holds $3F: a three-cycle load of it
ZP_PAD, ZP_PREV, ZP_NEW = 0x11, 0x12, 0x13
ZP_OFF_PTR, ZP_END_PTR = 0x14, 0x16
BANK_PAL = 0xA400
BANK_LO = 0xA500
BANK_COL = 0xA600
ORIGIN = 0xC000


def allowed(y):
    return y % 8 < 4 and y != SPLIT_LINE + 1


class Asm:
    """Code with its addresses and cycles counted. Branches' cycles come
    from the addresses of the pass before; generate() runs until they
    settle."""

    def __init__(self, labels):
        self.out = []
        self.addr = ORIGIN
        self.labels = labels        # from the pass before
        self.found = {}
        self.t = 0                  # cycles along the current path

    def label(self, name):
        self.found[name] = self.addr
        self.out.append("%s:" % name)

    def op(self, text, size, cycles, note=""):
        self.out.append("    %-24s; %3d%s" % (text, self.t, "  " + note if note else ""))
        self.addr += size
        self.t += cycles

    def comment(self, text):
        self.out.append("    ; " + text)

    def branch(self, mnemonic, target, taken):
        """A branch, its cycles for the path followed (taken or not)."""
        after = self.addr + 2
        dest = self.labels.get(target, after)
        cycles = 2
        if taken:
            cycles = 3 + ((dest & 0xFF00) != (after & 0xFF00))
        self.op("%s %s" % (mnemonic, target), 2, cycles)
        return cycles

    def taken_cost(self, at, target):
        after = at + 2
        dest = self.labels.get(target, after)
        return 3 + ((dest & 0xFF00) != (after & 0xFF00))

    def delay(self, n):
        """Exactly n cycles (n is 0 or 2 or more), X and the flags lost."""
        assert n == 0 or n >= 2, n
        while n > 1288 + 18:
            self.op("ldx #255", 2, 2)
            self.op("jsr delay_x", 3, 1286)     # 6 + 5 * 255 - 1 + 6
            n -= 1288
        if n >= 18:
            k = (n - 13) // 5
            r = n - 13 - 5 * k
            if r == 1:
                k -= 1
                r = 6
            if k >= 1:
                self.op("ldx #%d" % k, 2, 2)
                self.op("jsr delay_x", 3, 5 * k - 1 + 12)
                n = r
        if n % 2:
            self.op("bit $00", 2, 3)
            n -= 3
        while n:
            self.op("nop", 1, 2)
            n -= 2


def line_target(line, dot):
    """Cycles from the frame loop's start to that line and dot of the next
    frame's picture."""
    dots = (262 - VBL_LINE) * DOTS - 1 + line * DOTS + dot
    return round(dots / 3) - X0


def generate(labels, off_dot):
    a = Asm(labels)
    a.out.append("; Made by gen_linetest.py: timed to the cycle; do not edit.")
    for name, value in (("LT_OFFSETS", OFFSETS), ("LT_CENTRE", CENTRE), ("RAM_LO", RAM_LO),
                        ("RAM_COL", RAM_COL), ("BANK_LO", BANK_LO), ("BANK_COL", BANK_COL),
                        ("ZP_3F", ZP_3F), ("ZP_PAD", ZP_PAD), ("ZP_PREV", ZP_PREV),
                        ("ZP_NEW", ZP_NEW), ("ZP_OFF_PTR", ZP_OFF_PTR), ("ZP_END_PTR", ZP_END_PTR)):
        a.out.append("%s = $%04X" % (name, value))
    a.out.append('.segment "TIMED"')
    a.label("delay_x")              # 5X - 1 cycles; in the page's first bytes
    a.op("dex", 1, 2)
    a.op("bne delay_x", 2, 3)
    a.op("rts", 1, 6)

    # --- The sync: to within a cycle of the vblank flag's setting.
    a.out.append("")
    a.comment("Sync, rendering off. Coarse: a read after the flag is set.")
    a.label("sync")
    a.op("bit $2002", 3, 4)
    a.label("sync_coarse")
    a.op("bit $2002", 3, 4)
    a.op("bpl sync_coarse", 2, 2)
    a.t = 3                         # cycles since the coarse read
    a.delay(SYNC_FIRST - 3 - a.t)
    a.label("sync_fine")
    start = a.t
    a.op("bit $2002", 3, 4, "read at %d" % (a.t + 3))
    bpl_at = a.addr
    a.branch("bpl", "sync_found", taken=False)
    a.delay(SYNC_PERIOD - 9)
    a.op("jmp sync_fine", 3, 3)
    assert a.t - start == SYNC_PERIOD, (a.t, start)
    a.label("sync_found")
    # The read before the flag was set: call it the moment it was set.
    taken = a.taken_cost(bpl_at, "sync_found")
    a.t = 1 + taken
    a.delay(X0 - 3 - a.t)
    a.op("jmp frame_a", 3, 3)
    assert a.t == X0

    # --- The frame loop.
    def vblank():
        a.op("lda #$3F", 2, 2)
        a.op("sta $2006", 3, 4)
        a.op("lda #$00", 2, 2)
        a.op("sta $2006", 3, 4)
        for i in range(16):
            a.op("lda $%04X" % (BANK_PAL + i), 3, 4)
            a.op("sta $2007", 3, 4)
        a.op("bit $2002", 3, 4)
        a.op("lda #$00", 2, 2)
        a.op("sta $2000", 3, 4)
        a.op("sta $2005", 3, 4)
        a.op("sta $2005", 3, 4)
        a.op("lda #$%02X" % MASK_ON, 2, 2)
        a.op("sta $2001", 3, 4)
        a.op("lda #$01", 2, 2)
        a.op("sta $4016", 3, 4)
        a.op("lda #$00", 2, 2)
        a.op("sta $4016", 3, 4)
        for _ in range(8):
            a.op("lda $4016", 3, 4)
            a.op("lsr a", 1, 2)
            a.op("rol $%02X" % ZP_PAD, 2, 5)
        a.op("lda $%02X" % ZP_PREV, 2, 3)
        a.op("eor #$FF", 2, 2)
        a.op("and $%02X" % ZP_PAD, 2, 3)
        a.op("sta $%02X" % ZP_NEW, 2, 3)
        a.op("lda $%02X" % ZP_PAD, 2, 3)
        a.op("sta $%02X" % ZP_PREV, 2, 3)
        a.op("lda $%02X" % ZP_NEW, 2, 3)

    tails = {}
    for name, length, after in (("frame_a", FRAME_A, "frame_b"), ("frame_b", FRAME_B, "frame_a")):
        a.out.append("")
        a.label(name)
        a.t = 0
        vblank()
        label = name + "_go"
        a.branch("beq", label, taken=True)
        a.op("jmp action", 3, 0, "a button: out of the loop")
        a.label(label)
        a.op("jsr kernel", 3, 6)
        tails[name] = (a, length, after)
        kernel_start = a.t
        a.t += KERNEL_CYCLES.get("cycles", 0)
        a.delay(length - 3 - a.t)
        a.op("jmp " + after, 3, 3)
        assert a.t == length, (name, a.t)

    # --- The kernel: timed from the frame's start (both frames alike).
    a.out.append("")
    a.label("kernel")
    a.t = kernel_start
    entry = a.t
    a.op("jmp ($%02X)" % ZP_OFF_PTR, 3, 5)
    a.t += 2 + CENTRE + 3       # the offset's stub at the centre
    a.label("kernel_body")
    events = []
    for y in range(1, 240):
        if allowed(y):
            events.append((line_target(y - 1, off_dot), "line", y))
    events.append((line_target(SPLIT_LINE, SPLIT_DOT), "split", 0))
    events.sort()
    for target, kind, y in events:
        if kind == "split":
            a.delay(target - 2 - 3 - a.t)
            a.op("lda #$10", 2, 2)
            a.op("sta $2000", 3, 4, "line %d dot %d: the second pattern table" % (SPLIT_LINE, SPLIT_DOT))
            continue
        fine, coarse = y & 7, y >> 3
        hi = fine << 4 | coarse >> 3
        lo = (coarse & 7) << 5
        # LDY (4) + BMI (2) + LDA #$3F (2 or 3) + STA (4) + LDA (4) + LDX (2), then STX's write.
        slow = False
        d = target - 21 - a.t
        if d == 1:
            slow = True
            d = 0
        a.delay(d)
        a.op("ldy $%04X" % (RAM_LO + y), 3, 4)
        bmi_at = a.addr
        skip, join = "skip_%d" % y, "join_%d" % y
        path = a.t
        a.branch("bmi", skip, taken=False)
        if slow:
            a.op("lda $%02X" % ZP_3F, 2, 3)
        else:
            a.op("lda #$3F", 2, 2)
        a.op("sta $2006", 3, 4)
        a.op("lda $%04X" % (RAM_COL + y), 3, 4)
        a.op("ldx #$%02X" % lo, 2, 2)
        a.op("stx $2001", 3, 4, "line %d dot %d: off, for line %d" % (y - 1, off_dot, y))
        a.op("sty $2006", 3, 4)
        a.op("sta $2007", 3, 4)
        a.op("lda #$%02X" % hi, 2, 2)
        a.op("sta $2006", 3, 4)
        a.op("stx $2006", 3, 4)
        a.op("lda #$%02X" % MASK_ON, 2, 2)
        a.op("sta $2001", 3, 4, "on, 24 cycles after")
        a.op("jmp " + join, 3, 3)
        length = a.t - path
        a.label(skip)
        a.t = path + a.taken_cost(bmi_at, skip)
        a.delay(path + length - a.t)
        a.label(join)
        assert a.t == path + length
    a.op("jmp ($%02X)" % ZP_END_PTR, 3, 5)
    a.t += 2 + (OFFSETS - 1 - CENTRE) + 3
    a.label("kernel_end")
    a.op("rts", 1, 6)
    cycles = a.t - entry

    # The offsets' stubs: i cycles more at the start, as many fewer at the end.
    a.out.append("")
    for i in range(OFFSETS):
        a.label("off_%d" % i)
        a.t = 0
        a.delay(2 + i)
        a.op("jmp kernel_body", 3, 3)
        a.label("end_%d" % i)
        a.t = 0
        a.delay(2 + OFFSETS - 1 - i)
        a.op("jmp kernel_end", 3, 3)
    a.out.append("")
    a.out.append("off_lo: .byte " + ", ".join("<off_%d" % i for i in range(OFFSETS)))
    a.out.append("off_hi: .byte " + ", ".join(">off_%d" % i for i in range(OFFSETS)))
    a.out.append("end_lo: .byte " + ", ".join("<end_%d" % i for i in range(OFFSETS)))
    a.out.append("end_hi: .byte " + ", ".join(">end_%d" % i for i in range(OFFSETS)))
    a.addr += 4 * OFFSETS
    a.out.append("")
    for name, addr in sorted(a.found.items(), key=lambda kv: kv[1]):
        a.out.append(".assert %s = $%04X, error, \"gen_linetest.py's addresses are wrong\"" % (name, addr))
    return a, cycles


KERNEL_CYCLES = {}


def timed(off_dot):
    labels = {}
    for _ in range(6):
        a, cycles = generate(labels, off_dot)
        if a.found == labels and KERNEL_CYCLES.get("cycles") == cycles:
            return "\n".join(a.out) + "\n"
        labels = a.found
        KERNEL_CYCLES["cycles"] = cycles
    raise SystemExit("the timed code's addresses do not settle")


# --- Banks -----------------------------------------------------------------

def tile(rows):
    """8 rows of 8 colours (0-3) as a tile's two planes."""
    lo = bytes(sum(((c & 1) << (7 - x)) for x, c in enumerate(r)) for r in rows)
    hi = bytes(sum(((c >> 1) << (7 - x)) for x, c in enumerate(r)) for r in rows)
    return lo + hi


def pattern_bank():
    """Stripes of each palette's colours 1 and 2 with diagonals of colour 3
    that run on across tiles (a line or tile out of place breaks them),
    and every allowed line changing one colour."""
    tiles = [tile([[0] * 8] * 8)]
    for base in (1, 2):
        tiles.append(tile([[3 if (x - y) % 8 == 0 else base for x in range(8)] for y in range(8)]))
    chr_half = b"".join(tiles).ljust(0x1000, b"\0")
    chr_all = chr_half + chr_half
    names = bytearray(1024)
    for row in range(30):
        for col in range(1, 31):
            names[row * 32 + col] = 1 + (col & 1)
    for row in range(8):
        for col in range(8):
            byte = 0
            for q in range(4):
                square_x = col * 2 + (q & 1)
                byte |= (square_x % 4) << (2 * q)
            names[960 + row * 8 + col] = byte
    pal = bytes([0x0F, 0x10, 0x00, 0x30] * 4)
    lo = bytearray([0xFF] * 256)
    col_ = bytearray(256)
    entries = [e for e in range(1, 16) if e % 4]
    k = 0
    for y in range(8, 232):
        if allowed(y):
            lo[y] = entries[k % 12]
            col_[y] = 0x10 * (1 + (k // 12) % 3) + 1 + (k * 5) % 12
            k += 1
    return assemble(chr_all, bytes(names), pal, bytes(lo), bytes(col_))


def assemble(chr_, names, pal, lo, col):
    bank = bytearray([0xFF] * 0x4000)
    bank[0x0000:0x2000] = chr_
    bank[0x2000:0x2400] = names
    bank[0x2400:0x2410] = pal
    bank[0x2500:0x2600] = lo.ljust(256, b"\xFF")
    bank[0x2600:0x2700] = col.ljust(256, b"\0")
    return bytes(bank)


def picture_bank(base):
    made = open(base + ".bin", "rb").read()
    pal = open(base + ".pal", "rb").read()
    sched = open(base + ".sched", "rb").read()
    lo = bytearray([0xFF] * 256)
    col = bytearray(256)
    for y in range(240):
        entry, colour = sched[2 * y], sched[2 * y + 1]
        if entry != 0xFF:
            if not allowed(y):
                raise SystemExit("%s: a change on line %d, which cannot have one" % (base, y))
            lo[y], col[y] = entry, colour
    return assemble(made[:0x2000], made[0x2000:0x2400], pal, bytes(lo), bytes(col))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("pictures", nargs="*")
    parser.add_argument("--off-dot", type=int, default=245)
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "timed.s"), "w") as f:
        f.write(timed(args.off_dot))
    banks = [pattern_bank()] + [picture_bank(p) for p in args.pictures]
    if len(banks) > 7:
        raise SystemExit("at most 6 pictures")
    for n in range(7):
        with open(os.path.join(args.out, "bank%d.bin" % n), "wb") as f:
            f.write(banks[n] if n < len(banks) else bytes([0xFF]) * 0x4000)
    with open(os.path.join(args.out, "banks.inc"), "w") as f:
        f.write("BANKS = %d\n" % len(banks))


if __name__ == "__main__":
    main()
