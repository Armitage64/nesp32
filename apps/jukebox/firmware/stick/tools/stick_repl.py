#!/usr/bin/env python3
"""Run MicroPython code on the Stick without a soft reset.

    python3 tools/stick_repl.py [--port PORT] [--reset] CODE

mpremote soft-resets the Stick when a session starts, which on UIFlow reruns
boot.py; with boot_option 1 that starts the UIFlow launcher, which then holds
the REPL, and mpremote fails with "could not enter raw repl". This helper
interrupts whatever is running and uses the plain raw REPL instead, so it
works from the launcher, from the jukebox, or from an idle prompt.

Copied from nes-radar's firmware/stick_s3/tools.

--reset restarts the Stick after the code runs. Exit status is non-zero if
the code raised. Needs pyserial, which mpremote already installs.
"""

import argparse
import glob
import sys
import time

import serial

BAUD = 115200


def find_port():
    # The StickS3's native USB shows up as usbmodem (macOS) or ttyACM (Linux).
    # The Plus2's USB serial chip shows up as usbserial or wchusbserial, as
    # does the FTDI test cable, so with both attached the port must be named.
    ports = sorted(glob.glob("/dev/cu.usbmodem*") + glob.glob("/dev/cu.usbserial-*")
                   + glob.glob("/dev/cu.wchusbserial*")
                   + glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
    if len(ports) != 1:
        sys.exit("Found %d serial ports %s; pass the Stick's port." % (len(ports), ports))
    return ports[0]


def read_until(link, marker, timeout=10.0):
    data = b""
    end = time.time() + timeout
    while time.time() < end:
        data += link.read(256)
        if marker in data:
            return data
    raise TimeoutError("no response from the Stick (got %r)" % data[-80:])


def raw_exec(link, code):
    """Run code in MicroPython's raw REPL; return (stdout, stderr)."""
    link.write(b"\r\x03\x03")
    time.sleep(0.3)
    link.reset_input_buffer()
    link.write(b"\r\x01")
    read_until(link, b"raw REPL; CTRL-B to exit\r\n>")
    link.write(code.encode("utf-8") + b"\x04")
    # Reply: "OK", stdout, 0x04, stderr, 0x04, ">" -- possibly in one read.
    reply = read_until(link, b"\x04>")
    link.write(b"\x02")
    if not reply.startswith(b"OK"):
        raise RuntimeError("the Stick did not accept the code: %r" % reply[:80])
    output, errors = reply[2:reply.rindex(b"\x04>")].split(b"\x04", 1)
    return output.decode(errors="replace"), errors.decode(errors="replace")


def reset(link):
    """Restart the Stick. The connection drops, so nothing is read back."""
    link.write(b"\r\x03\x03")
    time.sleep(0.3)
    link.write(b"\r\x01")
    time.sleep(0.2)
    link.write(b"import machine\nmachine.reset()\n\x04")
    time.sleep(0.5)


def main():
    parser = argparse.ArgumentParser(description="Run code on the Stick without a soft reset.")
    parser.add_argument("--port", help="serial port (found automatically if one)")
    parser.add_argument("--reset", action="store_true", help="restart the Stick afterwards")
    parser.add_argument("code", help="MicroPython code to run")
    args = parser.parse_args()
    with serial.Serial(args.port or find_port(), BAUD, timeout=0.2) as link:
        output, errors = raw_exec(link, args.code)
        if output:
            print(output, end="" if output.endswith("\n") else "\n")
        if errors:
            print(errors, file=sys.stderr, end="")
            sys.exit(1)
        if args.reset:
            reset(link)


if __name__ == "__main__":
    main()
