/* The nesp32's files: the jukebox's tracks (nesp_hal_t's tracks). */
#ifndef STORE_H
#define STORE_H

#include "nesp_services.h"

#define STORE_BASE "/files"         /* where the files are mounted */
#define STORE_PARTITION "storage"

#ifdef __cplusplus
extern "C" {
#endif

/* Mount the `storage` partition, list the tracks in it, and put in place
 * of each rip among them (a .vgm or a .vgz) the .jbs that is played. It can
 * take a while: an empty partition is formatted, and a rip takes its time.
 * progress, which may be NULL, is called before each rip: which one it is,
 * from 1, and of how many. */
typedef void (*store_progress_t)(unsigned rip, unsigned of);
void store_start(store_progress_t progress);

/* Giving the files up, to lend them as a drive (usb.c). First the link
 * task, which reads them, closes what it has open, after which there are
 * no tracks; then they are unmounted, by whichever task. */
void store_close(void);
void store_unmount(void);

/* nesp_hal_t's tracks, track_size and track_read. The last two read flash
 * and are for the link task alone, between a reply and the next request. */
uint16_t store_tracks(void *ctx);
uint32_t store_track_size(void *ctx, uint16_t track);
size_t store_track_read(void *ctx, uint16_t track, uint32_t offset, uint8_t *out, size_t len);

#ifdef __cplusplus
}
#endif

#endif
