#!/usr/bin/env python3
"""A computer in place of a Stick, on the USB serial cable.

    host/serial_host.py /dev/cu.usbserial-XXXX

With nes-radar's 5 V FTDI cable on controller port 2 in place of a Stick,
this answers the console with the firmware's own link and services
(build/libnesp_host, from `make host`). It is for trying a ROM on a real
console before, or without, a Stick: the setup ROM's status screen and its
link test work in full. It has not been run on a cable yet.

The Wi-Fi is make-believe. A scan finds the networks below, and a join
succeeds two seconds later unless the password is "wrong". Nothing is
joined and nothing is saved.

USB serial adapters hold received bytes for a latency timer before passing
them on (16 ms by default on FTDI chips), which is longer than the console
waits for a reply. Set it to 1 ms where the driver allows: on Linux,
`setserial <port> low_latency`; nes-jukebox's host/jukebox.py has the
macOS call.
"""

import argparse
import sys
import time

import serial

import nesp
import nesp_proto as p

NETWORKS = [(b"Home Network", -48, p.NESP_AUTH_PASSWORD), (b"Upstairs", -58, p.NESP_AUTH_PASSWORD),
            (b"Cafe Guest", -66, p.NESP_AUTH_OPEN), (b"Enterprise", -70, p.NESP_AUTH_OTHER)]
SCAN_SECONDS = 1.5
JOIN_SECONDS = 2.0


class SerialPort:
    """The cable as nesp.Stick wants a port."""

    def __init__(self, device):
        self.serial = serial.Serial(device, p.NESP_BAUD, bytesize=8, parity="N",
                                    stopbits=2, timeout=0)
        self.heard_at = 0.0

    def read(self):
        data = self.serial.read(256)
        if data:
            self.heard_at = time.monotonic()
        return data or None

    def write(self, data):
        self.serial.write(data)
        self.serial.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("device", help="the serial port the cable is on")
    args = parser.parse_args(argv)
    port = SerialPort(args.device)
    stick = nesp.Stick(port)
    stick.set_battery(100)
    scans, joins = stick.scans, stick.joins
    scan_done = join_done = None
    shown = None
    print("answering on %s at %d baud; Ctrl-C to stop" % (args.device, p.NESP_BAUD))
    try:
        while True:
            if stick.poll():
                stick.note_turnaround(int((time.monotonic() - port.heard_at) * 1e6))
            now = time.monotonic()
            if stick.scans != scans:
                scans, scan_done = stick.scans, now + SCAN_SECONDS
            if scan_done is not None and now >= scan_done:
                scan_done = None
                stick.scan_set(NETWORKS)
                stick.scan_finish()
            if stick.joins != joins:
                joins, join_done = stick.joins, now + JOIN_SECONDS
            if join_done is not None and now >= join_done:
                join_done = None
                if stick.joined_password == b"wrong":
                    stick.set_wifi(p.NESP_WIFI_FAILED, why=p.NESP_WHY_PASSWORD)
                else:
                    stick.set_wifi(p.NESP_WIFI_JOINED, rssi=-50, address=(192, 168, 1, 77))
            if shown is None or now - shown >= 1.0:     # once a second
                shown = now
                app, version = stick.app
                print("\r%s v%d: %d requests, %d again, %d bytes of noise   "
                      % (app.decode("ascii", "replace"), version, stick.requests,
                         stick.repeats, stick.noise), end="", file=sys.stderr)
            time.sleep(0.0002)
    except KeyboardInterrupt:
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
