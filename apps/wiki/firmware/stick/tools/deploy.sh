#!/bin/sh
# Copy NESpedia onto a Stick running UIFlow 2.0 firmware (M5StickS3, or the
# M5StickC Plus2).
#
#   tools/deploy.sh [-p serial-port]
#
# Needs mpremote 1.24 or later (pip install mpremote). mpremote finds a
# single attached board by itself; name the port when the FTDI test cable is
# plugged in as well. A file the Stick already holds is not copied again.
#
# What it changes on the Stick:
#   - copies neswiki/ and main.py (and config.json if present here) into
#     /flash, UIFlow's user filesystem;
#   - saves UIFlow's existing /flash/main.py as /flash/main_uiflow.py the
#     first time, so tools/restore_uiflow.sh can put it back;
#   - sets UIFlow's boot_option to 0, so the Stick runs NESpedia at
#     power-on instead of the UIFlow launcher.
#
# Wi-Fi is the network saved in UIFlow's own settings: M5Burner's configure
# step, or tools/set_wifi.py. Nothing here touches it.
#
# From nes-jukebox's firmware/stick/tools/deploy.sh.
set -eu

HERE=$(cd "$(dirname "$0")/.." && pwd)
PORT=auto
if [ "${1:-}" = "-p" ]; then
    PORT=$2
    shift 2
fi

if [ "$PORT" = auto ]; then
    set -- mpremote
    REPL_PORT=""
else
    set -- mpremote connect "$PORT"
    REPL_PORT=$PORT
fi

# First step without a soft reset (tools/stick_repl.py): it works even from
# the UIFlow launcher, which holds the REPL. Setting boot_option 0 here means
# every mpremote soft reset below reruns boot.py without starting the
# launcher, so the copies reach the REPL.
if ! python3 "$HERE/tools/stick_repl.py" ${REPL_PORT:+--port "$REPL_PORT"} "
import os, esp32
try:
    os.stat('/flash/main_uiflow.py')
except OSError:
    try:
        os.rename('/flash/main.py', '/flash/main_uiflow.py')
        print('saved UIFlow main.py as /flash/main_uiflow.py')
    except OSError:
        pass
try:
    os.mkdir('/flash/neswiki')
except OSError:
    pass
nvs = esp32.NVS('uiflow')
nvs.set_u8('boot_option', 0)
nvs.commit()
print('UIFlow boot_option set to 0: the Stick will start NESpedia')
"; then
    echo "" >&2
    echo "Could not reach the Stick's REPL. Either an app is running and will" >&2
    echo "not stop, or the Stick is not running UIFlow 2.0. nes-radar's" >&2
    echo "firmware/stick_s3/tools/erase_apps.py --dry-run tells which." >&2
    exit 1
fi
"$@" cp "$HERE"/neswiki/*.py :/flash/neswiki/
if [ -f "$HERE/config.json" ]; then
    "$@" cp "$HERE/config.json" :/flash/config.json
fi
"$@" cp "$HERE/main.py" :/flash/main.py
"$@" reset
echo "Deployed. The Stick restarts into NESpedia."
