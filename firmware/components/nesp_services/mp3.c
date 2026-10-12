/* MP3 as it arrives into samples (nesp_mp3.h). This is the one file that
 * holds minimp3's code: layer 3 only, and without the vector instructions
 * a computer has and a nesp32 has not, so that the tests decode with the
 * code the nesp32 runs.
 */
#include <string.h>

#include "nesp_mp3.h"

#define MINIMP3_ONLY_MP3
#define MINIMP3_NO_SIMD
#define MINIMP3_IMPLEMENTATION
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wconversion"
#pragma GCC diagnostic ignored "-Wsign-conversion"
#pragma GCC diagnostic ignored "-Wshadow"
#pragma GCC diagnostic ignored "-Wsign-compare"
#pragma GCC diagnostic ignored "-Wunused-parameter"
#pragma GCC diagnostic ignored "-Wunused-function"
#include "minimp3.h"
#pragma GCC diagnostic pop

void nesp_mp3_init(nesp_mp3_t *mp3)
{
    memset(mp3, 0, sizeof(*mp3));
    mp3dec_init(&mp3->decoder);
}

void nesp_mp3_feed(nesp_mp3_t *mp3, const uint8_t *data, size_t len, nesp_mp3_out_t out,
                   void *ctx)
{
    while (len != 0) {
        size_t take = sizeof(mp3->held) - mp3->held_len;
        if (take > len) {
            take = len;
        }
        memcpy(mp3->held + mp3->held_len, data, take);
        mp3->held_len += take;
        data += take;
        len -= take;
        size_t at = 0;
        while (mp3->held_len - at >= NESP_MP3_AHEAD) {
            mp3dec_frame_info_t info;
            int count = mp3dec_decode_frame(&mp3->decoder, mp3->held + at,
                                            (int)(mp3->held_len - at), mp3->pcm, &info);
            if (info.frame_bytes <= 0) {
                /* Nothing in all of it that could be a frame. */
                mp3->skipped += (uint32_t)(mp3->held_len - at);
                at = mp3->held_len;
                break;
            }
            mp3->skipped += (uint32_t)info.frame_offset;
            at += (size_t)info.frame_bytes;
            if (count > 0) {
                mp3->frames++;
                out(ctx, mp3->pcm, (size_t)count, info.channels, info.hz);
            }
        }
        memmove(mp3->held, mp3->held + at, mp3->held_len - at);
        mp3->held_len -= at;
    }
}
