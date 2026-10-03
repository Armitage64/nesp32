"""Bench helper: show what the Stick hears from the NES, and answer nothing.

    mpremote run tools/link_monitor.py

This tests the NES-to-Stick direction by itself: OUT0, the RX stage of the
level shifter, the RX pin and the baud rate. Start it, then power on the NES
with build/jukebox_link.nes. With no host answering, the ROM sends one hello
and then asks for burst 0 again every 4 to 5 frames (about 13 times a second):

    HELLO
    DATA seq 0 credit 24      (repeated)

Every 16th frame the ROM reports one of its link counters instead, and those
are shown with each report line. With nothing answering, `timeouts` is the
one that climbs.

Every 2 seconds it prints the request count and the bytes that were not part
of a request. A few noise bytes when the NES powers on are normal. If bytes
arrive but nothing decodes, it prints them in hex: a request for burst 0 is
4a 00 18 f7. Garbage there points at the RX stage's edges, the invert
setting, or the pin.

`mpremote run` interrupts the jukebox first. Run `mpremote reset` afterwards
to go back to it.
"""

import json
import time

import M5

from nesjuke import board
from nesjuke.protocol import (NES_COUNTERS, OP_DATA, OP_HELLO, OP_STATS, NesCounters,
                              RequestDecoder)

REPORT_MS = 2000
SHOW_RAW = 32  # bytes to print in hex when a report period decodes nothing


def main():
    try:
        with open("/flash/config.json") as handle:
            config = json.load(handle)
    except (OSError, ValueError):
        config = {}
    board.init()
    label, tx, rx = board.detect(config.get("board"))
    tx = config.get("tx", tx)
    rx = config.get("rx", rx)
    invert = config.get("invert", True)
    uart = board.open_link_uart(tx, rx, invert=invert)
    # mpremote's soft reset leaves the screen blank; say what is running.
    M5.Lcd.setRotation(1)
    M5.Lcd.fillScreen(0x000000)
    M5.Lcd.setTextColor(0xFFB000, 0x000000)
    M5.Lcd.drawString("LINK MONITOR", 4, 4)
    M5.Lcd.drawString("output is on USB", 4, 24)
    M5.Lcd.drawString("mpremote reset to exit", 4, 44)
    print("%s: listening on G%d at %d baud, invert=%s; Ctrl-C to stop"
          % (label, rx, board.BAUD, invert))
    decoder = RequestDecoder()
    buffer = bytearray(64)
    counts = {"hello": 0, "data": 0, "other": 0}
    nes = NesCounters()
    heard = []    # the first bytes of this report period, for when nothing decodes
    decoded = 0
    last = None
    report_at = time.ticks_add(time.ticks_ms(), REPORT_MS)
    try:
        while True:
            count = uart.readinto(buffer)
            for index in range(count or 0):
                if len(heard) < SHOW_RAW:
                    heard.append(buffer[index])
                if not decoder.push(buffer[index]):
                    continue
                decoded += 1
                if decoder.op == OP_HELLO:
                    nes.hello()
                    counts["hello"] += 1
                    line = "HELLO"
                elif decoder.op == OP_DATA:
                    counts["data"] += 1
                    line = "DATA seq %d credit %d" % (decoder.seq, decoder.arg)
                elif decoder.op == OP_STATS:
                    nes.report(decoder.seq, decoder.arg)
                    continue
                else:
                    counts["other"] += 1
                    line = "BUTTON %02x" % decoder.arg
                if line != last:
                    print(line)
                    last = line
            now = time.ticks_ms()
            if time.ticks_diff(now, report_at) >= 0:
                report_at = time.ticks_add(now, REPORT_MS)
                print("requests: %d hello, %d data; noise bytes so far: %d"
                      % (counts["hello"], counts["data"], decoder.discarded))
                if nes.totals:
                    print("  NES:", " ".join("%s %d" % (name, nes.totals[name])
                                             for name in NES_COUNTERS if name in nes.totals))
                if heard and not decoded:
                    print("  nothing decoded from:", " ".join("%02x" % byte for byte in heard))
                heard = []
                decoded = 0
            time.sleep_ms(1)
    except KeyboardInterrupt:
        print("stopped")


main()
