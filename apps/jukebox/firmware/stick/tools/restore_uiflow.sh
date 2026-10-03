#!/bin/sh
# Put a Stick back to the UIFlow 2.0 launcher at power-on.
#
#   tools/restore_uiflow.sh [serial-port]
#
# Restores UIFlow's main.py from the backup deploy.sh made, or, when there is
# none (after tools/erase_apps.py, /flash had no main.py to back up), writes
# UIFlow's stock one-line main.py. Then sets boot_option 1 so UIFlow shows its
# launcher, and restarts. The jukebox's files stay in /flash; tools/deploy.sh
# switches back.
#
# All of this runs in one REPL session through tools/stick_repl.py. A second
# mpremote session would soft-reset into the launcher, which holds the REPL.
set -eu

HERE=$(cd "$(dirname "$0")/.." && pwd)
PORT=${1:-}

python3 "$HERE/tools/stick_repl.py" ${PORT:+--port "$PORT"} --reset "
import os, esp32
try:
    os.rename('/flash/main_uiflow.py', '/flash/main.py')
    print('restored UIFlow main.py from /flash/main_uiflow.py')
except OSError:
    with open('/flash/main.py', 'w') as handle:
        handle.write('# main.py\n')
    print('no backup found; wrote UIFlow stock main.py')
nvs = esp32.NVS('uiflow')
nvs.set_u8('boot_option', 1)
nvs.commit()
print('UIFlow boot_option set to 1: the Stick now starts the UIFlow launcher')
"
echo "Done. The Stick restarts into the UIFlow launcher."
