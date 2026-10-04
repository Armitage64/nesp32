#!/bin/sh
# Copy the throughput test to a Stick and run it there. Its log comes back
# on this terminal; Ctrl-C stops it.
#
#   stick/run.sh [-p serial-port]
#
# The Stick must already run the jukebox (../firmware/stick/tools/deploy.sh):
# that is what sets UIFlow to leave the REPL free for mpremote. This adds
# /flash/linktest and changes nothing else, so the jukebox is back after
# `mpremote reset`.
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
