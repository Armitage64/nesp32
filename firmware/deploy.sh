#!/bin/bash
# Build the firmware and flash it to every nesp32 on this computer's USB.
#
#   firmware/deploy.sh            build and flash whichever boards are connected
#   firmware/deploy.sh build      build all three firmwares, and flash nothing
#   firmware/deploy.sh watch      print the log of each connected board, without
#                                 restarting it: Ctrl-C to stop
#   firmware/deploy.sh --generic [flash|watch]
#                                 the same, with each ESP32-S3 taken for a
#                                 generic board wired with resistors
#
# A StickS3 shows up as /dev/cu.usbmodem*, and a StickC Plus2 as
# /dev/cu.usbserial*: that is how each is told from the other. An ESP32-S3
# board shows up as a StickS3 does, so --generic says which it is.
#
# It needs ESP-IDF 5.1 or later, installed for esp32 and esp32s3, in
# ~/esp/esp-idf or wherever IDF_PATH points.
set -e
cd "$(dirname "$0")"
self="$PWD/$(basename "$0")"

# ESP-IDF, with what is wrong said when it is missing or not installed.
idf="${IDF_PATH:-$HOME/esp/esp-idf}"
if [ ! -f "$idf/export.sh" ]; then
    echo "ESP-IDF is not at $idf: clone it there and run its"
    echo "./install.sh esp32,esp32s3, or set IDF_PATH to where it is."
    exit 1
fi
# export.sh is quiet when it works; when it fails, what it printed says why.
if ! out=$(. "$idf/export.sh" 2>&1); then
    echo "$out" | tail -15
    echo "ESP-IDF's export.sh failed: has $idf/install.sh esp32,esp32s3 been run?"
    exit 1
fi
. "$idf/export.sh" > /dev/null 2>&1
if ! command -v idf.py > /dev/null; then
    echo "$idf/export.sh left no idf.py on the PATH: run $idf/install.sh esp32,esp32s3 again."
    exit 1
fi

# A firmware is its target, or for a generic board its target and -generic,
# and builds in build-<firmware>.
build() {       # firmware
    local defaults="sdkconfig.defaults"
    [ "$1" = esp32s3-generic ] && defaults="sdkconfig.defaults;sdkconfig.defaults.generic"
    echo "== building for $1"
    mkdir -p "build-$1"
    if ! idf.py -B "build-$1" -D "SDKCONFIG=build-$1/sdkconfig" -D "IDF_TARGET=${1%-generic}" \
            -D "SDKCONFIG_DEFAULTS=$defaults" build > "build-$1/deploy.log" 2>&1; then
        grep -E "error|Error|FAILED" "build-$1/deploy.log" | head -20
        echo "The build for $1 failed: build-$1/deploy.log has it all."
        exit 1
    fi
}

flash() {       # firmware port
    echo "== flashing the $(name "$1") on $2"
    if ! idf.py -B "build-$1" -p "$2" flash > "build-$1/deploy.log" 2>&1; then
        tail -5 "build-$1/deploy.log"
        echo "Flashing the $(name "$1") failed: build-$1/deploy.log has it all."
        exit 1
    fi
    echo "   written and checked; the nesp32 has been restarted"
}

boards() {      # prints "firmware port" for each board connected
    for port in /dev/cu.usbmodem*; do
        [ -e "$port" ] && echo "$s3 $port"
    done
    for port in /dev/cu.usbserial*; do
        [ -e "$port" ] && echo "esp32 $port"
    done
    return 0
}

name() {
    case "$1" in
    esp32s3) echo "StickS3" ;;
    esp32s3-generic) echo "ESP32-S3" ;;
    *) echo "StickC Plus2" ;;
    esac
}

s3=esp32s3
if [ "$1" = --generic ]; then
    s3=esp32s3-generic
    shift
fi

case "${1:-flash}" in
build)
    build esp32s3
    build esp32
    build esp32s3-generic
    ;;
flash)
    found=$(boards)
    if [ -z "$found" ]; then
        echo "No nesp32 is connected."
        exit 1
    fi
    while read -r firmware port; do
        build "$firmware"
        flash "$firmware" "$port"
    done <<< "$found"
    echo "== done"
    ;;
watch)
    found=$(boards)
    if [ -z "$found" ]; then
        echo "No nesp32 is connected."
        exit 1
    fi
    # Each board's log with its name before every line. The port is opened
    # with its control lines left alone, so the board is not restarted.
    while read -r firmware port; do
        python -c '
import sys
import serial

# A board restarts when RTS is up with DTR down. Opening a port raises both,
# which is harmless, so both are let down from there with RTS first.
port = serial.Serial()
port.port, port.baudrate, port.dtr, port.rts, port.timeout = sys.argv[1], 115200, True, True, 1
port.open()
port.rts = False
port.dtr = False
while True:
    line = port.readline()
    if line:
        print("%-12s %s" % (sys.argv[2], line.decode("utf-8", "replace").rstrip()), flush=True)
' "$port" "$(name "$firmware")" &
    done <<< "$found"
    trap 'kill $(jobs -p) 2>/dev/null; exit 0' INT TERM
    wait
    ;;
*)
    sed -n '2,17p' "$self"
    exit 1
    ;;
esac
