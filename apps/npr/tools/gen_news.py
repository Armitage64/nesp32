#!/usr/bin/env python3
"""Write the routine that plays the station and shows the headlines.

    tools/gen_news.py build/news.inc

The station is sampled sound, a byte a sample, written to $4011 as it
arrives: the jukebox's routine for 14 CPU cycles a bit (its
tools/gen_pcm.py), which leaves 8 cycles to spare between one look at the
line and the next, seven times a byte. This is that routine with the
spare cycles put to use. Every look at the line is on the cycle it was;
what was padding is now work. A stretch of 8 spare cycles is a slot.

The headlines come in the samples. The DAC takes seven bits of a byte;
the eighth is the nesp32's to send what it likes in, and it sends
characters, eight samples to each, the first bit first (nesp32's
docs/PROTOCOL.md, TUNER). A character from $20 up is one of a page's 252,
and goes into the stage, the page as it will be drawn. Below that: HOME, a
page follows, from its first character; SHOW, the page is whole; anything
else, the sound is over. $80 up is nothing, which is what the bit says at
rest. So the nesp32 chooses the page and the moment, and the console holds
one page and no more.

  Hunting       the byte the routine is in but for a quarter of a second
                in thirty. A character begins with a 0, and nothing is all
                1s, so one slot asks whether the last sample's eighth bit
                was 0 (X has the sample: cpx #$80 / bcc). The first that
                is, is a character's first.
  Listening     from there, eight samples to a character. Three slots
                take the bit: into news_shift (cpx #$80 / rol), one fewer
                in news_bits, and whether that was the eighth. When it
                was, the slots left sort the character, and one that is
                nothing sends the routine back to hunting; so it finds
                its place again with every page, whatever came before.
  Waiting       SHOW has come, and nothing follows it for as long as a
                page takes to draw. The PPU is asked once a byte, in the
                stop bits, whether vblank has begun: the NMI is off, since
                it would take cycles from the receiver. A byte is 154
                cycles and vblank 2273, so it is found within a
                fourteenth of its start.
  Drawing       the 12 bytes after: every slot is a character (ldy stage
                / sty $2007), or half of the PPU's address. A page takes
                four vblanks, waiting between them. It is drawn where it
                cannot be seen, on the other of the two nametables, and
                the last vblank changes the two over. Then hunting again.

A branch taken costs a cycle more than one not, and a slot is 8 either
way: ldy / beq / bit $00 one way and ldy / beq / nop the other. Whatever
else branches does so in the stop bits, where a cycle either way moves
nothing but the hunt for the next start bit, which has room.

A is the sample being received, except in the stop bits, when it has been
written. Y is scratch. X is the last sample while hunting and listening,
and the nametable being drawn on otherwise.

A character of a page is kept in the stop bits, where A is free: the slot
before has its place in X. Button A is not looked at in those bytes.

Button A is looked at in every byte's stop bits, as in the jukebox's
routines, and leaves with carry set; the character that ends the sound
leaves with it clear.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "jukebox", "tools"))

import gen_pcm  # noqa: E402
import pcm  # noqa: E402

PERIOD = 14
RATE = pcm.PERIODS.index(PERIOD)
SLOT = PERIOD - gen_pcm.SAMPLE          # spare cycles between two looks
SLOTS = 7                               # in a byte
FIRST = int(1.5 * PERIOD - gen_pcm.MEAN_EDGE - gen_pcm.ROOMY_HUNT_TO_CODE
            - gen_pcm.READ_AT + 0.5)

ROWS = 9
COLUMNS = 28
NEWS_ROW = 10                           # on the screen
NEWS_COLUMN = 2
STAGE = 0x0300
NAMETABLES = (0x2000, 0x2800)
VBLANK_BYTES = 12                       # of a vblank's 14.7, after the one that found it

assert ROWS * COLUMNS <= 256, "a page's characters are counted in a byte"


def pad(cycles):
    return gen_pcm.delay(cycles)


def slot(*lines, cycles):
    """A slot's code, padded to its 8 cycles."""
    return ["    " + line for line in lines] + pad(SLOT - cycles)


