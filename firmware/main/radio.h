/* The Stick's Wi-Fi, and the rest of what the services ask of the hardware. */
#ifndef RADIO_H
#define RADIO_H

#include "nesp_services.h"

#ifdef __cplusplus
extern "C" {
#endif

/* What the services are given to ask the hardware with. Call it first: it
 * needs nothing started. */
const nesp_hal_t *radio_hal(void);

/* Open the settings kept in flash and read what is kept there: the screen's
 * way up, RADAR's airport and WEATHER's zip code. Before radio_start, and
 * before anything is drawn. */
void radio_settings(void);

/* Start Wi-Fi and join the saved network, if there is one. */
void radio_start(void);

/* Which way up the screen should be: a half turn round from M5Stack's
 * landscape, or not. The build's (CONFIG_NESP_DISPLAY_FLIPPED) until the
 * console chooses (SYS SCREEN), and then the console's, kept over
 * power-off. Read by the task that owns M5Unified. */
bool radio_screen_flipped(void);

/* The battery's charge, 0 to 100, or 0xFF if not known. Set by the task
 * that owns M5Unified; read by the link task. */
void radio_set_battery(uint8_t percent);

/* For the Stick's screen. */
void radio_wifi(nesp_wifi_t *out);
void radio_app(char *id, uint8_t *version);

/* One of the two lines of the screen that a service may fill (nesp_hal_t's
 * show), into out, which holds RADIO_SHOWN_MAX bytes. Empty: it has not. */
#define RADIO_SHOWN_MAX 80          /* a line of the screen, or one that main.cpp makes two of */
void radio_shown(uint8_t row, char *out);

/* What the service in use last had to say for the log (nesp_hal_t's
 * watch), into out, which holds RADIO_WATCH_MAX bytes. False: nothing new
 * since the last call. */
#define RADIO_WATCH_MAX 256
bool radio_watch(char *out);

#ifdef __cplusplus
}
#endif

#endif
