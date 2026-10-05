"""The Stick's hardware on UIFlow 2.0 firmware (MicroPython only).

UIFlow's M5 module (M5Unified underneath) already knows the board: display,
buttons, battery and power-off. This module adds the link UART, which UIFlow
leaves alone, on the pins of whichever Stick it finds. It is nes-jukebox's
(firmware/stick/nesjuke/board.py) at this link's rate.

The hat is the 8-pin proto hat with the NPN level shifter from nes-radar,
and its slots reach different pins on each board:

  slot     1    2       3    4        5    6    7       8
  S3       GND  EXT_5V  G0   G1       G8   BAT  3V3_L2  5V_IN
  Plus2    GND  5V OUT  G26  G36/G25  G0   BAT  3V3     5V IN

  S3:    TX on G8 (slot 5), RX on G1 (slot 4).
  Plus2: TX on G26 (slot 3), RX on G36 (slot 4). G36 is input-only and
         shares its pad with G25, which must stay an input.

G0 is the boot-mode strapping pin on both, and neither level-shifter stage
may touch it: held low at power-up, the Stick starts in download mode. It
sits on slot 3 of the S3 and slot 5 of the Plus2, so the TX wire is on a
different slot for each board and one hat cannot serve both.

Each NPN stage inverts, so the UART inverts TX and RX in hardware to cancel
it. A non-inverting shifter needs "invert": false in config.json.
"""

from machine import UART

import M5

from neswiki.linkrate import REPLY_SIZE, baud

LINK_UART_ID = 1
RX_BUFFER = 256     # several requests: what piles up while a fetch is busy
TX_BUFFER = 4 * REPLY_SIZE
POWER_OFF_HOLD_MS = 2000

# name: (M5.BOARD attribute, label, TX pin, RX pin)
BOARDS = {
    "s3": ("M5StickS3", "StickS3", 8, 1),
    "plus2": ("M5StickCPlus2", "StickC Plus2", 26, 36),
}


def init():
    """Start M5Unified. UIFlow's own boot does this too; calling it again is safe."""
    M5.begin()


def detect(override=None):
    """Return (label, TX pin, RX pin) for this Stick.

    override is config.json's "board": "s3" or "plus2", for a UIFlow build
    whose board id this code does not recognise.
    """
    if override is not None:
        if override not in BOARDS:
            raise ValueError("board must be s3 or plus2")
        return BOARDS[override][1:]
    found = M5.getBoard()
    for attribute, label, tx, rx in BOARDS.values():
        if found == getattr(M5.BOARD, attribute, None):
            return label, tx, rx
    raise ValueError("unknown board %s; set board in config.json" % found)


def open_link_uart(tx, rx, invert=True):
    # 2 stop bits out (the console's time to store a byte), 1 or more in.
    # At the console the line idles HIGH (mark): with an inverting shifter
    # the TX pin idles LOW, which leaves the transistor off and its pull-up
    # holding D0 high.
    return UART(
        LINK_UART_ID,
        baudrate=baud(),
        bits=8,
        parity=None,
        stop=2,
        tx=tx,
        rx=rx,
        rxbuf=RX_BUFFER,
        txbuf=TX_BUFFER,
        timeout=0,
        invert=(UART.INV_TX | UART.INV_RX) if invert else 0,
    )


class Buttons:
    """Front button A and side button B, through M5Unified's debounced
    state."""

    def poll(self):
        """Returns (A was pressed, B held long enough to power off)."""
        M5.update()
        return M5.BtnA.wasPressed(), M5.BtnB.pressedFor(POWER_OFF_HOLD_MS)


def battery_percent():
    return M5.Power.getBatteryLevel()


def power_off():
    """On battery this turns the Stick off; on USB power it stays on."""
    M5.Power.powerOff()