IDLE = slot(cycles=0)
# The eighth bit of the sample before, which X has, into the character.
TAKE = slot("cpx #$80", "rol a:news_shift", cycles=8)
COUNT = slot("dec news_bits", cycles=5)
# The scroll, which the address writes moved, and the nametable shown.
RESTORE = [slot("ldy #0", "sty PPUSCROLL", cycles=6),
           slot("sty PPUSCROLL", cycles=4),
           slot("ldy a:news_ctrl", "sty PPUCTRL", cycles=8)]
FLIP = [slot("ldy news_ctrl_for,x", "sty a:news_ctrl", cycles=8)]
HUNT_LOOKS = ["    cmp JOY2", "    beq %s"] * 3 + ["    cmp JOY2", "    bne %s"]


def char(index):
    return slot("ldy news_stage + %d" % index, "sty PPUDATA", cycles=8)


def address(row, column=0):
    """Two slots that point the PPU at a character's place on the
    nametable being drawn on."""
    offset = 32 * (NEWS_ROW + row) + NEWS_COLUMN + column
    return [slot("ldy news_hi_%02X,x" % (offset >> 8), "sty PPUADDR", cycles=8),
            slot("ldy #$%02X" % (offset & 0xFF), "sty PPUADDR", cycles=6)]


class Writer:
    def __init__(self):
        self.lines = []
        self.hunts = []
        self.count = 0

    def add(self, *lines):
        self.lines += lines

    def cells(self, slots):
        for code in slots:
            self.add(*code)
            self.add("    asl a", "    eor JOY2")

    def branch(self, test, to):
        """A slot that tests and may branch: 8 cycles if it does not, and
        6 if it does, which its target makes 8."""
        self.add(*["    " + line for line in test])
        self.add("    b%s %s" % to, "    bit $00", "    asl a", "    eor JOY2")

    def taken(self, name):
        self.add("%s:" % name, "    nop", "    asl a", "    eor JOY2")

    def stop_bits(self, to, keep=True, after=()):
        """The sample, the look at button A, and on to the hunt for the
        next byte's start bit. `keep` leaves the sample in X, for its
        eighth bit. A is free once the button has been looked at, and
        `after` is done then."""
        self.count += 1
        pressed = "@pressed%d" % self.count
        self.add("    sta APU_DMC_LEVEL   ; the sample; bit 7 is not the DAC's")
        if keep:
            self.add("    tax")
        self.add("    ldy #PORT_START",
                 "    cpy JOY1            ; button A, with the line at rest",
                 "    beq %s" % pressed)
        self.add(*after)
        self.add("    lda #PORT_START", "    jmp %s" % to,
                 "%s:" % pressed, "    jmp news_pressed")

    def hunt(self, name, to):
        """A hunt of its own for a byte: each goes on to different code.
        Kept apart and aligned, so that none of its branches crosses a
        page."""
        self.hunts += ["", ".align 32", "%s:" % name]
        self.hunts += ["    cmp JOY2", "    beq @found"] * 3
        self.hunts += ["    cmp JOY2", "    bne %s" % name,
                       "    bit $00         ; evens out the two ways out",
                       "    jmp %s" % to, "@found:", "    nop", "    jmp %s" % to]

    def begin(self, name):
        self.add("%s:" % name)
        self.add(*pad(FIRST))
        self.add("    lda JOY2")


def hunting(w):
    """The byte that waits for a character's first bit."""
    w.hunt("news_sync_hunt", "news_sync")
    w.hunt("news_listen_hunt", "news_listen")
    w.add("", ".align 256")
    w.begin("news_sync")
    w.add("    cpx #$80", "    bcc news_sync_first", "    nop", "    nop",
          "    asl a", "    eor JOY2")
    w.cells([IDLE] * 6)
    w.add("news_sync_plain:")
    w.stop_bits("news_sync_hunt")
    # A 0: the first of a character's eight, and seven to come.
    w.add("news_sync_first:", "    bit $00", "    asl a", "    eor JOY2")
    w.cells([slot("ldy #$FE", "sty news_shift", cycles=5),
             slot("ldy #7", "sty news_bits", cycles=5)] + [IDLE] * 4)
    w.stop_bits("news_listen_hunt")
    w.add('    .assert >news_sync = >(* - 1), error, "the hunting byte crosses a page"')


