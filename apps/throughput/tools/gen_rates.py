#!/usr/bin/env python3
"""Write the console's cycle-timed block routines, one per rate, and the
tables the test ROM climbs the ladders by.

    tools/gen_rates.py nesp-build build/rates.inc

The first argument is where nesp32's tools/gen_proto.py put nesp_proto.py:
a run's times are the RAW service's.

For every period in tools/rates.py's two ladders this writes a routine that
receives a 256-byte block, or one that sends one, with every read of $4017
and every write of $4016 on its exact cycle. Each routine starts on its own
page and must end on it, so no branch pays the page-crossing cycle;
tests/test_thru_rates.py measures all of them on py65. Frames, at the
link's own rate, are nesp32's library's business (its nes/lib/gen_link.py).

The tables have a row for each rate to the console and then one for each
rate from it: the period, what to ask the nesp32 to send, how long to wait
after the block before asking how it went, the block routine, and the
rate's figures as text for the screen.

Receiving. Blocks to the console use two receivers of their own.

The fast receiver, for every rate down to 8 cycles a bit. Its hunt is
cpy $4017 / beq with Y holding what the port reads at a start bit, 6 cycles
a look, four looks to a loop and 7 cycles round the corner; both ways out
of it reach the byte's code 6 cycles after the read that saw the start bit,
which fell 3.1 cycles earlier on average. Its sample is asl / eor $4017
with the byte in A, 6 cycles. The byte it stores is scrambled
(rates.raw_byte), and rx_decode is the table that puts it right.

The tracking receiver, for the rates rates.tracked_receive names, has no
hunt after the first byte. Once a byte it reads the line where the start
bit's edge should be (cpx, with X holding what the port reads at a start
bit). If the line is already low it is late or on time, and takes 4 cycles
to its first sample; if still high it is early, and takes 6. So a byte is
a cycle shorter or longer than it should be, the edge stays within a cycle
or two of the look, and the nesp32's clock may differ by a cycle a byte.
At 6 cycles a bit nothing in its loop is padding. The first byte is found
by a hunt, up to 6 cycles out, which the block's preamble of $FF bytes
(one clean edge each) gives it time to work off.

Sending. A holds the byte and shifts right after each write, so a bit costs
sta + lsr, 6 cycles, and the rest is padding. Bits 1 and 2 of A reach OUT1
and OUT2 as well, which go nowhere but the expansion port. Looping to the
next byte takes 11 cycles, so below 11 cycles a bit the stop bit is longer
than the data bits (rates.from_nes_stop). At 6 cycles a bit there is no room
in the start bit to load the byte, so it is loaded first and Y, holding 0,
writes the start bit.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import rates  # noqa: E402

READ_AT = 3             # lda abs reads on its 4th cycle
FRAME_CYCLES = 29780.5  # from one vblank to the next


# Ways to pass time: (cycles, bytes, lines). pha / pla puts A back, and none
# of them touch carry, which holds a bit between a sample's lsr and ror.
PADS = ((2, 1, ["    nop"]), (3, 2, ["    bit $00"]), (7, 2, ["    pha", "    pla"]))
LOOP_BYTES = 5          # ldy #n, then dey / bne: 5n + 1 cycles


def delay(cycles, _memo={0: (0, [])}):
    """Lines of code that take exactly this many cycles, in the fewest
    bytes: a routine has to fit its loop inside a branch's reach. Uses Y
    from 12 cycles up."""
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


FAST_HUNT_TO_CODE = 6   # from the fast hunt's read to the byte's code
FAST_MEAN_EDGE = 3.1    # looks come 6, 6, 6 and 7 cycles apart
FAST_SAMPLE = rates.FASTEST_SAMPLE  # asl, eor abs


def fast_receiver(name, period):
    first = int(1.5 * period - FAST_MEAN_EDGE - FAST_HUNT_TO_CODE - READ_AT + 0.5)
    lines = ["", ".align 256",
             "; %d cycles a bit, %d baud, the fast receiver" % (period, rates.baud(period)),
             "%s:" % name, "    ldx #0", "    ldy #PORT_START", "    jmp @hunt",
             "@found:", "    nop             ; evens out the two ways here", "@byte:"]
    lines += delay(first + 1 if first == 1 else first)
    lines.append("    lda JOY2")
    for _ in range(7):
        lines += delay(period - FAST_SAMPLE)
        lines += ["    asl a", "    eor JOY2"]
    lines += ["    sta rx_buf,x    ; scrambled; rx_decode puts it right", "    inx",
              "    beq @done", "@hunt:"]
    lines += ["    cpy JOY2", "    beq @found"] * 3
    lines += ["    cpy JOY2", "    bne @hunt", "    jmp @byte", "@done:", "    rts",
              one_page(name)]
    return lines


TRACK_STORE = 15        # from the last sample to the look: sta (zp),y, iny, bne, cpx
TRACK_TO_SAMPLE = 9     # from the look to the first sample: 8 if late, 10 if early


def tracked_receiver(name, period):
    sent_at = period
    period = rates.routine_period(period)   # a rate past the last gets the last's
    gaps = rates.tracked_gaps(period)
    first = int(1.5 * period) - TRACK_TO_SAMPLE
    first += first == 1
    turn = rates.to_nes_byte(period) - TRACK_STORE - TRACK_TO_SAMPLE - first - sum(gaps)
    lines = ["", ".align 256",
             "; %d cycles a bit, %d baud, the tracking receiver%s" % (
                 sent_at, rates.baud(sent_at),
                 "" if sent_at == period else " for %d: too slow, and meant to be" % period),
             "%s:" % name, "    lda #<rx_buf", "    sta rx_ptr", "    lda #>rx_buf",
             "    sta rx_ptr + 1", "    ldy #0", "    ldx #PORT_START", "    jmp @hunt",
             "@check:"]
    lines += delay(turn)
    lines += ["    cpx JOY2        ; where the start bit's edge should be",
              "    bne @early      ; still at mark: a longer way round",
              "    nop", "@sample:"]
    lines += delay(first)
    lines.append("    lda JOY2")
    for gap in gaps:
        lines += delay(gap - FAST_SAMPLE)
        lines += ["    asl a", "    eor JOY2"]
    lines += ["    sta (rx_ptr),y  ; scrambled; rx_decode puts it right", "    iny",
              "    bne @check", "    rts", "@early:", "    jmp @sample", "@hunt:"]
    lines += ["    cpx JOY2", "    beq @sample"] * 3
    lines += ["    cpx JOY2", "    bne @hunt", "    jmp @sample", one_page(name)]
    return lines


ROOMY_HUNT_TO_CODE = 9  # the roomy hunt's ways out take 8 cycles, not 5
ROOMY_TAIL = 15         # from the last sample to the hunt's first look


def roomy_receiver(name, period):
    """The fast receiver where a bit is long. Its padding runs to loops,
    which count in Y, so the hunt compares with A; and a byte's code is
    longer than a branch reaches, so the hunt's ways out are jumps."""
    first = int(1.5 * period - FAST_MEAN_EDGE - ROOMY_HUNT_TO_CODE - READ_AT + 0.5)
    rest = max(0, int(1.5 * period) - ROOMY_TAIL)   # the hunt starts where the stop bits meet
    lines = ["", ".align 256",
             "; %d cycles a bit, %d baud, the fast receiver" % (period, rates.baud(period)),
             "%s:" % name, "    ldx #0", "    jmp @arm", "@byte:"]
    lines += delay(first + 1 if first == 1 else first)
    lines.append("    lda JOY2")
    for _ in range(7):
        lines += delay(period - FAST_SAMPLE)
        lines += ["    asl a", "    eor JOY2"]
    lines += delay(rest + 1 if rest == 1 else rest)
    lines += ["    sta rx_buf,x    ; scrambled; rx_decode puts it right", "    inx",
              "    beq @done", "@arm:", "    lda #PORT_START", "@hunt:"]
    lines += ["    cmp JOY2", "    beq @found"] * 3
    lines += ["    cmp JOY2", "    bne @hunt", "    bit $00         ; evens out the two ways out",
              "    jmp @byte", "@found:", "    nop", "    jmp @byte", "@done:", "    rts",
              one_page(name)]
    return lines


