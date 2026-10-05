"""Bench helper: show what the Stick hears from the NES, and answer nothing.

    mpremote run tools/link_monitor.py

This tests the NES-to-Stick direction by itself: OUT0, the RX stage of the
level shifter, the RX pin and the baud rate. Start it, then start
build/nespedia_link.nes on the console and press Start there. With nothing
answering, the ROM sends its search again about seven times a second for
half a minute and then gives up:

    SEARCH id 1 'Nintendo Entertainment System'      (repeated)

Every 2 seconds it prints the request count and the bytes that were not
part of a request. One such byte arrives every frame, 60 a second: the
console's controller read, which is expected. If bytes arrive but nothing
decodes, it prints them in hex; a search begins 57 01. Garbage there points
at the RX stage's edges, the invert setting, or the pin.

`mpremote run` interrupts NESpedia first. Run `mpremote reset` afterwards to
go back to it. From nes-jukebox's tool of the same name.
"""

import json
import time

import M5

from neswiki import board, proto

REPORT_MS = 2000


def main():
    M5.begin()
    M5.Lcd.setRotation(1)
    M5.Lcd.fillScreen(0)
    M5.Lcd.drawString("LINK MONITOR", 4, 2)
    try:
        with open("/flash/config.json") as handle:
            config = json.load(handle)
    except OSError:
        config = {}
    label, tx, rx = board.detect(config.get("board"))
    uart = board.open_link_uart(config.get("tx", tx), config.get("rx", rx),
                                invert=config.get("invert", True))
    print("listening on %s: RX G%d" % (label, config.get("rx", rx)))
    decoder = proto.Decoder()
    requests = received = 0
    last = b""
    report_at = time.ticks_ms()
    while True:
        data = uart.read() if uart.any() else None
        if data:
            received += len(data)
            last = data
            for op, payload in decoder.feed(data):
                requests += 1
                if op == proto.OP_SEARCH and payload:
                    print("SEARCH id %d %r" % (payload[0], bytes(payload[1:]).decode()))
                elif op == proto.OP_LINE and len(payload) == 2:
                    print("LINE %d" % (payload[0] | payload[1] << 8))
                else:
                    print("op %d" % op, bytes(payload))
        now = time.ticks_ms()
        if time.ticks_diff(now, report_at) >= REPORT_MS:
            report_at = now
            print("%d requests, %d bytes, %d not part of one"
                  % (requests, received, decoder.discarded))
            if received and not requests:
                print("  last bytes:", " ".join("%02x" % byte for byte in last[-16:]))
        time.sleep_ms(1)


main()
