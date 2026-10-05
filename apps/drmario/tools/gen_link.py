#!/usr/bin/env python3
"""Write the console's cycle-timed serial routines and the link's constants.

    tools/gen_link.py build/link.inc

The link runs at one rate, linkrate.PERIOD CPU cycles a bit, and the Stick's
UART is set from the same number. This writes, for that rate:

    rx_block    receive a frame, FRAME_SIZE bytes, into net_reply
    tx_byte     send A as 8N1

Each routine must sit on one page, so no branch pays the page-crossing
cycle; the file asserts it, and tests/test_link_timing.py measures every
read of $4017 and write of $4016 on py65.

The generators and the padding are nes-wiki's (tools/gen_link.py), which
has them from nes-jukebox. What differs is the receiver's wait for a start
bit. Theirs has no timeout, because their NMI is one. Here the exchange is
made inside the NMI, so the wait counts its looks and gives up: X counts
256 looks, and net_tries counts those.

Receiving. t0 is the cycle on which the hunt's lda read the start bit. The
hunt reads every 13 cycles, so the edge fell 0 to 13 cycles before t0, 6.5
on average, and data bit k's center is t0 - 6.5 + (1.5 + k) * period. Once
in 256 looks the hunt takes 20 cycles to come round, and a start bit that
falls in that one is sampled up to 7 cycles later than it should be; the
frame's check bytes are what catch a bit misread there.

Between bits the padding uses no register: Y counts the bytes.

After a byte's last sample the routine stores it and hunts again 30 cycles
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

from drnet import linkrate  # noqa: E402

HUNT_PASS = 13          # cycles from one of the hunt's reads to the next
HUNT_TO_CODE = 6        # from the hunt's read to the byte's code: lsr, bcs
READ_AT = 3             # lda abs reads on its 4th cycle
SAMPLE = 11             # lda abs, lsr, ror zp
MEAN_EDGE = HUNT_PASS / 2   # cycles from the start edge to the hunt's read
BLOCK_TAIL = 30         # from a byte's last sample to the hunt's next read

# Ways to pass time: (cycles, bytes, lines). pha / pla puts A back, and none
# of them touch carry, which holds a bit between a sample's lsr and ror.
PADS = ((2, 1, ["    NOP"]), (3, 2, ["    BIT $00"]), (7, 2, ["    PHA", "    PLA"]))
LOOP_BYTES = 5          # ldy #n, then dey / bne: 5n + 1 cycles


def delay(cycles, use_y=True):
    """Lines of code that take exactly this many cycles, in the fewest
    bytes. With use_y, counts in Y from 12 cycles up."""
    if cycles == 1 or cycles < 0:
        raise ValueError("cannot pad %d cycles" % cycles)
    return list(_pad(cycles, use_y, {0: (0, [])})[1])


def _pad(cycles, use_y, memo):
    if cycles not in memo:
        choices = []
        for cost, size, lines in PADS:
            if cycles - cost >= 0 and cycles - cost != 1:
                rest = _pad(cycles - cost, use_y, memo)
                choices.append((size + rest[0], lines + rest[1]))
        loops, rest = divmod(cycles - 1, 5)
        if rest == 1:
            loops, rest = loops - 1, 6
        if use_y and 1 <= loops <= 255 and cycles >= 12:
            tail = _pad(rest, use_y, memo)
            choices.append((LOOP_BYTES + tail[0],
                            ["    LDY #%d" % loops, ":   DEY", "    BNE :-"] + tail[1]))
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
    lines = ["",
             "; Receive FRAME_SIZE bytes into net_reply. %d cycles a bit, %d baud."
             % (period, linkrate.baud(period)),
             "; net_tries is how long to wait for a start bit, in passes of 256",
             "; looks; it is not wound up again between bytes. Carry clear if the",
             "; frame came, set if the wait ran out. Destroys A, X and Y.",
             "rx_block:", "    LDY #<(256 - FRAME_SIZE)", "    LDX #$00",
             "@hunt:                      ; the tests skip ahead while this sees mark",
             "    LDA $4017", "    LSR", "    BCS @byte           ; the port inverts D0",
             "    DEX", "    BNE @hunt", "    DEC net_tries", "    BNE @hunt",
             "    SEC", "    RTS", "@byte:"]
    for bit in range(8):
        lines += delay(first_sample_delay(period) if bit == 0 else period - SAMPLE,
                       use_y=False)
        lines += ["    LDA $4017", "    LSR", "    ROR net_rx_data"]
    lines += ["    LDA net_rx_data", "    EOR #$FF",
              "    STA net_reply - (256 - FRAME_SIZE),Y", "    INY", "    BEQ @done",
              "    LDX #$00", "    JMP @hunt", "@done:", "    CLC", "    RTS",
              one_page("rx_block")]
    return lines


def sender(period):
    lines = ["",
             "; Send A as 8N1, %d cycles a bit. OUT0 must be at mark, and is left"
             % period,
             "; there for a whole bit before this returns. Destroys A and Y.",
             "tx_byte:", "    STA net_tx_data", "    LDA #$00",
             "    STA $4016           ; start bit", "    LDA net_tx_data"]
    lines += delay(period - 7)
    for bit in range(8):
        lines += ["    STA $4016           ; bit %d" % bit,
                  "    LSR" if bit < 7 else "    LDA #$01"]
        lines += delay(period - 6)
    lines += ["    STA $4016           ; stop bit"]
    lines += delay(period)
    lines += ["    RTS", one_page("tx_byte")]
    return lines


def one_page(name):
    return '.assert >(%s) = >(* - 1), error, "%s crosses a page"' % (name, name)


def mapper_write(value, register):
    """Five writes: the MMC1 takes a register a bit at a time."""
    lines = ["    LDA #$%02X" % value]
    for bit in range(5):
        lines += ["    STA $%04X" % register] + (["    LSR"] if bit < 4 else [])
    return lines


def common():
    """What the game's bank and the menu's must both have, byte for byte,
    at the same addresses: the code that runs while the bank under it
    changes."""
    lines = ["",
             "; The start of the reset code, and the jump between the banks. The",
             "; same bytes at the same place in both banks (from FF00): at reset",
             "; either bank may be the one at FF00, and in net_far the bank changes",
             "; under the code. Both end in the game's bank at net_boot, or go",
             "; through net_vector with A's bank in place (00 the game, 02 the menu).",
             ".macro net_common",
             "    CLD                 ; D8: the byte the INC below resets the mapper with",
             "    SEI", "    LDX #$00", "    STX $2000", "    STX $2001",
             "    INC $FF00"]
    lines += mapper_write(0x10, 0x9FFF)     # control: 32 KB of PRG, 4 KB of CHR
    lines += mapper_write(0x00, 0xFFF0)     # PRG: the game
    lines += ["    JMP net_boot", "net_far:"]
    for bit in range(5):
        lines += ["    STA $FFF0"] + (["    LSR"] if bit < 4 else [])
    lines += ["    JMP (net_vector)", ".endmacro"]
    return lines


def constants():
    names = ("FRAME_SIZE", "CHECKED", "REQUEST_GAME", "REQUEST_CONTROL", "REPLY_GAME",
             "REPLY_CONTROL", "INPUT_DELAY", "RING", "PER_FRAME", "PEER_LOST", "RX_TRIES",
             "SILENT_FRAMES", "CMD_STATUS", "CMD_HOST", "CMD_JOIN", "CMD_CANCEL", "CMD_LAST",
             "STATE_NO_WIFI", "STATE_IDLE", "STATE_HOSTING", "STATE_CONNECTING",
             "STATE_HOST", "STATE_GUEST", "STATE_FAILED")
    return ["%-16s= %d" % (name, getattr(linkrate, name)) for name in names]


def include():
    period = linkrate.PERIOD
    if linkrate.RING & (linkrate.RING - 1):
        raise ValueError("RING must be a power of two")
    lines = ["; Generated by tools/gen_link.py. Do not edit.", "",
             "LINK_PERIOD     = %d       ; CPU cycles a bit" % period]
    lines += constants()
    lines += ["", ".macro net_serial"]
    lines += receiver(period)
    lines += sender(period)
    lines += [".endmacro"]
    lines += common()
    return "\n".join(lines) + "\n"


def main(argv):
    with open(argv[1], "w") as handle:
        handle.write(include())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