def fast_sender(name, period):
    stop = rates.from_nes_stop(period)
    lines = ["", ".align 256", "; %d cycles a bit, the byte loaded ahead" % period,
             "%s:" % name, "    ldx #0", "    ldy #0", "@byte:", "    lda tx_buf,x",
             "    sty JOY1        ; start bit"]
    lines += delay(period - 4)
    for bit in range(8):
        lines += ["    sta JOY1        ; bit %d" % bit,
                  "    lsr a" if bit < 7 else "    lda #OUT0_MARK"]
        lines += delay(period - 6)
    lines.append("    sta JOY1        ; stop bit")
    # inx, bne, the lda and the sty that starts the next byte take 13.
    lines += delay(stop - rates.FAST_FROM_NES_STOP_MIN)
    lines += ["    inx", "    bne @byte", "    rts", one_page(name)]
    return lines


def sender(name, period):
    lines = ["", ".align 256", "; %d cycles a bit" % period, "%s:" % name,
             "    ldx #0", "@byte:", "    lda #0", "    sta JOY1        ; start bit",
             "    lda tx_buf,x"]
    lines += delay(period - 8)
    for bit in range(8):
        lines += ["    sta JOY1        ; bit %d" % bit,
                  "    lsr a" if bit < 7 else "    lda #OUT0_MARK"]
        lines += delay(period - 6)
    lines.append("    sta JOY1        ; stop bit")
    # inx, bne, lda #0 and the sta that starts the next byte take 11.
    lines += delay(rates.from_nes_stop(period) - rates.FROM_NES_STOP_MIN)
    lines += ["    inx", "    bne @byte", "    rts", one_page(name)]
    return lines


