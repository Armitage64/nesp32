/* The nesp32's files, lent to a computer as a USB drive (SYS DRIVE). */
#ifndef USB_H
#define USB_H

#include "nesp_services.h"

#ifdef __cplusplus
extern "C" {
#endif

/* At start, before anything else of this: the USB port is the serial port
 * the firmware is flashed and watched through, whatever it was before the
 * restart. */
void usb_start(void);

/* nesp_hal_t's drive: what the console asks of it (NESP_LEND_*), and how it
 * stands (NESP_DRIVE_*). From the link task, and it never waits: what was
 * asked is done by usb_poll. */
uint8_t usb_drive(void *ctx, uint8_t lend);

/* How it stands, for the screen. */
uint8_t usb_drive_state(void);

/* Do what was asked: become a drive, or restart to stop being one, which
 * is also what follows a computer's letting go of it. For the main task,
 * every so often. */
void usb_poll(void);

#ifdef __cplusplus
}
#endif

#endif
