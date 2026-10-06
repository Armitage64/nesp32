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

/* Start Wi-Fi and join the saved network, if there is one. */
void radio_start(void);

/* The battery's charge, 0 to 100, or 0xFF if not known. Set by the task
 * that owns M5Unified; read by the link task. */
void radio_set_battery(uint8_t percent);

/* For the Stick's screen. */
void radio_wifi(nesp_wifi_t *out);
void radio_app(char *id, uint8_t *version);

#ifdef __cplusplus
}
#endif

#endif
