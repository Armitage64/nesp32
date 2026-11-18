#!/usr/bin/env python3
"""Write the console's routines that play sound, one per rate.

    tools/gen_pcm.py build/pcm_rates.inc

For every rate in pcm.PERIODS this writes a routine that receives bytes and
writes each to $4011 as it arrives, until one comes without bit 7, or
until button A of controller 1 is down. Every read of $4017 is on its exact
cycle. Each routine starts on its own page
and must end on it, so no branch pays the page-crossing cycle;
tests/test_sound.py measures them all on py65.

They are the fast receiver of the throughput test (../throughput/README.md),
which ran on a real console at each of these rates, with a write to $4011
where that one stores the byte. A sample is asl / eor $4017 with the byte
in A, 6 cycles, which leaves the byte scrambled in a way the host allows
for (pcm.raw_byte), so nothing is put right here.

The hunt for a start bit compares the port with what it reads at one
(PORT_START), 6 cycles a look, four looks to a loop and 7 cycles round the
corner. Both ways out of it reach the byte's code the same number of cycles
after the read that saw the start bit, which fell 3.1 cycles earlier on
average. After the last sample come the write, the test of bit 7 and enough
padding that the hunt starts again where the two stop bits meet: not before
the last data bit is over, or a 0 there is taken for a start bit.

From 13 cycles a bit up the padding is long enough to need a loop, which
counts in Y. The hunt then compares with A, and since a byte's code is
longer than a branch reaches, its ways out are jumps.

At the rates pcm.tracked names, 8 and 7 cycles a bit, the hunt is too
coarse: a look every 6 cycles leaves a sample up to 3.5 cycles off the
middle of a bit of 8, and on a real NES that rate lost bytes where 7 and
6 with the throughput test's tracking receiver lost none. So these
routines are that receiver (../throughput/tools/gen_rates.py). Once a
byte it reads the line where the start bit's edge should be (cpx, with X
holding PORT_START). Already low, it is late or on time and takes 4
cycles to its first sample; still high, it is early and takes 6. A byte is
so a cycle shorter or longer than the line's, and the edge stays within a
cycle of the look. At 7 cycles a bit the gaps between samples are 6 and 8
by turns, since a gap of 7 has 1 cycle of padding, which cannot be.

The first byte is found by a hunt, up to 6 cycles out, and the nesp32
sends pcm.LEAD bytes of $FF ahead of the samples for the routine to work
that off on: it counts them in Y, and neither plays nor looks at them.
After them it takes its bytes two to a loop, the same but for what comes
after the last sample: the first of the two looks at button A, the
second jumps back. A tracking routine goes by the clock and has no hunt
after the first byte, so a gap in the samples, which a nesp32 does not
leave, would put it out of step.

Button A is looked at once a byte, in the stop bits, or at the tracked
rates once every two. The line to the nesp32
is OUT0, which is at rest for as long as a sound plays, and at rest it
keeps the controller loading its buttons: a read of $4016 then gives A as
it is now, as PORT_START if it is down, with nothing put on the line. The
look is cpy $4016 / beq, 6 cycles, and Y has PORT_START already where the
hunt compares with it. That is 3 cycles more than the padding it took the
place of in the three fastest routines, whose hunt begins that much later,
still before the next start bit can fall; the others had the room. A
routine left this way returns with carry set and the last byte in A, and
pcm_hush is what its caller does next: it tells the nesp32, which is still
sending, and waits for it to stop. The other buttons are behind the
controller's shift register, which is clocked only with OUT0 held low, and
are not read.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pcm  # noqa: E402

READ_AT = 3             # an absolute read lands on its 4th cycle
SAMPLE = 6              # asl a, eor abs
MEAN_EDGE = 3.1         # cycles from the start edge to the look that sees it
HUNT_TO_CODE = 6        # from that look to the byte's code
ROOMY_HUNT_TO_CODE = 9  # where the ways out are jumps
WRITE = 9               # sta abs, bpl not taken, and 3 of padding
LOOK = 6                # cpy abs, beq not taken: button A
ROOMY_TAIL = 15         # from the last sample to the hunt's first look, at least


def direct_sample(bit):
    """Cycles in one of the direct receiver's samples: lda abs, the shifts
    that take the Stick's bit into carry — bit + 1 of them, the first
    bringing the port's bit 0 there — and ror abs, which packs it."""
    return 12 + 2 * bit

