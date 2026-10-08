#!/usr/bin/env python3
"""Write the console's cycle-timed serial routines for the link's rate.

    nes/lib/gen_link.py build build/link.inc [--timeout] [--pack]

The first argument is where tools/gen_proto.py put nesp_proto.py. The link
runs at NESP_PERIOD CPU cycles a bit, and the Stick's UART is set from the
same number. This writes, for that rate:

    nesp_rx_frame   receive one reply into nesp_rx, however long it says it is
    nesp_rx_bytes   receive A bytes into nesp_rx, for a short reply: any
                    number but NESP_HEADER, at which the other works out a
                    length
    nesp_tx_byte    send A as 8N1
    nesp_crc_table_hi, _lo      the CRC a byte at a time, for a ROM that
                                defines NESP_CRC_TABLE

Each routine sits on a page of its own and must end on it, so no branch pays
the page-crossing cycle; tests/test_link_timing.py measures every read of
$4017 and write of $4016 on py65. nesp.inc includes the file, after it has
named the zero page the routines use: their timing counts on those names
being zero page.

With --pack nothing is aligned, for a ROM with one page to spare and no
more (nes-drmario's game fills its cartridge): its linker configuration
puts RXTX at the start of a page, and the sender follows the receiver on
it. The file still says so if either crosses a page.

The generators and the padding are nes-wiki's and nes-drmario's
(tools/gen_link.py in each), which have them from nes-jukebox. What is new
is that a frame's length is not fixed.

Receiving. t0 is the cycle on which the hunt's lda read the start bit. The
hunt reads every HUNT_PASS cycles, so the edge fell 0 to HUNT_PASS cycles
before t0, half that on average, and data bit k's center is
t0 - HUNT_PASS / 2 + (1.5 + k) * period.

A reply is a header of NESP_HEADER bytes, whose last is the payload's
length, then the payload and two check bytes. The routine counts to the end
of the header, and there works out where the frame ends: the length, cut
to NESP_RX_MASK so that no reply can run past the buffer, and the
overhead. That is the one byte after which the hunt starts later than after
the others, and it still starts inside the two stop bits the Stick sends.
A length that had to be cut was wrong, and the frame then fails its checks.

Two receivers, for the two places an exchange can be made:

    default     no timeout; the caller's NMI is one (nesp_nmi_hook). The
                hunt is 9 cycles a look. X counts the bytes.
    --timeout   for an exchange made inside the NMI, where nothing else can
                end it. The wait counts its looks, 13 cycles each: X counts
                256 of them and nesp_tries counts those. Y counts the bytes.
                Carry is set if the wait ran out.

Sending. A holds the byte and shifts right after each write, so a bit costs
sta + lsr, 6 cycles, and the rest is padding. Bits 1 and 2 of A reach OUT1
and OUT2 as well, which go nowhere but the expansion port. The stop bit is
held for a whole bit before the routine returns, and the caller's loop makes
it longer, which a UART does not mind.
"""

import os
import sys

READ_AT = 3             # lda abs reads on its 4th cycle
SAMPLE = 11             # lda abs, lsr, ror zp

# Ways to pass time: (cycles, bytes, lines). pha / pla puts A back, and none
# of them touch carry, which holds a bit between a sample's lsr and ror.
PADS = ((2, 1, ["    nop"]), (3, 2, ["    bit $00"]), (7, 2, ["    pha", "    pla"]))
LOOP_BYTES = 5          # ldy #n, then dey / bne: 5n + 1 cycles


