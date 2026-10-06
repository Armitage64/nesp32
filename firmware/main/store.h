/* The nesp32's files: the jukebox's tracks (nesp_hal_t's tracks). */
#ifndef STORE_H
#define STORE_H

#include "nesp_services.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Mount the `storage` partition and list the tracks in it. It can take a
 * while, the first time most of all: an empty partition is formatted. */
void store_start(void);

/* nesp_hal_t's tracks, track_size and track_read. The last two read flash
 * and are for the link task alone, between a reply and the next request. */
uint16_t store_tracks(void *ctx);
uint32_t store_track_size(void *ctx, uint16_t track);
size_t store_track_read(void *ctx, uint16_t track, uint32_t offset, uint8_t *out, size_t len);

#ifdef __cplusplus
}
#endif

#endif
