#!/usr/bin/env python3
"""Write the console's cycle-timed serial routines and the CRC's tables.

    tools/gen_link.py build/link.inc

The link runs at one rate, linkrate.PERIOD CPU cycles a bit, and the Stick's
UART is set from the same number. This writes, for that rate:

    rx_block    receive a reply, REPLY_SIZE bytes, into rx_buf
    tx_byte     send A as 8N1
    crc_table_hi, crc_table_lo    CRC-16/CCITT-FALSE, a byte at a time

Each routine sits on a page of its own and must end on it, so no branch pays
the page-crossing cycle; tests/test_link_timing.py measures every read of
$4017 and write of $4016 on py65.

The generators and the padding are nes-jukebox's (throughput/tools/
gen_rates.py: `receiver`, `sender`, `delay`), and the sampling is the
jukebox's own: lda, lsr, ror, 11 cycles, which asks nothing of the port's
unused bits and stores the byte the right way round.

Receiving. t0 is the cycle on which the hunt's lda read the start bit. The
hunt reads every 9 cycles, so the edge fell 0 to 9 cycles before t0, 4.5 on
average, and data bit k's center is t0 - 4.5 + (1.5 + k) * period. The hunt
loop is below the code for a byte and jumps up to it, the byte's code being
longer than a branch reaches.

After a byte's last sample the routine stores it and hunts again 25 cycles
later. That must be after the last data bit is over, or a 0 there is taken
for a start bit, and before the next start bit falls: between half a bit
and two and a half, since the Stick sends two stop bits.

Sending. A holds the byte and shifts right after each write, so a bit costs
sta + lsr, 6 cycles, and the rest is padding. Bits 1 and 2 of A reach OUT1
and OUT2 as well, which go nowhere but the expansion port. The stop bit is
held for a whole bit before the routine returns, and the caller's loop makes
it longer, which a UART does not mind.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "firmware", "stick"))

from neswiki import linkrate  # noqa: E402

HUNT_PASS = 9           # cycles from one of the hunt's reads to the next
HUNT_TO_CODE = 8        # from the hunt's read to the byte's code: lsr, bcc, jmp
READ_AT = 3             # lda abs reads on its 4th cycle
SAMPLE = 11             # lda abs, lsr, ror zp
MEAN_EDGE = HUNT_PASS / 2   # cycles from the start edge to the hunt's read
BLOCK_TAIL = 25         # from a byte's last sample to the hunt's next read

# Ways to pass time: (cycles, bytes, lines). pha / pla puts A back, and none
# of them touch carry, which holds a bit between a sample's lsr and ror.
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


def first_sample_delay(period):
    return int(1.5 * period - MEAN_EDGE - HUNT_TO_CODE - READ_AT + 0.5)


def check_tail(period):
    """The hunt for the next byte must start inside the stop bits."""
    stop_begins = 0.5 * period
    next_start = stop_begins + (linkrate.TO_NES_BITS - 9) * period
    # The edge may have fallen up to MEAN_EDGE either side of where the
    # samples assume, and the first look of the hunt may just miss it.
    if not stop_begins + MEAN_EDGE < BLOCK_TAIL < next_start - MEAN_EDGE:
        raise ValueError("at %d cycles a bit the receiver's hunt misses the stop bits" % period)


def receiver(period):
    check_tail(period)
    lines = ["", ".align 256",
             "; Receive REPLY_SIZE bytes into rx_buf. %d cycles a bit, %d baud."
             % (period, linkrate.baud(period)),
             "; There is no timeout; the caller's NMI is one. X counts up to 0.",
             "; Destroys A, X and Y.",
             ".proc rx_block", "    ldx #<(256 - REPLY_SIZE)", "    jmp @hunt", "@byte:"]
    for bit in range(8):
        lines += delay(first_sample_delay(period) if bit == 0 else period - SAMPLE)
        lines += ["    lda JOY2", "    lsr a", "    ror rx_data"]
    lines += ["    lda rx_data", "    eor #$FF            ; the port inverts D0",
              "    sta rx_buf - (256 - REPLY_SIZE),x", "    inx", "    beq @done",
              "@hunt:                      ; the tests skip ahead while this sees mark",
              "    lda JOY2", "    lsr a", "    bcc @hunt", "    jmp @byte",
              "@done:", "    rts", ".endproc", one_page("rx_block")]
    return lines


def sender(period):
    lines = ["", ".align 256",
             "; Send A as 8N1, %d cycles a bit. OUT0 must be at mark, and is left"
             % period,
             "; there for a whole bit before this returns. Destroys A and Y.",
             ".proc tx_byte", "    sta tx_data", "    lda #0",
             "    sta JOY1            ; start bit", "    lda tx_data"]
    lines += delay(period - 7)
    for bit in range(8):
        lines += ["    sta JOY1            ; bit %d" % bit,
                  "    lsr a" if bit < 7 else "    lda #OUT0_MARK"]
        lines += delay(period - 6)
    lines += ["    sta JOY1            ; stop bit"]
    lines += delay(period)
    lines += ["    rts", ".endproc", one_page("tx_byte")]
    return lines


def one_page(name):
    return '.assert >(%s) = >(* - 1), error, "%s crosses a page"' % (name, name)


def crc_table():
    """T[i]: the CRC register after i << 8 has been through eight rounds.
    Per byte the console does index = crc_hi ^ byte; crc_hi = crc_lo ^
    hi[index]; crc_lo = lo[index]."""
    entries = []
    for index in range(256):
        crc = index << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
        entries.append(crc)
    return entries


def include():
    period = linkrate.PERIOD
    lines = ["; Generated by tools/gen_link.py. Do not edit.", "",
             "LINK_PERIOD = %d        ; CPU cycles a bit" % period,
             "REPLY_SIZE  = %d" % linkrate.REPLY_SIZE,
             "REPLY_TEXT  = %d         ; where its text begins" % linkrate.HEADER_SIZE,
             "", '.segment "RXTX"']
    lines += receiver(period)
    lines += sender(period)
    lines += ["", '.segment "RODATA"']
    entries = crc_table()
    for name, part in (("crc_table_hi", lambda v: v >> 8), ("crc_table_lo", lambda v: v & 0xFF)):
        lines.append("%s:" % name)
        for row in range(0, 256, 16):
            lines.append("    .byte " + ", ".join("$%02X" % part(v) for v in entries[row:row + 16]))
    return "\n".join(lines) + "\n"


def main(argv):
    with open(argv[1], "w") as handle:
        handle.write(include())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