def listening(w):
    """The byte that takes the eighth bit, and the ways through it when a
    character is whole. All on a page, for their branches."""
    w.add("", ".align 256")
    w.begin("news_listen")
    w.cells([TAKE, COUNT])
    w.branch(["ldy news_bits"], ("eq", "news_listen_whole"))
    w.cells([IDLE] * 4)
    w.stop_bits("news_listen_hunt")

    # A character. Eight more bits to the next; then what it is.
    w.taken("news_listen_whole")
    w.cells([slot("ldy #8", "sty news_bits", cycles=5)])
    w.branch(["ldy news_shift"], ("mi", "news_listen_nothing"))
    w.add("    cpy #$20", "    bcc news_listen_control", "    nop", "    nop",
          "    asl a", "    eor JOY2")
    # Of a page: its place, and the place moved on; and in the stop bits,
    # into the stage. The sample goes round by Y to be X's again.
    w.cells([slot("ldx news_at", "inc news_at", cycles=8)])
    w.add("    sta APU_DMC_LEVEL", "    tay", "    lda news_shift", "    sta news_stage,x",
          "    tya", "    tax", "    lda #PORT_START", "    jmp news_listen_hunt")

    # Nothing: back to hunting.
    w.taken("news_listen_nothing")
    w.cells([IDLE] * 2)
    w.add("    jmp news_sync_plain     ; 3 cycles late with the sample, which is nothing")

    w.add("news_listen_control:", "    bit $00", "    asl a", "    eor JOY2",
          "    cpy #NESP_TUNER_NEWS_HOME", "    beq news_listen_home", "    nop", "    nop",
          "    asl a", "    eor JOY2",
          # SHOW: wait for vblank, with X as the nametable to draw on.
          # Anything else: the sound is over.
          "    sta APU_DMC_LEVEL",
          "    cpy #NESP_TUNER_NEWS_SHOW",
          "    bne news_listen_over",
          "    ldy #PORT_START",
          "    cpy JOY1",
          "    beq news_listen_pressed",
          "    ldx news_nt",
          "    lda #PORT_START",
          "    jmp news_wait0_hunt",
          "news_listen_over:", "    jmp news_done",
          "news_listen_pressed:", "    jmp news_pressed")
    w.add("news_listen_home:", "    bit $00", "    asl a", "    eor JOY2")
    w.stop_bits("news_listen_hunt", after=["    lda #0", "    sta news_at"])
    w.add('    .assert >news_listen = >(* - 1), error, "the listening byte crosses a page"')


def draw_runs():
    """The page's drawing cut into vblanks: each begins by pointing the
    PPU, also in the middle of a row, and ends by putting the scroll
    back; the last changes the nametables over first."""
    chars = [(row, column, char(row * COLUMNS + column))
             for row in range(ROWS) for column in range(COLUMNS)]
    capacity = VBLANK_BYTES * SLOTS
    runs = []
    while chars:
        slots = []
        row = None
        while chars:
            need = 1 + (2 if chars[0][0] != row else 0)
            # Room for the change-over too, in case this is the last.
            if len(slots) + need + len(RESTORE) + len(FLIP) > capacity:
                break
            this_row, column, code = chars.pop(0)
            if this_row != row:
                slots += address(this_row, column)
                row = this_row
            slots.append(code)
        runs.append(slots)
    for index, slots in enumerate(runs):
        slots += (FLIP if index == len(runs) - 1 else []) + RESTORE
        slots += [IDLE] * (capacity - len(slots))
    return runs


