#!/bin/sh
# Copy NES Jukebox and its music onto a Stick running UIFlow 2.0 firmware
# (M5StickS3, or the M5StickC Plus2 stand-in).
#
#   tools/deploy.sh [-p serial-port] [music files or directories ...]
#
# With no music named it takes ../../music. Needs mpremote 1.24 or later
# (pip install mpremote). mpremote finds a single attached board by itself;
# name the port when the FTDI test cable is plugged in as well.
#
# A file the Stick already holds is not copied again: mpremote compares a
# hash of each file with the Stick's copy and passes over the ones that
# match, so a second run sends only what changed.
#
# What it changes on the Stick:
#   - copies nesjuke/ and main.py (and config.json if present here) into
#     /flash, UIFlow's user filesystem;
#   - makes /flash/tracks hold the music, converted to .jbs on this
#     computer, and sampled sound (.pcm, .wav, .mp3) as .pcm, and removes
#     the tracks there that are not in this playlist;
#   - saves UIFlow's existing /flash/main.py as /flash/main_uiflow.py the
#     first time, so tools/restore_uiflow.sh can put it back;
#   - sets UIFlow's boot_option to 0, so the Stick runs the jukebox at
#     power-on instead of the UIFlow launcher.
set -eu

HERE=$(cd "$(dirname "$0")/.." && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
BUILD="$HERE/build"
PORT=auto
if [ "${1:-}" = "-p" ]; then
    PORT=$2
    shift 2
fi
if [ -x "$ROOT/.venv/bin/python" ]; then
    PYTHON="$ROOT/.venv/bin/python"
else
    PYTHON=python3
fi

if [ $# -eq 0 ]; then
    set -- "$ROOT/music"
fi
"$PYTHON" "$HERE/tools/pack_tracks.py" "$BUILD/tracks" "$@"
TRACKS=$(cd "$BUILD/tracks" && echo *.*)

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
# launcher, so the copies reach the REPL. Tracks that are not in this
# playlist go now, so a shorter one leaves none behind; the rest stay for
# mpremote to compare.
if ! "$PYTHON" "$HERE/tools/stick_repl.py" ${REPL_PORT:+--port "$REPL_PORT"} "
import os, esp32
try:
    os.stat('/flash/main_uiflow.py')
except OSError:
    try:
        os.rename('/flash/main.py', '/flash/main_uiflow.py')
        print('saved UIFlow main.py as /flash/main_uiflow.py')
    except OSError:
        pass
for name in ('/flash/nesjuke', '/flash/tracks'):
    try:
        os.mkdir(name)
    except OSError:
        pass
for name in os.listdir('/flash/tracks'):
    if name not in '$TRACKS'.split():
        os.remove('/flash/tracks/' + name)
        print('removed /flash/tracks/' + name)
nvs = esp32.NVS('uiflow')
nvs.set_u8('boot_option', 0)
nvs.commit()
print('UIFlow boot_option set to 0: the Stick will start the jukebox')
"; then
    echo "" >&2
    echo "Could not reach the Stick's REPL. Either an app is running and will" >&2
    echo "not stop, or the Stick is not running UIFlow 2.0. nes-radar's" >&2
    echo "firmware/stick_s3/tools/erase_apps.py --dry-run tells which." >&2
    exit 1
fi
"$@" cp "$HERE"/nesjuke/*.py :/flash/nesjuke/
"$@" cp "$BUILD"/tracks/*.* :/flash/tracks/
if [ -f "$HERE/config.json" ]; then
    "$@" cp "$HERE/config.json" :/flash/config.json
fi
"$@" cp "$HERE/main.py" :/flash/main.py
"$@" reset
echo "Deployed. The Stick restarts into the jukebox."
