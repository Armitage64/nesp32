/* A Bluetooth keyboard: what is typed on it (keyboard.c). */
#ifndef KEYBOARD_H
#define KEYBOARD_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* At start. In the spike (NESP_KBD_SPIKE), Bluetooth is turned on here and
 * stays on; a firmware without Bluetooth does nothing. */
void keyboard_start(void);

/* What has been typed, oldest first: printable ASCII and the control codes
 * of keyboard.c. Returns how many, up to max. From any task; never waits. */
size_t keyboard_read(uint8_t *out, size_t max);

#ifdef __cplusplus
}
#endif

#endif