def waiting_and_drawing(w, runs):
    for index, slots in enumerate(runs):
        last = index == len(runs) - 1
        wait, draw = "news_wait%d" % index, "news_draw%d" % index
        # Waiting: the look for vblank.
        w.add("", ".align 256")
        w.begin(wait)
        w.cells([IDLE] * SLOTS)
        w.add("    sta APU_DMC_LEVEL",
              "    ldy #PORT_START",
              "    cpy JOY1            ; button A, with the line at rest",
              "    beq %s_pressed" % wait,
              "    bit PPUSTATUS       ; vblank? Asked once, it is forgotten",
              "    bmi %s_vblank" % wait,
              "    lda #PORT_START",
              "%s_hunt:" % wait)
        w.add(*[line % ("%s_found" % wait if "beq" in line else "%s_hunt" % wait)
                if "%s" in line else line for line in HUNT_LOOKS])
        w.add("    bit $00         ; evens out the two ways out", "    jmp %s" % wait,
              "%s_found:" % wait, "    nop", "    jmp %s" % wait,
              "%s_pressed:" % wait, "    jmp news_pressed",
              "%s_vblank:" % wait, "    lda #PORT_START", "    jmp %s_hunt" % draw,
              '    .assert >%s = >(* - 1), error, "a waiting byte crosses a page"' % wait)
        # Drawing: VBLANK_BYTES bytes, each with its own hunt before it.
        for byte in range(VBLANK_BYTES):
            name = draw if byte == 0 else "%s_%d" % (draw, byte)
            w.hunt(name + "_hunt", name)
            w.begin(name)
            w.cells(slots[byte * SLOTS:(byte + 1) * SLOTS])
            if byte < VBLANK_BYTES - 1:
                w.stop_bits("%s_%d_hunt" % (draw, byte + 1), keep=False)
            elif not last:
                w.stop_bits("news_wait%d_hunt" % (index + 1), keep=False)
            else:
                # The other nametable is the one to draw on next; and X is
                # a sample again, whose eighth bit is nothing.
                w.stop_bits("news_sync_hunt", keep=False,
                            after=["    txa", "    eor #1", "    sta news_nt", "    ldx #$FF"])


def routine():
    w = Writer()
    w.add("", '.segment "SOUND"', "", ".align 256",
          "; %d cycles a bit, %d baud, %d samples a second" % (
              PERIOD, pcm.baud(PERIOD), round(pcm.sample_rate(PERIOD))),
          "; X = $FF as it begins: a sample whose eighth bit is nothing.",
          "news_stream:", "    lda #PORT_START", "    jmp news_sync_hunt",
          "news_done:", "    clc", "    rts", "news_pressed:", "    sec", "    rts")
    hunting(w)
    listening(w)
    runs = draw_runs()
    waiting_and_drawing(w, runs)

    highs = sorted({(32 * (NEWS_ROW + row) + NEWS_COLUMN + column) >> 8
                    for row in range(ROWS) for column in range(COLUMNS)})
    tables = ["", '.segment "RODATA"',
              "news_ctrl_for: .byte " + ", ".join(
                  "$%02X" % (base >> 10 & 3) for base in NAMETABLES)]
    for high in highs:
        tables.append("news_hi_%02X:    .byte " % high + ", ".join(
            "$%02X" % ((base >> 8) + high) for base in NAMETABLES))
    return w.lines + w.hunts + tables, len(runs)


def include():
    code, runs = routine()
    lines = ["; Generated by tools/gen_news.py. Do not edit.", "",
             "NEWS_RATE = %d            ; as JUKE's sounds count them: %d cycles a bit" % (
                 RATE, PERIOD),
             "NEWS_ROWS = %d" % ROWS, "NEWS_COLUMNS = %d" % COLUMNS,
             "NEWS_VBLANKS = %d         ; that a page is drawn in" % runs,
             "news_stage = $%04X" % STAGE]
    return "\n".join(lines + code) + "\n"


def main(argv):
    with open(argv[1], "w") as handle:
        handle.write(include())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
