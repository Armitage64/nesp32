#!/usr/bin/env python3
"""Save Wi-Fi settings into the Stick's UIFlow settings (NVS), from your terminal.

    python3 tools/set_wifi.py [serial-port]

Use this when M5Burner's configure step does not stick. UIFlow's boot.py
reads these settings on every start, even with "Run main.py directly"; if any
is missing it stops with ESP_ERR_NVS_NOT_FOUND and never runs main.py, which
leaves the screen blank.

The password is read with getpass (not echoed) and sent over the USB serial
link in MicroPython's raw REPL. It never touches a file, your shell history,
or a command line. Needs pyserial, which mpremote already installs.
"""

import getpass
import os
import sys

import serial

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stick_repl import BAUD, find_port, raw_exec  # noqa: E402


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else find_port()
    ssid = input("Wi-Fi network name (SSID): ").strip()
    if not ssid:
        sys.exit("No SSID given; nothing changed.")
    password = getpass.getpass("Wi-Fi password (not shown): ")
    # Every key UIFlow's startup() reads with get_str. DHCP leaves the
    # static-address fields empty.
    settings = {
        "net_mode": "WIFI",
        "ssid0": ssid,
        "pswd0": password,
        "protocol": "DHCP",
        "ip_addr": "",
        "netmask": "",
        "gateway": "",
        "dns": "",
    }
    code = (
        "import esp32\n"
        "n = esp32.NVS('uiflow')\n"
        "for k, v in %r.items():\n"
        "    n.set_str(k, v)\n"
        "n.commit()\n"
        "print('saved', len(%r), 'settings')\n"
    ) % (settings, settings)
    with serial.Serial(port, BAUD, timeout=0.2) as link:
        output, errors = raw_exec(link, code)
    if errors:
        sys.exit("The Stick reported an error:\n" + errors)
    print(output.strip())
    print("Done. Power-cycle the Stick (or run `mpremote reset`).")


if __name__ == "__main__":
    main()
