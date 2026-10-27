/* A Bluetooth keyboard, for a ROM's text: KBD's hardware (keyboard.c). */
#ifndef KEYBOARD_H
#define KEYBOARD_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "nesp_services.h"

#ifdef __cplusplus
extern "C" {
#endif

/* At start: the keyboard's task, with Bluetooth off. A firmware built
 * without Bluetooth does nothing here. */
void keyboard_start(void);

/* For the main task, every so often: a wait for the paired keyboard to
 * wake is called off when the console asks for something else. */
void keyboard_poll(void);

/* True if this firmware has Bluetooth, and with it the hooks below. */
bool keyboard_built(void);

/* nesp_hal_t's kbd_*. From the link task; none of them waits. */
void keyboard_enable(void *ctx, bool on);
uint8_t keyboard_state(void *ctx, nesp_keyboard_t *paired, uint8_t *found);
bool keyboard_scan(void *ctx);
bool keyboard_found(void *ctx, uint8_t index, nesp_keyboard_t *out);
bool keyboard_pair(void *ctx, uint8_t index);
void keyboard_forget(void *ctx);
size_t keyboard_read(void *ctx, uint8_t *out, size_t max);

/* How it stands, for the log. */
const char *keyboard_said(void);

#ifdef __cplusplus
}
#endif

#endif
