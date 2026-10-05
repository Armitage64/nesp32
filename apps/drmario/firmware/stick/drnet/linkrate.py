"""The numbers both ends of the link must agree on.

tools/gen_link.py builds the console's serial routines and constants from
these, and the Stick opens its UART at baud(PERIOD), so the two sides cannot
disagree.

A rate is a whole number of NES CPU cycles per bit, so the console's
bit-banged routines hit every bit exactly. 21 cycles is 85227 baud, the rate
nes-wiki runs at, and well inside what nes-jukebox's throughput test passed
on hardware in both directions.
"""

CPU_HZ = 1789773                # NTSC: 21.477272 MHz / 12
PERIOD = 21                     # cycles a bit, both ways
TO_NES_BITS = 11                # the Stick sends 8N2
TO_STICK_BITS = 10              # the console sends 8N1

FRAME_SIZE = 8                  # every request and every reply
CHECKED = FRAME_SIZE - 2        # bytes the two check bytes cover

# The first byte of a frame says what it is.
REQUEST_GAME = 0x47             # 'G': a tick's buttons, console to Stick
REQUEST_CONTROL = 0x43          # 'C': the menu's commands
REPLY_GAME = 0x5A
REPLY_CONTROL = 0xA5

# A button press is used INPUT_DELAY ticks after the frame it was read in,
# on both consoles. It is the time the press has to cross to the other one.
INPUT_DELAY = 3
RING = 8                        # ticks of buttons the console keeps, each way
PER_FRAME = 2                   # ticks of buttons a frame can carry

# A game reply's fourth byte: how many ticks it carries, and in the high
# nibble what has become of the other console.
PEER_OK = 0x00
PEER_LOST = 0x10

# The menu's commands, a control request's second byte. JOIN carries the
# address to join in the four bytes after it.
CMD_STATUS = 0                  # only asks
CMD_HOST = 1                    # wait for the other Stick to connect
CMD_JOIN = 2                    # connect to a Stick that is waiting
CMD_CANCEL = 3                  # drop whatever connection there is
CMD_LAST = 4                    # asks for the address last joined

# A control reply's second byte. The four after it are this Stick's own
# address, or for CMD_LAST the one last joined (zeros if none).
STATE_NO_WIFI = 0
STATE_IDLE = 1
STATE_HOSTING = 2               # waiting for the other Stick
STATE_CONNECTING = 3
STATE_HOST = 4                  # connected: this console is player 1
STATE_GUEST = 5                 # connected: this console is player 2
STATE_FAILED = 6                # the last JOIN did not connect

PORT = 6502                     # TCP, on the Stick that hosts

# How long the console waits for a reply's first byte, in passes of 256
# looks of 13 cycles: 1.86 ms each.
RX_TRIES = 3
# Frames in a row with no tick before the console gives the session up.
SILENT_FRAMES = 240


def baud(period=PERIOD):
    return (CPU_HZ + period // 2) // period


def checks(data):
    """The two check bytes of a frame's first CHECKED bytes: a running sum,
    and a running sum of that."""
    low = high = 0
    for byte in data:
        low = (low + byte) & 0xFF
        high = (high + low) & 0xFF
    return low, high
