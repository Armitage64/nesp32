#!/usr/bin/env python3
"""A computer in place of a Stick, on the 5 V USB serial cable.

    host/drnet_host.py /dev/cu.usbserial-XXXX
    host/drnet_host.py /dev/cu.usbserial-XXXX --idle

The cable is nes-radar's: the adapter's TXD to D0 and its RXD to OUT0 of
controller port 2, each through 1 kOhm, and ground. This program then
answers the console as a Stick does, with the Stick's own code
(firmware/stick/drnet/stick.py): the console's menu shows this computer's
address, HOST GAME listens on TCP port 6502, and JOIN GAME connects to
another console's Stick or computer.

--idle needs no other console: HOST GAME and JOIN GAME both start a game at
once, against an opponent who never presses a button.

Needs pyserial. Ctrl-C stops it.

Replies have to start within about 5.6 ms of the console's request, so the
USB serial driver is asked for 1 ms of receive latency (--latency-ms; an
FTDI chip's own default of 16 ms would miss every one). The status line
says how the replies are doing: `repeats` counts requests the console had
to make again.
"""

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "firmware", "stick"))
sys.path.insert(0, HERE)

from desktop import DesktopNetwork, IdleNetwork, dotted  # noqa: E402
from drnet.linkrate import (  # noqa: E402
    PORT,
    STATE_CONNECTING,
    STATE_FAILED,
    STATE_GUEST,
    STATE_HOST,
    STATE_HOSTING,
    STATE_IDLE,
    STATE_NO_WIFI,
    baud,
)
from drnet.stick import Stick  # noqa: E402

IOSSDATALAT = 0x80085400  # macOS <IOKit/serial/ioss.h>: _IOW('T', 0, unsigned long)
READ_WAIT_S = 0.001         # how long a read waits for the console
STATUS_S = 5.0
STATES = {
    STATE_NO_WIFI: "no network",
    STATE_IDLE: "idle",
    STATE_HOSTING: "hosting",
    STATE_CONNECTING: "connecting",
    STATE_HOST: "player 1",
    STATE_GUEST: "player 2",
    STATE_FAILED: "not connected",
}


def open_port(path):
    import serial  # pyserial

    port = serial.Serial(
        path,
        baudrate=baud(),
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_TWO,  # transmit; the receiver accepts 1
        timeout=READ_WAIT_S,
        write_timeout=1.0,
        xonxoff=False,
        rtscts=False,
        dsrdtr=False,
    )
    port.break_condition = False
    port.reset_input_buffer()
    port.reset_output_buffer()
    return port


def set_low_latency(port, milliseconds=1):
    """Ask the USB serial driver to hand over received bytes at once.
    Returns a word for the startup line. From nes-jukebox's host, which
    found that on macOS the value is the FTDI timer in milliseconds."""
    try:
        if sys.platform == "darwin":
            import fcntl
            import struct

            fcntl.ioctl(port.fileno(), IOSSDATALAT, struct.pack("L", milliseconds))
        else:
            port.set_low_latency_mode(True)  # Linux; other systems raise
    except (OSError, AttributeError, NotImplementedError) as error:
        return "driver default (%s)" % error
    return "%d ms requested" % milliseconds


class SerialPort:
    """The cable as the Stick's code wants a port. A read waits up to
    READ_WAIT_S for the console, which is what paces the program's loop."""

    def __init__(self, port):
        self.port = port

    def read(self):
        data = self.port.read(self.port.in_waiting or 1)
        return data or None

    def write(self, data):
        self.port.write(data)
        self.port.flush()


def status(stick, network):
    session = stick.session
    line = "%s, %d commands" % (STATES[network.state], stick.commands)
    if session is not None:
        line += ", %d ticks, %d repeats" % (session.requests - session.repeats, session.repeats)
    if network.error:
        line += " (%s)" % network.error
    return line


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("port", help="the serial cable, such as /dev/cu.usbserial-XXXX")
    parser.add_argument("--idle", action="store_true",
                        help="no other console: play against an opponent who does nothing")
    parser.add_argument("--tcp-port", type=int, default=PORT,
                        help="TCP port to listen on and connect to (default %d)" % PORT)
    parser.add_argument("--latency-ms", type=int, default=1,
                        help="USB serial receive latency to ask for; 0 leaves the driver's own")
    args = parser.parse_args(argv)

    port = open_port(args.port)
    latency = set_low_latency(port, args.latency_ms) if args.latency_ms else "driver default"
    network = IdleNetwork() if args.idle else DesktopNetwork(port=args.tcp_port)
    stick = Stick(SerialPort(port), network)
    print("%d baud on %s, receive latency %s" % (baud(), args.port, latency))
    print("this computer is at %s%s" % (
        dotted(network.address) if network.address else "no address",
        "; playing an idle opponent" if args.idle else ", TCP port %d" % args.tcp_port))
    shown = None
    shown_at = 0.0
    try:
        while True:
            stick.poll()
            now = time.monotonic()
            if network.state != shown or now - shown_at >= STATUS_S:
                if network.state != shown or stick.session is not None:
                    print(status(stick, network))
                shown, shown_at = network.state, now
    except KeyboardInterrupt:
        print()
    finally:
        network.close()
        port.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
