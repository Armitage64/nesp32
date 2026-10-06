#!/bin/sh
# Copy the throughput test to a Stick and run it there. Its log comes back
# on this terminal; Ctrl-C stops it.
#
#   stick/run.sh [-p serial-port]
#
# The Stick must run UIFlow 2.0 with its REPL free for mpremote (UIFlow's
# boot_option 0), as the jukebox's MicroPython firmware used to leave it;
# see ../README.md, "Running it". A Stick with nesp32's firmware on it does
# not run this. This adds /flash/linktest and changes nothing else.
#
# Start build/linktest.nes on the console first, with the hat in controller
# port 2. Name the port when the FTDI test cable is plugged in as well.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
if [ "${1:-}" = "-p" ]; then
    set -- mpremote connect "$2"
else
    set -- mpremote
fi

"$@" mkdir :/flash/linktest >/dev/null 2>&1 || true    # it may be there already
"$@" cp "$HERE"/linktest/*.py :/flash/linktest/
"$@" exec "import linktest.device; linktest.device.main()"
