/* MP3 as it arrives, a piece at a time, into samples (mp3.c).
 *
 * The decoder is minimp3 (third_party/minimp3), which wants whole frames;
 * a stream comes in pieces that end anywhere. What has come is held here
 * until there are a few frames of it, and each frame decoded is handed on.
 */
#ifndef NESP_MP3_H
#define NESP_MP3_H

#include <stddef.h>
#include <stdint.h>

#include "minimp3.h"

#ifdef __cplusplus
extern "C" {
#endif

/* A frame of a stream is under 1500 bytes. The decoder is surer of where
 * one begins with the frames after it to go by, so nothing is decoded with
 * less than NESP_MP3_AHEAD held. */
#define NESP_MP3_AHEAD 3072
#define NESP_MP3_HELD (NESP_MP3_AHEAD + 1536)

/* A frame's samples: `count` of them for each channel, the channels' in
 * turn if there are two, at `hz` a second. */
typedef void (*nesp_mp3_out_t)(void *ctx, const int16_t *pcm, size_t count, int channels,
                               int hz);

typedef struct {
    mp3dec_t decoder;
    uint8_t held[NESP_MP3_HELD];
    size_t held_len;
    int16_t pcm[MINIMP3_MAX_SAMPLES_PER_FRAME];
    uint32_t frames;                /* decoded */
    uint32_t skipped;               /* bytes passed over that were no frame's */
} nesp_mp3_t;

void nesp_mp3_init(nesp_mp3_t *mp3);

/* More of the stream. `out` is called for each frame it completes, from
 * here. The decoder keeps some 16 KB on the stack while it works. */
void nesp_mp3_feed(nesp_mp3_t *mp3, const uint8_t *data, size_t len, nesp_mp3_out_t out,
                   void *ctx);

#ifdef __cplusplus
}
#endif

#endif