# Ways to pass time: (cycles, bytes, lines). pha / pla puts A back.
PADS = ((2, 1, ["    nop"]), (3, 2, ["    bit $00"]), (7, 2, ["    pha", "    pla"]))
LOOP_BYTES = 5          # ldy #n, then dey / bne: 5n + 1 cycles


def delay(cycles, y=True, _memo={0: (0, [])}, _memo_y={0: (0, [])}):
    """Lines of code that take exactly this many cycles, in the fewest
    bytes. Uses Y from 12 cycles up, unless y is False."""
    if cycles == 1 or cycles < 0:
        raise ValueError("cannot pad %d cycles" % cycles)
    return list(_pad(cycles, _memo if y else _memo_y, y)[1])


def _pad(cycles, memo, y=True):
    if cycles not in memo:
        choices = []
        for cost, size, lines in PADS:
            if cycles - cost >= 0 and cycles - cost != 1:
                rest = _pad(cycles - cost, memo, y)
                choices.append((size + rest[0], lines + rest[1]))
        loops, rest = divmod(cycles - 1, 5)
        if rest == 1:
            loops, rest = loops - 1, 6
        if y and 1 <= loops <= 255 and cycles >= 12:
            tail = _pad(rest, memo, y)
            choices.append((LOOP_BYTES + tail[0],
                            ["    ldy #%d" % loops, ":   dey", "    bne :-"] + tail[1]))
        memo[cycles] = min(choices, key=lambda choice: choice[0])
    return memo[cycles]


def stream_routine(name, period):
    roomy = period >= pcm.ROOMY_FROM
    to_code = ROOMY_HUNT_TO_CODE if roomy else HUNT_TO_CODE
    first = int(1.5 * period - MEAN_EDGE - to_code - READ_AT + 0.5)
    rest = max(0, int(1.5 * period) - ROOMY_TAIL) if roomy else 0
    compare = "cmp" if roomy else "cpy"
    lines = ["", ".align 256",
             "; %d cycles a bit, %d baud, %d samples a second" % (
                 period, pcm.baud(period), round(pcm.sample_rate(period))),
             "%s:" % name]
    lines += (["    jmp @arm", "@byte:"] if roomy else
              ["    ldy #PORT_START", "    jmp @hunt", "@found:",
               "    nop             ; evens out the two ways here", "@byte:"])
    lines += delay(first + 1 if first == 1 else first)
    lines.append("    lda JOY2")
    for _ in range(7):
        lines += delay(period - SAMPLE)
        lines += ["    asl a", "    eor JOY2"]
    # The padding comes after the branch, which needs the flags the last
    # sample left.
    lines += ["    sta APU_DMC_LEVEL   ; the sample; bit 7 is not the DAC's",
              "    bpl @done           ; and clear in the last byte"]
    # Button A. The fast routines have 3 cycles of padding to give it and
    # no more; the others give it what it takes, or a cycle less where
    # that would leave one, which cannot be passed.
    if roomy:
        spare = WRITE - 6 + rest - LOOK - 2
        lines.append("    ldy #PORT_START")
    lines += ["    cpy JOY1            ; button A, with the line at rest",
              "    beq @pressed"]
    if roomy:
        lines += delay(2 if spare == 1 else spare)
        lines += ["@arm:", "    lda #PORT_START"]
    lines.append("@hunt:")
    lines += ["    %s JOY2" % compare, "    beq @found"] * 3
    lines += ["    %s JOY2" % compare, "    bne @hunt"]
    if roomy:
        lines += ["    bit $00         ; evens out the two ways out", "    jmp @byte",
                  "@found:", "    nop"]
    lines += ["    jmp @byte", "@done:", "    clc", "    rts", "@pressed:", "    sec", "    rts",
              '    .assert >(%s) = >(* - 1), error, "%s crosses a page"' % (name, name)]
    return lines


TRACK_TO_SAMPLE = 9     # from the look to the first sample's code: 8 if late, 10 if early
LOOK_AND_LOAD = 13      # that, and lda JOY2: from the look to the end of the first sample
SETTLE_TAIL = 5         # dey, bne: after the last sample of a byte that is not played
PAIR_TAILS = (9, 12)    # sta, bpl, jmp after the second of a pair; then cpx / beq (button A)
                        # after the first, the tail before the second's look