class Shape:
    """What differs between the two receivers."""

    def __init__(self, timeout):
        self.timeout = timeout
        # Cycles from one of the hunt's reads to the next, and from the read
        # that saw the start bit to the first instruction of the byte's code.
        if timeout:
            self.hunt_pass = 13         # lda, lsr, bcs, dex, bne
            self.hunt_to_code = 6       # lsr, bcs taken
            self.index = "y"
            self.rewind = 2             # ldx #0 before each hunt
        else:
            self.hunt_pass = 9          # lda, lsr, bcc
            self.hunt_to_code = 8       # lsr, bcc not taken, jmp
            self.index = "x"
            self.rewind = 0
        self.mean_edge = self.hunt_pass / 2
        # From a byte's last sample to the hunt's next read: the rest of the
        # lda, lsr, ror, lda, eor, sta abs+index, in?, cp? zp, bne taken.
        self.tail = 1 + 2 + 5 + 3 + 2 + 5 + 2 + 3 + 3 + self.rewind + READ_AT
        # And after the header's last byte: bne not taken, cp? #, bne not
        # taken, lda abs, and #, adc #, sta zp.
        self.header_tail = self.tail - 3 + 2 + 2 + 2 + 4 + 2 + 2 + 3


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
                            ["    ldy #%d" % loops, ":   dey", "    bne :-"] + tail[1]))
        memo[cycles] = min(choices, key=lambda choice: choice[0])
    return memo[cycles]


def first_sample_delay(period, shape):
    return int(1.5 * period - shape.mean_edge - shape.hunt_to_code - READ_AT + 0.5)


def check_tails(period, shape, to_nes_bits):
    """The hunt for the next byte must start after the last data bit is
    over, or a 0 there is taken for a start bit; and not so long after the
    next start bit has begun that the samples that follow are off."""
    data_over = 0.5 * period + shape.mean_edge
    next_start = (to_nes_bits - 8.5) * period
    if shape.tail <= data_over:
        raise ValueError("at %d cycles a bit the hunt starts inside the last data bit" % period)
    # A hunt that starts d cycles into the start bit sees it at once, as if
    # the edge had fallen d cycles before its read: fine up to hunt_pass,
    # which is the most the samples allow for.
    if shape.header_tail > next_start - shape.mean_edge + shape.hunt_pass:
        raise ValueError("at %d cycles a bit the hunt after the header is late" % period)


def samples(period, shape, use_y):
    lines = []
    for bit in range(8):
        lines += delay(first_sample_delay(period, shape) if bit == 0 else period - SAMPLE,
                       use_y=use_y)
        lines += ["    lda JOY2", "    lsr a", "    ror nesp_rx_data"]
    return lines


def store(shape):
    """A byte into the frame, and whether that was the frame's last. Falls
    through with the frame's end newly worked out, after the header."""
    index = shape.index
    return ["    lda nesp_rx_data", "    eor #$FF            ; the port inverts D0",
            "    sta a:nesp_rx,%s" % index, "    in%s" % index,
            "    cp%s nesp_rx_end" % index, "    bne @next",
            "    cp%s #NESP_HEADER" % index, "    bne @done",
            "    lda a:nesp_rx + NESP_HEADER - 1     ; the payload's length",
            "    and #NESP_RX_MASK",
            "    adc #NESP_OVERHEAD - 1  ; and the carry the compare left",
            "    sta nesp_rx_end"]


def receiver(period, baud, to_nes_bits):
    shape = Shape(timeout=False)
    check_tails(period, shape, to_nes_bits)
    lines = ["", ".align 256",
             "; Receive a reply into nesp_rx. %d cycles a bit, %d baud." % (period, baud),
             "; There is no timeout; the caller's NMI is one. Carry clear, as the",
             "; other receiver leaves it for a frame that came. Destroys A, X and Y.",
             ".proc nesp_rx_frame", "    lda #NESP_HEADER",
             "    sta nesp_rx_end     ; nesp_rx_bytes comes in here",
             "    ldx #0", "    jmp @hunt", "@byte:"]
    lines += samples(period, shape, use_y=True)
    lines += store(shape)
    lines += ["@next:",
              "@hunt:                      ; the tests skip ahead while this sees mark",
              "    lda JOY2", "    lsr a", "    bcc @hunt", "    jmp @byte",
              "@done:", "    clc", "    rts", ".endproc", one_page("nesp_rx_frame"),
              RX_BYTES]
    return lines


