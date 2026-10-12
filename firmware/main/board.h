/* Which Stick this is, and the pins its hat's two stages are on.
 *
 * The hat is the 8-pin proto hat with the NPN level shifter from nes-radar
 * (docs/WIRING.md has the circuit and the reasons). One hat serves both
 * boards: its slots reach different pins on each, and the link is on the
 * same two slots.
 *
 *   slot     1    2       3    4        5    6    7       8
 *   S3       GND  EXT_5V  G0   G1       G8   BAT  3V3_L2  5V_IN
 *   Plus2    GND  5V OUT  G26  G36/G25  G0   BAT  3V3     5V IN
 *
 *   S3:    TX on G8 (slot 5), RX on G1 (slot 4).
 *   Plus2: TX on G0 (slot 5), RX on G36 (slot 4). G36 is input-only and
 *          shares its pad with G25, which must stay an input.
 *
 * G0 is the boot-mode pin on both. On a StickS3 it is slot 3, which the
 * hat leaves open: either stage there would start the board in
 * firmware-download mode. On a StickC Plus2 it is slot 5, the hat's TX,
 * and the board starts all the same with the TX stage's 10 k base resistor
 * on it: tried from off a number of times, with the console on and off. A
 * hat built for the Plus2's old pins, with TX on slot 3 (G26), has to be
 * converted (docs/WIRING.md).
 *
 * The two boards have different chips, so the board is the target the
 * firmware was built for (idf.py set-target esp32, or esp32s3).
 */
#ifndef BOARD_H
#define BOARD_H

#include "nesp_proto.h"
#include "sdkconfig.h"

#if CONFIG_IDF_TARGET_ESP32S3
#define BOARD_ID NESP_BOARD_S3
#define BOARD_NAME "StickS3"
#define BOARD_LINK_TX 8
#define BOARD_LINK_RX 1
#elif CONFIG_IDF_TARGET_ESP32
#define BOARD_ID NESP_BOARD_PLUS2
#define BOARD_NAME "StickC Plus2"
#define BOARD_LINK_TX 0
#define BOARD_LINK_RX 36
#else
#error "nesp32 is for a StickC Plus2 (esp32) or a StickS3 (esp32s3)"
#endif

/* Each NPN stage inverts, so the UART inverts TX and RX in hardware to
 * cancel it. A hat with a non-inverting shifter needs 0 here. */
#define BOARD_LINK_INVERTED 1

#endif
