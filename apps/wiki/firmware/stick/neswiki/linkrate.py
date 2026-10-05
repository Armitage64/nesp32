"""The numbers both ends of the link must agree on.

tools/gen_link.py builds the console's serial routines from PERIOD, and the
Stick opens its UART at baud(PERIOD), so the two sides cannot disagree.

A rate is a whole number of NES CPU cycles per bit, so the console's
bit-banged routines hit every bit exactly. 21 cycles is 85227 baud: on the
ladder both directions passed on hardware in nes-jukebox's throughput test,
and the slowest of its rates at which a whole line still fits in the part
of a frame left under the header (PLAN.md, decision 2).
"""

CPU_HZ = 1789773                # NTSC: 21.477272 MHz / 12
PERIOD = 21                     # cycles a bit, both ways
TO_NES_BITS = 11                # the Stick sends 8N2
TO_STICK_BITS = 10              # the console sends 8N1

COLUMNS = 28                    # characters in a line of text
HEADER_SIZE = 6                 # marker, state, line (2), total (2)
REPLY_SIZE = HEADER_SIZE + COLUMNS + 2  # and the CRC: always 36 bytes
EARLY_LINES = 28                # lines laid out before an article is offered
# The Stick lays out an article only this far ahead of the last line the
# console has asked for: it stops FILL_HIGH lines ahead, two pages, and
# starts again when the console has read to within FILL_LOW, one page. A
# page is 22 lines.
FILL_LOW = 22
FILL_HIGH = 44
QUERY_MAX = 30                  # characters in a search: the default has 29


def baud(period=PERIOD):
    return (CPU_HZ + period // 2) // period