def tracked_gaps(period):
    """Cycles between a byte's 8 samples: a gap is 6 or at least 8."""
    if period - SAMPLE == 1:
        return [6, 8] * 3 + [6]
    return [period] * 7


def tracked_routine(name, period):
    byte = pcm.FRAME_BITS * period
    gaps = tracked_gaps(period)
    first = int(1.5 * period) - TRACK_TO_SAMPLE
    first += first == 1
    # From one look to the next is a byte: the look and the first sample,
    # the other seven, what comes after them and the turn to the next. A
    # look's turn so follows the byte before it: the first of a pair's,
    # the second's; the second's, the first's.
    turns = [byte - LOOK_AND_LOAD - sum(gaps) - tail - first
             for tail in (SETTLE_TAIL,) + PAIR_TAILS]
    assert all(turn >= 0 and turn != 1 for turn in turns), (period, turns)
    settle_turn, turn_one, turn_two = turns
    # Out of the last byte not played: bne not taken, and to the first
    # pair's look as if from a byte played.
    into = 1 + settle_turn - turn_one

    def receive(label, turn, early, y=True):
        lines = ["@look%s:" % label]
        lines += delay(turn, y=y)
        lines += ["    cpx JOY2            ; where the start bit's edge should be",
                  "    bne %s       ; still at mark: a longer way round" % early,
                  "    nop", "@sample%s:" % label]
        lines += delay(first, y=y)
        lines.append("    lda JOY2")
        for gap in gaps:
            lines += delay(gap - SAMPLE, y=y)
            lines += ["    asl a", "    eor JOY2"]
        return lines

    lines = ["", ".align 256",
             "; %d cycles a bit, %d baud, %d samples a second, tracking" % (
                 period, pcm.baud(period), round(pcm.sample_rate(period))),
             "%s:" % name, "    ldx #PORT_START", "    ldy #%d" % pcm.LEAD,
             "@hunt:"]
    lines += ["    cpx JOY2", "    beq @sample_lead"] * 3
    lines += ["    cpx JOY2", "    bne @hunt",
              "@early_lead:", "    jmp @sample_lead"]
    lines += receive("_lead", settle_turn, "@early_lead", y=False)
    lines += ["    dey                 ; a byte of the lead, not played", "    bne @look_lead"]
    lines += delay(into)
    lines += receive("_one", turn_one, "@early_one")
    lines += ["    sta APU_DMC_LEVEL   ; the sample; bit 7 is not the DAC's",
              "    bpl @done           ; and clear in the last byte",
              "    cpx JOY1            ; button A, with the line at rest",
              "    beq @pressed"]
    lines += receive("_two", turn_two, "@early_two")
    lines += ["    sta APU_DMC_LEVEL", "    bpl @done", "    jmp @look_one",
              "@early_one:", "    jmp @sample_one", "@early_two:", "    jmp @sample_two",
              "@done:", "    clc", "    rts", "@pressed:", "    sec", "    rts",
              '    .assert >(%s) = >(* - 1), error, "%s crosses a page"' % (name, name)]
    return lines


# The direct receiver, for a Famicom. Its expansion port carries the Stick's
# data on joypad 2's /D1 or higher (docs/WIRING.md, the Famicom), and the
# fold receiver needs the data in bit 0: a bit at position p, fed through
# asl / eor, has walked p samples' worth of shifts out of the top of A by
# the byte's end. So each sample is read out on its own: lda $4017, the
# lsr's that take the Stick's bit into carry, and ror into a byte of its
# own, which arrives bits-reversed; the fold's scramble (pcm.raw_byte) is
# one eor a byte, off the sample clock. Only the Stick's bit is looked at,
# which is why the hardwired controller II, whose data line is the port's
# bit 0, that every read of $4017 shifts and that a controller read's
# strobe re-loads for the eight reads after it, is of no concern here; the
# hunts and the hush test the port through the Stick's bit alone for the
# same reason. At these rates, 12 cycles a sample and up, the two fastest
# of the nesp32's rates are out of reach: the fold's 6-cycle sample is what
# bought them on a NES.
#
# The byte is kept in nesp_tx_data, which no exchange is using while a
# sound plays, as pcm_hush's nesp_count and nesp_index are.
DIRECT_RATES = "the rates at which a Famicom's routines are generated"


