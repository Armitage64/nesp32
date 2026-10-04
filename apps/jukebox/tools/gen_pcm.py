#!/usr/bin/env python3
"""Write the console's routines that play sound, one per rate.

    tools/gen_pcm.py build/pcm_rates.inc

For every rate in pcm.PERIODS this writes a routine that receives bytes and
writes each to $4011 as it arrives, until one comes without bit 7. Every
read of $4017 is on its exact cycle. Each routine starts on its own page
and must end on it, so no branch pays the page-crossing cycle;
tests/test_sound.py measures them all on py65.

They are the fast receiver of the throughput test (throughput/README.md),
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
    lines += delay(WRITE - 6 + rest)
    if roomy:
        lines += ["@arm:", "    lda #PORT_START"]
    lines.append("@hunt:")
    lines += ["    %s JOY2" % compare, "    beq @found"] * 3
    lines += ["    %s JOY2" % compare, "    bne @hunt"]
    if roomy:
        lines += ["    bit $00         ; evens out the two ways out", "    jmp @byte",
                  "@found:", "    nop"]
    lines += ["    jmp @byte", "@done:", "    rts",
              '    .assert >(%s) = >(* - 1), error, "%s crosses a page"' % (name, name)]
    return lines


def include():
    lines = ["; Generated by tools/gen_pcm.py. Do not edit.", "",
             "PCM_COUNT = %d" % len(pcm.PERIODS),
             "PORT_IDLE = $%02X      ; what JOY2 reads with the line at rest" % pcm.PORT_IDLE,
             "PORT_START = $%02X     ; and at a start bit" % (pcm.PORT_IDLE | 1),
             "", '.segment "SOUND"']
    names = ["pcm_stream_%d" % index for index in range(len(pcm.PERIODS))]
    for name, period in zip(names, pcm.PERIODS):
        lines += stream_routine(name, period)
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
