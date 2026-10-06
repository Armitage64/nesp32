"""The throughput test on a Stick running UIFlow 2.0 (MicroPython).

    stick/run.sh            copies this package to the Stick and runs it

This is the only module that touches the hardware: the link UART, whose
rate changes between a command and a block, the screen and button A. The
pins are the hat's on each board (nesp32's firmware/main/board.h has the
same ones), and /flash/config.json overrides them.
"""

import gc
import json
import sys
import time

from machine import UART

import M5

from linktest import VERSION
from linktest.rates import CONTROL, TO_NES_BITS, baud
from linktest.tester import Link, Session

CONFIG_PATH = "/flash/config.json"
LINK_UART_ID = 1
BUFFER = 1024                   # a block is 256 bytes; both buffers hold one

# M5.BOARD attribute, label, TX pin, RX pin.
BOARDS = {
    "s3": ("M5StickS3", "StickS3", 8, 1),
    "plus2": ("M5StickCPlus2", "StickC Plus2", 26, 36),
}

BLACK = 0x000000
GREEN = 0x00FF40
GREY = 0x8C8C8C
RED = 0xFF3030
WHITE = 0xFFFFFF
BRIGHTNESS = 96
WIDTH = 240
ROW_TOP = 22
ROW_HEIGHT = 18
VALUE_X = 62
ROWS = ("state", "rx", "tx", "last", "error")
LABELS = {"state": "STATE", "rx": "TO NES", "tx": "TO STICK", "last": "LAST",
          "error": ""}


def detect(override=None):
    """(label, TX pin, RX pin) for this Stick, or for config.json's board."""
    if override is not None:
        if override not in BOARDS:
            raise ValueError("board must be s3 or plus2")
        return BOARDS[override][1:]
    found = M5.getBoard()
    for attribute, label, tx, rx in BOARDS.values():
        if found == getattr(M5.BOARD, attribute, None):
            return label, tx, rx
    raise ValueError("unknown board %s; set board in config.json" % found)


class UartPort:
    """The link UART as tester.Link wants it. Opens at the control rate."""

    def __init__(self, tx, rx, invert=True):
        # Each NPN stage of the hat inverts, and the UART inverts back.
        self.invert = (UART.INV_TX | UART.INV_RX) if invert else 0
        self.baud = baud(CONTROL)
        self.uart = UART(LINK_UART_ID, baudrate=self.baud, bits=8, parity=None, stop=2,
                         tx=tx, rx=rx, rxbuf=BUFFER, txbuf=BUFFER, timeout=0,
                         invert=self.invert)
        self.origin = time.ticks_ms()

    def _drain(self):
        if hasattr(self.uart, "flush"):
            self.uart.flush()

    def set_baud(self, rate):
        if rate == self.baud:
            return
        self._drain()
        # Everything is named again: some builds put back the default for
        # whatever init is not given, and the default is not inverted.
        self.uart.init(baudrate=rate, bits=8, parity=None, stop=2, timeout=0,
                       invert=self.invert)
        self.baud = rate

    def write(self, data):
        self.uart.write(data)
        # write only queues the bytes. Wait out the time they take on the
        # wire, for a build whose flush returns early or is missing.
        time.sleep_ms(len(data) * TO_NES_BITS * 1000 // self.baud + 2)
        self._drain()

    def read(self, count, timeout_ms):
        uart = self.uart
        data = b""
        started = time.ticks_ms()
        while True:
            chunk = uart.read(count - len(data))
            if chunk:
                data += chunk
                if len(data) >= count:
                    return data
            elif time.ticks_diff(time.ticks_ms(), started) >= timeout_ms:
                return data
            else:
                time.sleep_ms(1)

    def discard(self):
        while self.uart.any():
            self.uart.read()

    def sleep_ms(self, duration):
        time.sleep_ms(duration)

    def ticks_ms(self):
        return time.ticks_diff(time.ticks_ms(), self.origin)


class Screen:
    """Rows of label and value on the 240 x 135 panel. A row is painted
    when its text changes, which is always between blocks."""

    def __init__(self):
        self.lcd = M5.Lcd
        self.fields = {name: "" for name in ROWS}
        self.lcd.setRotation(1)
        self.lcd.setBrightness(BRIGHTNESS)
        self.lcd.fillScreen(BLACK)

    def header(self, board):
        lcd = self.lcd
        lcd.setFont(lcd.FONTS.Montserrat14)
        lcd.setTextColor(GREEN, BLACK)
        lcd.drawString("LINK TEST", 4, 2)
        lcd.setFont(lcd.FONTS.Montserrat12)
        lcd.setTextColor(GREY, BLACK)
        lcd.drawString(board, 112, 4)
        lcd.drawLine(0, ROW_TOP - 3, WIDTH - 1, ROW_TOP - 3, GREEN)

    def set(self, **fields):
        for name, value in fields.items():
            value = str(value)
            if self.fields[name] != value:
                self.fields[name] = value
                self._draw(name)

    def _draw(self, name):
        lcd = self.lcd
        y = ROW_TOP + ROWS.index(name) * ROW_HEIGHT
        label = LABELS[name]
        lcd.fillRect(0, y, WIDTH, ROW_HEIGHT, BLACK)
        lcd.setFont(lcd.FONTS.Montserrat12)
        if label:
            lcd.setTextColor(GREY, BLACK)
            lcd.drawString(label, 4, y + 2)
        lcd.setTextColor(RED if name == "error" else WHITE, BLACK)
        lcd.drawString(self.fields[name], VALUE_X if label else 4, y + 2)


def load_config():
    try:
        with open(CONFIG_PATH) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def idle():
    """Between blocks, when nothing is on the wire."""
    M5.update()
    gc.collect()


def main():
    M5.begin()
    screen = Screen()
    try:
        config = load_config()
        label, tx, rx = detect(config.get("board"))
        tx = config.get("tx", tx)
        rx = config.get("rx", rx)
        screen.header(label)
        port = UartPort(tx, rx, invert=config.get("invert", True))
        print("Link test %s on %s: TX G%d, RX G%d, commands at %d bps"
              % (VERSION, label, tx, rx, baud(CONTROL)))
        link = Link(port, idle=idle)
        again = False
        while True:
            # Each run waits for button A or the controller's Start.
            Session(link, display=screen, log=print, button=M5.BtnA.wasPressed).run(again)
            again = True
            print("done; Ctrl-C stops")
    except KeyboardInterrupt:
        print("stopped")
    except Exception as error:
        sys.print_exception(error)
        screen.set(state="ERROR", error="%s: %s" % (type(error).__name__, error))
