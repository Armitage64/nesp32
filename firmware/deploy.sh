#!/bin/bash
# Build the firmware and flash it to every nesp32 on this computer's USB.
#
#   firmware/deploy.sh            build and flash whichever boards are connected
#   firmware/deploy.sh build      build for both boards, and flash nothing
#   firmware/deploy.sh watch      print the log of each connected board, without
#                                 restarting it: Ctrl-C to stop
#
# A StickS3 shows up as /dev/cu.usbmodem*, and a StickC Plus2 as
# /dev/cu.usbserial*: that is how each is told from the other. IDF_PATH is
# ~/esp/esp-idf unless it is set.
set -e
cd "$(dirname "$0")"
self="$PWD/$(basename "$0")"
. "${IDF_PATH:-$HOME/esp/esp-idf}/export.sh" > /dev/null 2>&1

build() {       # target
    echo "== building for $1"
    if ! idf.py -B "build-$1" -D "SDKCONFIG=build-$1/sdkconfig" -D "IDF_TARGET=$1" build \
            > "build-$1/deploy.log" 2>&1; then
        grep -E "error|Error|FAILED" "build-$1/deploy.log" | head -20
        echo "The build for $1 failed: build-$1/deploy.log has it all."
        exit 1
    fi
}

flash() {       # target port
    echo "== flashing the $(name "$1") on $2"
    if ! idf.py -B "build-$1" -p "$2" flash > "build-$1/deploy.log" 2>&1; then
        tail -5 "build-$1/deploy.log"
        echo "Flashing the $(name "$1") failed: build-$1/deploy.log has it all."
        exit 1
    fi
    echo "   written and checked; the nesp32 has been restarted"
}

boards() {      # prints "target port" for each board connected
    for port in /dev/cu.usbmodem*; do
        [ -e "$port" ] && echo "esp32s3 $port"
    done
    for port in /dev/cu.usbserial*; do
        [ -e "$port" ] && echo "esp32 $port"
    done
    return 0
}

name() {
    [ "$1" = esp32s3 ] && echo "StickS3" || echo "StickC Plus2"
}

case "${1:-flash}" in
build)
    build esp32s3
    build esp32
    ;;
flash)
    found=$(boards)
    if [ -z "$found" ]; then
        echo "No nesp32 is connected."
        exit 1
    fi
    while read -r target port; do
        build "$target"
        flash "$target" "$port"
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
    while read -r target port; do
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
' "$port" "$(name "$target")" &
    done <<< "$found"
    trap 'kill $(jobs -p) 2>/dev/null; exit 0' INT TERM
    wait
    ;;
*)
    sed -n '2,11p' "$self"
    exit 1
    ;;
esac
