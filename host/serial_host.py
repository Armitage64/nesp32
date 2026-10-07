#!/usr/bin/env python3
"""A computer in place of a Stick, on the USB serial cable.

    host/serial_host.py /dev/cu.usbserial-XXXX
    host/serial_host.py /dev/cu.usbserial-XXXX --tracks ../nes-jukebox/build/tracks
    host/serial_host.py /dev/cu.usbserial-XXXX --game       # or --idle

With nes-radar's 5 V FTDI cable on controller port 2 in place of a Stick,
this answers the console with the firmware's own link and services
(build/libnesp_host, from `make host`). It is for trying a ROM on a real
console before, or without, a Stick: the setup ROM's status screen and its
link test work in full. It has not been run on a cable yet.

The Wi-Fi is make-believe. A scan finds the networks below, and a join
succeeds two seconds later unless the password is "wrong". Nothing is
joined and nothing is saved.

With --tracks it has the jukebox's music: the .jbs and .pcm files of a
directory, in the order of their names (nes-jukebox's tools/pack_tracks.py
makes one). The keys a, b and n are then the nesp32's buttons: play or
pause, the previous track, the next. Sampled sound changes the cable's
rate, as it does a nesp32's UART's.

With --game it is one end of a game for two consoles (PEER: nes-drmario's
netplay). The Wi-Fi is then this computer's own network, joined from the
start, and the other end is called, or waited for, on it: a nesp32 with
its console, or another computer with one. With --idle no other console is
needed: HOST GAME starts a game at once against an opponent who never
presses a button, which is the first thing to try on one console.

USB serial adapters hold received bytes for a latency timer before passing
them on (16 ms by default on FTDI chips), which is longer than the console
waits for a reply. Set it to 1 ms where the driver allows: on Linux,
`setserial <port> low_latency`; nes-jukebox's host/jukebox.py has the
macOS call.
"""

import argparse
import os
import select
import sys
import time

import serial

import nesp
import nesp_proto as p
import peer_net

NETWORKS = [(b"Home Network", -48, p.NESP_AUTH_PASSWORD), (b"Upstairs", -58, p.NESP_AUTH_PASSWORD),
            (b"Cafe Guest", -66, p.NESP_AUTH_OPEN), (b"Enterprise", -70, p.NESP_AUTH_OTHER)]
SCAN_SECONDS = 1.5
JOIN_SECONDS = 2.0
TX_AHEAD = 1024                 # bytes of a run handed to the driver ahead of the wire
KEYS = {"a": p.NESP_EVENT_BUTTON_A, "b": p.NESP_EVENT_BUTTON_B, "n": p.NESP_EVENT_BUTTON_POWER}


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

    # The line with framing off, and the clock (nesp.Stick): for a run of
    # RAW's, which is how the jukebox's sampled sound travels.

    def now_ms(self):
        return time.monotonic() * 1000.0

    def line_rate(self, period):
        self.serial.baudrate = (p.NESP_CPU_HZ + period // 2) // period
        self.serial.reset_input_buffer()

    def line_write(self, data):
        count = max(0, min(len(data), TX_AHEAD - self.serial.out_waiting))
        if count:
            self.serial.write(data[:count])
        return count

    def line_idle(self):
        return self.serial.out_waiting == 0


class Keys:
    """The terminal's keys one at a time, without waiting for Return, if
    there is a terminal."""

    def __init__(self):
        self.saved = None
        if sys.stdin.isatty():
            import termios
            import tty
            self.saved = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())

    def read(self):
        if self.saved is None or not select.select([sys.stdin], [], [], 0)[0]:
            return ""
        return sys.stdin.read(1)

    def close(self):
        if self.saved is not None:
            import termios
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.saved)


def tracks_in(directory):
    """The files of the jukebox's tracks in a directory, in the order of
    their names."""
    names = sorted(name for name in os.listdir(directory) if name.endswith((".jbs", ".pcm")))
    out = []
    for name in names:
        with open(os.path.join(directory, name), "rb") as handle:
            out.append(handle.read())
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("device", help="the serial port the cable is on")
    parser.add_argument("--tracks", help="a directory of .jbs and .pcm files: the jukebox's music")
    parser.add_argument("--game", action="store_true",
                        help="one end of a game for two consoles, on this computer's network")
    parser.add_argument("--idle", action="store_true",
                        help="a game for two consoles with no other: an opponent who presses nothing")
    args = parser.parse_args(argv)
    port = SerialPort(args.device)
    stick = nesp.Stick(port)
    stick.set_battery(100)
    network = None
    if args.game or args.idle:
        address = peer_net.own_address()
        if address is None and not args.idle:
            parser.error("this computer is on no network")
        stick.set_saved(b"This computer")
        stick.set_wifi(p.NESP_WIFI_JOINED, rssi=-50, address=address or bytes(4))
        network = peer_net.IdleNetwork(stick) if args.idle else peer_net.SocketNetwork(stick)
    for track in tracks_in(args.tracks) if args.tracks else ():
        stick.add_track(track)
    keys = Keys()
    scans, joins = stick.scans, stick.joins
    scan_done = join_done = None
    shown = None
    print("answering on %s at %d baud; Ctrl-C to stop" % (args.device, p.NESP_BAUD))
    try:
        while True:
            if stick.poll():
                stick.note_turnaround(int((time.monotonic() - port.heard_at) * 1e6))
            if network is not None:
                network.poll()
            now = time.monotonic()
            key = keys.read()
            if key in KEYS:
                stick.event(KEYS[key])
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
                print("\r%s v%d: %d requests, %d again, %d bytes of noise  %s  %s   "
                      % (app.decode("ascii", "replace"), version, stick.requests,
                         stick.repeats, stick.noise, stick.shown(0), stick.shown(1)),
                      end="", file=sys.stderr)
            time.sleep(0.0002)
    except KeyboardInterrupt:
        print()
    finally:
        keys.close()
        if network is not None:
            network.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
