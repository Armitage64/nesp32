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

Button A is looked at once a byte, in the stop bits. The line to the nesp32
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

# Ways to pass time: (cycles, bytes, lines). pha / pla puts A back.
PADS = ((2, 1, ["    nop"]), (3, 2, ["    bit $00"]), (7, 2, ["    pha", "    pla"]))
LOOP_BYTES = 5          # ldy #n, then dey / bne: 5n + 1 cycles


def delay(cycles, _memo={0: (0, [])}):
    """Lines of code that take exactly this many cycles, in the fewest
    bytes. Uses Y from 12 cycles up."""
    if cycles == 1 or cycles < 0:
        raise ValueError("cannot pad %d cycles" % cycles)
    return list(_pad(cycles, _memo)[1])


def _pad(cycles, memo):
    if cycles not in memo:
        choices = []
        for cost, size, lines in PADS:
            if cycles - cost >= 0 and cycles - cost != 1:
                rest = _pad(cycles - cost, memo)
                choices.append((size + rest[0], lines + rest[1]))
        loops, rest = divmod(cycles - 1, 5)
        if rest == 1:
            loops, rest = loops - 1, 6
        if 1 <= loops <= 255 and cycles >= 12:
            tail = _pad(rest, memo)
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


# A look is 13 cycles, and 256 of them a pass.
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
    lda JOY2
    cmp #PORT_IDLE
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


def include():
    lines = ["; Generated by tools/gen_pcm.py. Do not edit.", "",
             "PCM_COUNT = %d" % len(pcm.PERIODS),
             "PORT_IDLE = $%02X      ; what JOY2 reads with the line at rest" % pcm.PORT_IDLE,
             "PORT_START = $%02X     ; and at a start bit" % (pcm.PORT_IDLE | 1),
             "", '.segment "SOUND"']
    names = ["pcm_stream_%d" % index for index in range(len(pcm.PERIODS))]
    for name, period in zip(names, pcm.PERIODS):
        lines += stream_routine(name, period)
    lines += HUSH.splitlines()
    lines += ["", '.segment "RODATA"',
              "pcm_stream_lo: .byte " + ", ".join("<" + name for name in names),
              "pcm_stream_hi: .byte " + ", ".join(">" + name for name in names)]
    return "\n".join(lines) + "\n"


def main(argv):
    with open(argv[1], "w") as handle:
        handle.write(include())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