def timeout_receiver(period, baud, to_nes_bits):
    shape = Shape(timeout=True)
    check_tails(period, shape, to_nes_bits)
    lines = ["", ".align 256",
             "; Receive a reply into nesp_rx. %d cycles a bit, %d baud." % (period, baud),
             "; nesp_tries is how long to wait for a start bit, in passes of 256",
             "; looks; it is not wound up again between bytes. Carry clear if the",
             "; frame came, set if the wait ran out. Destroys A, X and Y.",
             ".proc nesp_rx_frame", "    lda #NESP_HEADER",
             "    sta nesp_rx_end     ; nesp_rx_bytes comes in here",
             "    ldy #0", "    ldx #0",
             "@hunt:                      ; the tests skip ahead while this sees mark",
             "    lda JOY2", "    lsr a", "    bcs @byte", "    dex", "    bne @hunt",
             "    dec nesp_tries", "    bne @hunt", "    sec", "    rts", "@byte:"]
    lines += samples(period, shape, use_y=False)
    lines += store(shape)
    lines += ["@next:", "    ldx #0", "    jmp @hunt", "@done:", "    clc", "    rts",
              ".endproc", one_page("nesp_rx_frame"), RX_BYTES]
    return lines


# Past the lda # that a whole frame's receiver begins with.
RX_BYTES = "nesp_rx_bytes = nesp_rx_frame + 2"


def sender(period):
    lines = ["", ".align 256",
             "; Send A as 8N1, %d cycles a bit. OUT0 must be at mark, and is left"
             % period,
             "; there for a whole bit before this returns. Destroys A and Y.",
             ".proc nesp_tx_byte", "    sta nesp_tx_data", "    lda #0",
             "    sta JOY1            ; start bit", "    lda nesp_tx_data"]
    lines += delay(period - 7)
    for bit in range(8):
        lines += ["    sta JOY1            ; bit %d" % bit,
                  "    lsr a" if bit < 7 else "    lda #OUT0_MARK"]
        lines += delay(period - 6)
    lines += ["    sta JOY1            ; stop bit"]
    lines += delay(period)
    lines += ["    rts", ".endproc", one_page("nesp_tx_byte")]
    return lines


def one_page(name):
    return '.assert >(%s) = >(* - 1), error, "%s crosses a page"' % (name, name)


def crc_table(poly):
    """T[i]: the CRC register after i << 8 has been through eight rounds.
    Per byte the console does index = crc_hi ^ byte; crc_hi = crc_lo ^
    hi[index]; crc_lo = lo[index]."""
    entries = []
    for index in range(256):
        crc = index << 8
        for _ in range(8):
            crc = ((crc << 1) ^ poly) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
        entries.append(crc)
    return entries


def include(proto, timeout=False, pack=False):
    period = proto.NESP_PERIOD
    lines = ["; Generated by nes/lib/gen_link.py. Do not edit.", "",
             '.segment "RXTX"']
    make = timeout_receiver if timeout else receiver
    lines += make(period, proto.NESP_BAUD, proto.NESP_TO_NES_BITS)
    lines += sender(period)
    if pack:
        lines = [line for line in lines if line != ".align 256"]
    lines += ["", ".ifdef NESP_CRC_TABLE", '.segment "RODATA"']
    entries = crc_table(proto.NESP_CRC_POLY)
    for name, part in (("nesp_crc_table_hi", lambda value: value >> 8),
                       ("nesp_crc_table_lo", lambda value: value & 0xFF)):
        lines.append("%s:" % name)
        for row in range(0, 256, 16):
            lines.append("    .byte " + ", ".join("$%02X" % part(value)
                                                  for value in entries[row:row + 16]))
    lines += [".endif"]
    return "\n".join(lines) + "\n"


def main(argv):
    sys.path.insert(0, os.path.abspath(argv[1]))
    import nesp_proto

    with open(argv[2], "w") as handle:
        handle.write(include(nesp_proto, timeout="--timeout" in argv[3:],
                             pack="--pack" in argv[3:]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