def direct_stream_routine(name, period, bit):
    first = int(1.5 * period - MEAN_EDGE - ROOMY_HUNT_TO_CODE - READ_AT + 0.5)
    first += first == 1
    sample = direct_sample(bit)
    # The hunt resumes in the stop bits: after the last data bit is over,
    # and before the next start bit falls. The finalize is five cycles
    # longer than the fold's write, and the slot ends nine after its read
    # where the fold's ends one; the spare that places the resume is
    # taken from the middle of what the window leaves. The pads never
    # touch Y (they are shorter than 12 cycles), so Y carries the button
    # check's constant from the routine's entry, once, for every byte.
    # The first sample is aimed a cycle early: the byte's code, with the
    # direct receiver's 14-cycle finalize and check, is otherwise a cycle
    # longer than the wire's byte, and the hunt's phase would slip a
    # cycle a byte until a start bit was missed whole.
    first -= 1
    spare = max(0, int(3 * period - first - 43.1) - 2)
    if spare == 1:
        spare = 0
    mask = 1 << bit
    lines = ["", ".align 256",
             "; %d cycles a bit, %d baud, %d samples a second, reading bit %d of $4017" % (
                 period, pcm.baud(period), round(pcm.sample_rate(period)), bit),
             "%s:" % name,
             "    ldy #PORT_REST     ; the button check's, for every byte",
             "    jmp @arm", "@byte:"]
    lines += delay(first, y=False)
    for index in range(8):
        if index:
            lines += delay(period - sample, y=False)
        lines += (["    lda JOY2"] + ["    lsr a"] * (bit + 1) +
                  ["    ror a:nesp_tx_data"])
    lines += ["    ldx a:nesp_tx_data",
              "    lda pcm_direct_table,x ; the fold's raw, from the wire's order",
              "    sta APU_DMC_LEVEL   ; the sample; bit 7 is not the DAC's",
              "    bpl @done           ; and clear in the last byte",
              "    cpy JOY1            ; button A, with the line at rest",
              "    beq @pressed"]
    lines += delay(spare, y=False)
    lines += ["@arm:", "    lda #$%02X" % mask]
    lines.append("@hunt:")
    lines += ["    bit JOY2", "    bne @found"] * 3
    lines += ["    bit JOY2", "    beq @hunt",
              "    bit $00         ; evens out the two ways out", "    jmp @byte",
              "@found:", "    nop"]
    lines += ["    jmp @byte", "@done:", "    clc", "    rts", "@pressed:", "    sec", "    rts",
              '    .assert >(%s) = >(* - 1), error, "%s crosses a page"' % (name, name)]
    return lines
# A look is 13 cycles, and 256 of them a pass. On a Famicom the look reads
# the port through the Stick's bit, for the hardwired controller II's bit 0;
# the same 13 cycles.
HUSH = """
; A routine above came back with carry set: button A is down, and the
; nesp32 is still sending. A = the byte the DAC was last given.
;
; The nesp32 is told with NESP_SOUND_SAY bytes at the link's rate, which
; its UART, at the sound's rate, hears as that many of some kind; any bytes
; at all from a console in the middle of a sound mean that it has stopped
; listening. Then the DAC is brought to its rest, over some 20 ms, and the
; line is watched until it has been quiet for NESP_RAW_REST_MS: what the
; nesp32 had already given its UART goes by unheard. If it is still sending
; after half a second or so it is told again. Uses nesp_count and
; nesp_index, which no exchange is using, and destroys A, X and Y.
HUSH_PASSES = NESP_RAW_REST_MS * (NESP_CPU_HZ / 1000) / (13 * 256) + 1
HUSH_PATIENCE = 100
.proc pcm_hush
    and #$7F
    sta nesp_index              ; the DAC's level
@say:
    ldx #NESP_SOUND_SAY
@word:
    lda #$FF                    ; a start bit and nothing more: one byte heard
    jsr nesp_tx_byte            ; for each, at any rate. Preserves X
    dex
    bne @word
@fall:
    lda nesp_index
    beq @down
    dec nesp_index
    lda nesp_index
    sta APU_DMC_LEVEL
    ldy #50
:   dey
    bne :-
    beq @fall
@down:
    lda #HUSH_PATIENCE
    sta nesp_index
    lda #0
    sta nesp_count
@listen:
    ldx #HUSH_PASSES
    ldy #0
@look:
%s
    bne @busy
    dey
    bne @look
    dex
    bne @look
    rts
@busy:
    dec nesp_count
    bne @listen
    dec nesp_index
    bne @listen
    beq @say
.endproc
.assert HUSH_PASSES < 256, error, "the passes are counted in X"
"""