def one_page(name):
    return '    .assert >(%s) = >(* - 1), error, "%s crosses a page"' % (name, name)


def byte_table(name, values, comment):
    lines = [("%s:%s; %s" % (name, " " * max(1, 23 - len(name)), comment)).rstrip(" ;")]
    for row in range(0, len(values), 16):
        lines.append("    .byte " + ", ".join("%d" % value for value in values[row:row + 16]))
    return lines


def rest_frames(cycles, proto):
    """Frames to let pass after a block before asking the nesp32 how the
    run went: what is left of the run by then, at most; the couple of
    milliseconds it takes the nesp32 to see that its last byte has left;
    and the rest RAW asks for. Waiting n frames from somewhere in one is
    only sure to be n - 1."""
    cycles += (2 + proto.NESP_RAW_REST_MS) * proto.NESP_CPU_HZ / 1000.0
    return int(-(-cycles // FRAME_CYCLES)) + 1


def to_nes_rest(period, proto):
    """The console has its block when the receiver comes back, and the run
    may go on: by a block if all went well, and by more if the line was
    low throughout and each byte took the receiver only its samples' time,
    9.5 bits. The run began as late after the console started listening as
    the nesp32's first byte is due."""
    lead, count = rates.to_nes_run(period)
    left = (lead + count) * rates.to_nes_byte(period) - rates.BLOCK * 9.5 * period
    late = (proto.NESP_RAW_START_MS - proto.NESP_RAW_SETTLE_MS) * proto.NESP_CPU_HZ / 1000.0
    return rest_frames(late + left, proto)


TEXTS = (("TEXT_SPEED", "%d BPS", 10), ("TEXT_CPU", "%d%%", 4), ("TEXT_FASTEST", "%d BYTES/S", 13))


def text_record(figures):
    """A rate's figures as the screen shows them: each a text that ends
    with a 0, at its place in the record."""
    record = b""
    for (_, form, width), figure in zip(TEXTS, figures):
        text = (form % figure).encode()
        assert len(text) <= width
        record += text.ljust(width + 1, b"\0")
    return record


def include(proto):
    assert proto.NESP_CPU_HZ == rates.CPU_HZ and proto.NESP_TO_NES_BITS == rates.TO_NES_BITS
    assert min(rates.TO_NES) >= proto.NESP_RAW_PERIOD_MIN
    to_nes, from_nes = rates.TO_NES, rates.FROM_NES
    tracked = [index for index, period in enumerate(to_nes) if rates.tracked_receive(period)]
    assert tracked == list(range(tracked[0], len(to_nes)))      # one compare finds them
    lines = ["; Generated by tools/gen_rates.py. Do not edit.", "",
             "RX_COUNT = %d          ; rates to the console" % len(to_nes),
             "TX_COUNT = %d          ; rates from it; their rows come after the others'"
             % len(from_nes),
             "BLOCK = %d" % rates.BLOCK,
             "PREAMBLE = %d           ; bytes of a block the tracking receiver settles on"
             % rates.PREAMBLE,
             "PORT_IDLE = $%02X       ; what JOY2 reads with the line at rest" % rates.PORT_IDLE,
             "PORT_START = $%02X      ; and at a start bit" % (rates.PORT_IDLE | 1)]
    offset = 0
    for name, _, width in TEXTS:
        lines.append("%s = %d" % (name, offset))
        offset += width + 1
    lines += ["", '.segment "RATES"']
    for index, period in enumerate(to_nes):
        name = "rx_block_%d" % index
        lines += (tracked_receiver(name, period) if rates.tracked_receive(period)
                  else roomy_receiver(name, period) if rates.roomy(period)
                  else fast_receiver(name, period))
    for index, period in enumerate(from_nes):
        name = "tx_block_%d" % index
        lines += (fast_sender(name, period) if rates.fast_send(period)
                  else sender(name, period))
    lines += ["", '.segment "RODATA"']
    decode = [0] * 256
    for byte in range(256):
        decode[rates.raw_byte(byte)] = byte
    lines.append("rx_decode:              ; the byte for what the receivers stored")
    for row in range(0, 256, 16):
        lines.append("    .byte " + ", ".join("$%02X" % value for value in decode[row:row + 16]))

    runs = [rates.to_nes_run(period) for period in to_nes]
    lines += [""]
    lines += byte_table("rate_period", list(to_nes) + list(from_nes), "CPU cycles a bit")
    lines += byte_table("rate_lead", [lead for lead, _ in runs],
                        "to the console only: bytes of $FF first, which are not checked")
    lines += byte_table("rate_count_lo", [count & 0xFF for _, count in runs],
                        "and bytes of the pattern after them")
    lines += byte_table("rate_count_hi", [count >> 8 for _, count in runs], "")
    lines += byte_table("rate_rest", [to_nes_rest(period, proto) for period in to_nes]
                        + [rest_frames(0, proto)] * len(from_nes),
                        "frames after a block before asking how it went")
    blocks = (["rx_block_%d" % index for index in range(len(to_nes))]
              + ["tx_block_%d" % index for index in range(len(from_nes))])
    lines += ["block_lo: .lobytes " + ", ".join(blocks),
              "block_hi: .hibytes " + ", ".join(blocks)]
    records = ([text_record(rates.to_nes_figures(period)) for period in to_nes]
               + [text_record(rates.from_nes_figures(period)) for period in from_nes])
    names = ["rate_text_%d" % index for index in range(len(records))]
    lines += ["rate_text_lo: .lobytes " + ", ".join(names),
              "rate_text_hi: .hibytes " + ", ".join(names)]
    for name, record in zip(names, records):
        lines.append("%s: .byte %s" % (name, ", ".join("$%02X" % byte for byte in record)))
    return "\n".join(lines) + "\n"


def main(argv):
    sys.path.insert(0, os.path.abspath(argv[1]))
    import nesp_proto

    with open(argv[2], "w") as handle:
        handle.write(include(nesp_proto))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