def include(bit=0):
    lines = ["; Generated by tools/gen_pcm.py. Do not edit.", "",
             "PCM_COUNT = %d" % len(pcm.PERIODS),
             "NESP_PORT_BIT = %d" % bit]
    if bit:
        # A Famicom: the Stick's data on joypad 2's /D1 or higher, and the
        # hardwired controller II's bit 0, which rests at one (its shift
        # register drains to its grounded serial input as the routines
        # read the port).
        rest = pcm.PORT_IDLE | 1
        possible = [index for index, period in enumerate(pcm.PERIODS)
                    if period >= direct_sample(bit)]
        lines += ["PORT_REST = $%02X      ; what JOY2 reads with the line at rest: on a" % rest,
                  "                       ; Famicom the hardwired controller II's bit is one",
                  "PORT_START = $%02X     ; and at a start bit" % (rest | (1 << bit)),
                  "PCM_LIMIT = %d         ; rates from this index on are refused" % (possible[-1] + 1),
                  "PCM_HQ = %d          ; the fastest rate this console has a routine for" % possible[-1]]
    else:
        lines += ["PORT_IDLE = $%02X      ; what JOY2 reads with the line at rest" % pcm.PORT_IDLE,
                  "PORT_START = $%02X     ; and at a start bit" % (pcm.PORT_IDLE | 1),
                  "PCM_LIMIT = %d         ; rates from this index on are refused" % len(pcm.PERIODS),
                  "PCM_HQ = %d           ; the fastest rate this console has a routine for" % (
                      len(pcm.PERIODS) - 1)]
    lines += ["", '.segment "SOUND"']
    names = ["pcm_stream_%d" % index for index in range(len(pcm.PERIODS))]
    if bit:
        for index, period in enumerate(pcm.PERIODS):
            if period >= direct_sample(bit):
                lines += direct_stream_routine(names[index], period, bit)
            else:
                lines += ["", ".align 256",
                          "; %d cycles a bit: no routine for it on this console, and" % period,
                          "; sound_rate refuses the rate before a routine is asked for",
                          "%s:" % names[index], "    sec", "    rts",
                          '    .assert >(%s) = >(* - 1), error, "%s crosses a page"' % (
                              names[index], names[index])]
        lines += (HUSH % "\n".join(["    lda #$%02X" % (1 << bit), "    bit JOY2"])).splitlines()
    else:
        for name, period in zip(names, pcm.PERIODS):
            lines += (tracked_routine(name, period) if pcm.tracked(period)
                      else stream_routine(name, period))
        lines += (HUSH % "\n".join(["    lda JOY2", "    cmp #PORT_IDLE"])).splitlines()
    lines += ["", '.segment "RODATA"',
              "pcm_stream_lo: .byte " + ", ".join("<" + name for name in names),
              "pcm_stream_hi: .byte " + ", ".join(">" + name for name in names)]
    if bit:
        # The direct receiver's table, on a page of its own: the lookup's
        # abs,x must never pay a page-crossing cycle, which would wobble
        # the sound's timing.
        lines += ["", '.segment "TABLE"',
                  '.align 256',
                  "pcm_direct_table:   ; what the fold would hold for each wire byte,",
                  "                    ; as the direct receiver's byte arrives: the port's",
                  "                    ; buffer inverts the line, so its bits are the",
                  "                    ; complement of the byte that went out",
                  "    .byte " + ", ".join("$%02X" % (pcm.raw_byte(value ^ 0xFF))
                                          for value in range(256))]
    return "\n".join(lines) + "\n"


def main(argv):
    bits = [int(option.split("=")[1]) for option in argv[2:]
            if option.startswith("--joy2-bit=")]
    with open(argv[1], "w") as handle:
        handle.write(include(bits[0] if bits else 0))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
