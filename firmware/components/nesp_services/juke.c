/* JUKE: the jukebox's music, as a stream the console asks for by position
 * (docs/PROTOCOL.md). nes-jukebox's service.
 *
 * The nesp32 holds the tracks, as files (the hal's tracks): .jbs, a stream
 * of register writes for the console's sound chip, and .pcm, sampled sound.
 * Their formats are nes-jukebox's (its docs/PROTOCOL.md, parts 1, 2 and 4).
 * The console holds about a second of the stream in a ring and plays a
 * frame of it at every vblank; this keeps the ring fed.
 *
 * The playlist is one stream: each track's names and length as control
 * records, then its bytes, round its loop as often as `loops` says, then
 * the next track's. Nothing here decodes it. It may be cut anywhere, since
 * the console plays only whole frames.
 *
 * STREAM is "I have this much of it, and room for that much more". The
 * console says where it has got to, and the reply is the bytes from there.
 * The nesp32 keeps what it sent until the console's position has moved past
 * it, so a reply that was lost is sent again by the next request, and a
 * request that was lost changes nothing. No reply is held for a repeat.
 *
 * An epoch is a stretch of the stream with no jump inside it. Whatever
 * should be heard at once (another track, stop, the music after a sound)
 * begins a new one: positions start again from 0, and the console, seeing
 * an epoch that is not its own, drops what it had buffered and starts
 * from the reply's bytes.
 *
 * A .pcm track is not part of the stream. Its place there is its names
 * and then a sound record, after which the stream gives nothing more. The
 * console plays what it has, comes to the record, and asks for the sound
 * (SOUND); the samples then go as a run of RAW's, and the music after them
 * begins a new epoch.
 *
 * A .pcm file's samples are at an NTSC console's rates: its period's
 * cycles a bit of the NTSC clock. On a PAL console the same period is
 * 7.6% slower, so the nesp32 resamples them to the PAL rate (resample.c),
 * and a sound plays as long, and as high, as on NTSC (docs/PAL.md). Its
 * length on the screen is the file's own, either way.
 *
 * A console can leave a sound: button A of its controller, which is all of
 * it that it looks at then. It says so on a line that is the run's, where
 * nothing it sends can be read, so any NESP_JUKE_HEARD bytes heard in a
 * run mean that. The run is ended, the music is paused, and the sound is
 * due again, from as near as can be told to where the console stopped
 * listening; it asks for it when the music is played again.
 *
 * The console has a menu of the tracks, and asks for their names one at a
 * time (LIST): the game's, and the track's. The first asking of a track is
 * answered without them, and tick reads them for the next. CHOOSE plays a
 * track of the menu's from its beginning, and BUTTON's STOP is back to it.
 *
 * handle answers from `pending` and never reads a file. tick, which runs
 * after the reply has gone, reads ahead.
 */
#include <stdio.h>
#include <string.h>

#include "nesp_services.h"

/* Where the stream comes from next. */
enum {
    OPEN,           /* a track's file, not yet looked at */
    INTRO,          /* its names and length */
    RECORD,         /* a sound's record */
    DATA,           /* its bytes */
    WAIT,           /* a sound is due: nothing more until it is over */
    FINISHED,       /* the playlist has ended */
};

/* A sound track. */
enum {
    S_NONE,
    S_DUE,          /* its record is in the stream; the console will ask */
    S_ARMED,        /* the console was told to expect it */
    S_PLAYING,      /* the line is its */
};

#define FILL 64                 /* bytes kept ready for the console */
#define CHUNK 48                /* read from a file at a time */
#define READS 4                 /* reads in one tick */
#define SHOW_MS 500

#define JBS_HEADER 24
#define JBS_LOOPS 0x01
#define PCM_HEADER 8
#define TITLE_FILE_MAX 255
#define FRAMES_PER_SECOND 60
#define MORE 0x80               /* in what the console holds of every sample but the last */
#define RAMPS_PER_SECOND 50     /* a sound that was paused rises from the DAC's rest in 20 ms */

/* The stream's records (nes-jukebox's docs/PROTOCOL.md, part 1). */
#define OP_CONTROL 0x80
#define CTRL_END 0x00
#define CTRL_TITLE 0x02
#define CTRL_GAME 0x03
#define CTRL_LENGTH 0x04
#define CTRL_SOUND 0x05

/* A sound's rates, in CPU cycles a bit; the console is told the index. */
static const uint8_t periods[NESP_JUKE_SOUND_RATES] = {21, 16, 14, 12, 10, 8, 7};

typedef struct {
    bool sound;
    uint8_t rate;               /* a sound's, as an index into periods */
    uint32_t frames;            /* how long it plays */
    uint32_t data_at;           /* where its bytes are in the file */
    uint32_t data_end;
    uint32_t loop_at;           /* 0: it does not loop */
    uint8_t title_len;
    uint8_t title[TITLE_FILE_MAX];
} track_t;

static uint32_t get32(const uint8_t *data)
{
    return (uint32_t)data[0] | (uint32_t)data[1] << 8 | (uint32_t)data[2] << 16
           | (uint32_t)data[3] << 24;
}

/* A sound's rate at its period, in baud, as its file was made: an NTSC
 * console's. */
static uint32_t made_baud(uint8_t period)
{
    return (NESP_CPU_HZ + period / 2u) / period;
}

/* A track's header and title. False if the file is not one, or is cut
 * short. */
static bool look(nesp_juke_t *juke, uint16_t index, track_t *track)
{
    uint8_t head[JBS_HEADER + 1 + TITLE_FILE_MAX];
    const nesp_hal_t *hal = juke->hal;
    size_t got = hal->track_read(hal->ctx, index, 0, head, sizeof(head));
    uint32_t size = hal->track_size(hal->ctx, index);
    memset(track, 0, sizeof(*track));

    if (got > JBS_HEADER && memcmp(head, "JBS\x1a", 4) == 0 && head[4] == 1) {
        uint32_t frames = get32(head + 8);
        uint32_t loop_frame = get32(head + 12);
        uint32_t loop_offset = get32(head + 16);
        uint32_t length = get32(head + 20);
        track->title_len = head[JBS_HEADER];
        track->data_at = (uint32_t)JBS_HEADER + 1 + track->title_len;
        if (got < track->data_at || length == 0 || length > size
            || track->data_at > size - length) {
            return false;
        }
        memcpy(track->title, head + JBS_HEADER + 1, track->title_len);
        track->data_end = track->data_at + length;
        if ((head[5] & JBS_LOOPS) && loop_offset < length && loop_frame <= frames
            && juke->loops > 1) {
            track->loop_at = track->data_at + loop_offset;
            frames += (uint32_t)(juke->loops - 1) * (frames - loop_frame);
        }
        track->frames = frames;
        return true;
    }
    if (got >= PCM_HEADER && memcmp(head, "NPCM", 4) == 0 && head[4] == 1) {
        uint8_t rate = 0;
        while (rate < NESP_JUKE_SOUND_RATES && periods[rate] != head[5]) {
            rate++;
        }
        track->title_len = head[6];
        track->data_at = (uint32_t)PCM_HEADER + track->title_len;
        if (rate == NESP_JUKE_SOUND_RATES || got < track->data_at || size < track->data_at) {
            return false;
        }
        memcpy(track->title, head + PCM_HEADER, track->title_len);
        track->sound = true;
        track->rate = rate;
        track->data_end = size;
        /* A byte is a sample, and the nesp32 sends it as 11 bits, at the
         * rate it was made for: on a PAL console it is resampled, and
         * plays as long. */
        uint32_t baud = made_baud(head[5]);
        track->frames = (uint32_t)((uint64_t)(size - track->data_at) * FRAMES_PER_SECOND
                                   * NESP_TO_NES_BITS / baud);
        return true;
    }
    return false;
}

/* A name as the console's screen has it: cut to a line of it, trimmed,
 * and in printable ASCII, which its font is. Returns its length. */
static uint8_t screen_name(uint8_t *out, const uint8_t *text, size_t len)
{
    if (len > NESP_JUKE_TITLE_MAX) {
        len = NESP_JUKE_TITLE_MAX;
    }
    while (len != 0 && text[0] == ' ') {
        text++;
        len--;
    }
    while (len != 0 && text[len - 1] == ' ') {
        len--;
    }
    for (size_t index = 0; index < len; index++) {
        out[index] = text[index] >= 0x20 && text[index] < 0x7F ? text[index] : (uint8_t)'?';
    }
    return (uint8_t)len;
}

/* A control record with a name in it. */
static uint8_t put_name(uint8_t *out, uint8_t code, const uint8_t *text, size_t len)
{
    out[0] = OP_CONTROL;
    out[1] = code;
    out[2] = screen_name(out + 3, text, len);
    return (uint8_t)(3 + out[2]);
}

/* A title is "game - track"; one with no " - " is a track's name with no
 * game. Where the game's name ends, or len if there is none. */
static size_t game_ends(const uint8_t *title, size_t len)
{
    for (size_t index = 0; index + 3 <= len; index++) {
        if (memcmp(title + index, " - ", 3) == 0) {
            return index;
        }
    }
    return len;
}

/* What goes ahead of a track: the game's name, the track's, and how long
 * it will play, as nes-jukebox's tools/jbs.py builds them. */
static void make_intro(nesp_juke_t *juke, const track_t *track)
{
    const uint8_t *title = track->title;
    size_t len = track->title_len;
    size_t cut = game_ends(title, len);
    uint8_t *out = juke->intro;
    if (cut == len) {
        out += put_name(out, CTRL_GAME, title, 0);
        out += put_name(out, CTRL_TITLE, title, len);
    } else {
        out += put_name(out, CTRL_GAME, title, cut);
        out += put_name(out, CTRL_TITLE, title + cut + 3, len - cut - 3);
    }
    uint32_t seconds = track->frames / FRAMES_PER_SECOND;
    if (seconds > 99 * 60 + 59) {
        seconds = 99 * 60 + 59;
    }
    uint32_t minutes = seconds / 60;
    seconds %= 60;
    *out++ = OP_CONTROL;
    *out++ = CTRL_LENGTH;
    uint8_t *text = out;
    if (minutes >= 10) {
        *out++ = (uint8_t)('0' + minutes / 10);
    }
    *out++ = (uint8_t)('0' + minutes % 10);
    *out++ = ':';
    *out++ = (uint8_t)('0' + seconds / 10);
    *out++ = (uint8_t)('0' + seconds % 10);
    if (out - text < 5) {
        *out++ = ' ';
    }
    juke->intro_len = (uint8_t)(out - juke->intro);
    juke->intro_at = 0;
}

static void name_track(nesp_juke_t *juke, const track_t *track)
{
    size_t len = track->title_len;
    if (len > sizeof(juke->name) - 1) {
        len = sizeof(juke->name) - 1;
    }
    memcpy(juke->name, track->title, len);
    juke->name[len] = 0;
    juke->named = juke->index;
    juke->show = true;
}

/* Begin a new epoch: the console holds nothing of what comes next. */
static void new_epoch(nesp_juke_t *juke)
{
    juke->epoch++;
    juke->base = 0;
    juke->offered = 0;
    juke->pending_len = 0;
}

/* The stream starts again from the current track's beginning. */
static void rewind_track(nesp_juke_t *juke)
{
    juke->phase = OPEN;
    juke->sound = S_NONE;
    juke->sound_press = 0;
    juke->failed = 0;
}

static void start(nesp_juke_t *juke)
{
    juke->state = NESP_PLAYER_PLAYING;
    rewind_track(juke);
    new_epoch(juke);
    juke->show = true;
}

static void stop(nesp_juke_t *juke)
{
    juke->state = NESP_PLAYER_STOPPED;
    rewind_track(juke);
    new_epoch(juke);
    juke->show = true;
}

/* The track has given all it has: on to the next, or the end. */
static void advance(nesp_juke_t *juke)
{
    if (juke->index + 1 < juke->count || juke->repeat) {
        juke->index = (uint16_t)((juke->index + 1) % juke->count);
        juke->phase = OPEN;
    } else {
        juke->pending[juke->pending_len++] = OP_CONTROL;
        juke->pending[juke->pending_len++] = CTRL_END;
        juke->phase = FINISHED;
    }
}

/* A press or a choice is to be done. False if there is nothing to do it
 * to. A sound the console was told to expect is due again: it asks when
 * the music it is in plays. */
static bool pressing(nesp_juke_t *juke)
{
    if (juke->count == 0 || juke->state == NESP_PLAYER_NO_TRACKS) {
        return false;
    }
    juke->sound_press = 0;
    if (juke->sound == S_ARMED) {
        nesp_raw_drop(juke->raw);
        juke->sound = S_DUE;
    }
    return true;
}

/* Do what a button asks (NESP_PRESS_*), the console's or the nesp32's own.
 * Stop is the console's menu, with the track it was at. Next and previous
 * change the track and play it, also from stopped or paused. Play pauses
 * and resumes; from stopped, or after the playlist's end, it plays the
 * current track from its beginning. */
static void press(nesp_juke_t *juke, uint8_t buttons)
{
    if (!pressing(juke)) {
        return;
    }
    if (buttons & NESP_PRESS_STOP) {
        stop(juke);
    } else if (buttons & (NESP_PRESS_NEXT | NESP_PRESS_PREVIOUS)) {
        uint16_t step = buttons & NESP_PRESS_NEXT ? 1 : (uint16_t)(juke->count - 1);
        juke->index = (uint16_t)((juke->index + step) % juke->count);
        start(juke);
    } else if (buttons & NESP_PRESS_PLAY) {
        if (juke->state == NESP_PLAYER_STOPPED || juke->phase == FINISHED) {
            start(juke);
        } else {
            juke->state = juke->state == NESP_PLAYER_PAUSED ? NESP_PLAYER_PLAYING
                                                             : NESP_PLAYER_PAUSED;
            juke->show = true;
        }
    }
}

/* --- a sound, as a run of RAW's ------------------------------------------------ */

/* A sound's samples on their way from an NTSC rate to the PAL one: from
 * the hal's memory, the first time a PAL console plays a sound. */
#define PAL_IN 128              /* bytes of the file read at a time */
#define PAL_READY 512           /* samples made before a run: 24 ms at the fastest rate */
struct nesp_juke_pal {
    nesp_resample_t resample;
    uint8_t level[NESP_DAC_STEPS];
    float loudest;              /* what the DAC puts out at its top level */
    uint8_t in[PAL_IN];         /* read from the file, and not yet resampled */
    uint8_t in_at;
    uint8_t in_len;
    uint32_t tail;              /* samples of silence fed after the file's last */
    uint8_t period;             /* the rate the filter was worked out for; 0: none */
    /* The run's first samples, made in tick once the console has been told
     * to expect it (S_ARMED): the run then begins with no read of the file
     * and no work, which a console at the fastest rates cannot wait for. */
    bool primed;
    uint32_t primed_from;       /* the file's place they were made from, */
    uint32_t primed_to;         /* and the place after what they took */
    uint16_t ready_at;
    uint16_t ready_len;
    uint8_t ready[PAL_READY];
};

static uint8_t mirror(uint8_t byte)
{
    uint8_t out = 0;
    for (int bit = 0; bit < 8; bit++) {
        out = (uint8_t)(out << 1 | (byte >> bit & 1));
    }
    return out;
}

/* A sample on the wire and its level for the DAC, each way. The console's
 * receiver ends up with a byte's bits reversed and inverted, and with the
 * $40 its port's unused bits read left in from its last two reads (the
 * jukebox's tools/pcm.py). Every sample's has MORE: the one without it
 * ends the sound. */
static uint8_t sample_level(uint8_t byte)
{
    return (uint8_t)((mirror(byte) ^ 0x3F) & 0x7F);
}

static uint8_t sample_byte(uint8_t level)
{
    return mirror((uint8_t)((level | MORE) ^ 0x3F));
}

/* A sample on the wire, less loud. */
static uint8_t quieter(uint8_t byte, uint32_t part, uint32_t whole)
{
    return sample_byte((uint8_t)((uint32_t)sample_level(byte) * part / whole));
}

static bool resampled(const nesp_juke_t *juke)
{
    return juke->pal != NULL && juke->link->region == NESP_REGION_PAL;
}

/* A PAL console's resampler for the sound of the track being sent: made,
 * and its filter worked out, which takes milliseconds. So this is done in
 * tick, from when the track is opened, long before the run: a run at the
 * fastest rates begins with a lead the console's receiver settles on, and
 * a pause after it, while this was done, lost the console its place.
 * False: no memory for one, and the sound goes as it is, slow and low. */
static bool resample_ready(nesp_juke_t *juke)
{
    if (juke->pal == NULL) {
        juke->pal = juke->hal->alloc(juke->hal->ctx, sizeof(*juke->pal));
        if (juke->pal == NULL) {
            return false;
        }
        nesp_dac_levels(juke->pal->level);
        juke->pal->loudest = nesp_dac_out(NESP_DAC_LEVELS - 1);
        juke->pal->period = 0;
    }
    if (juke->pal->period != juke->sound_period) {
        uint32_t from = made_baud(juke->sound_period);
        uint32_t to = nesp_link_baud(juke->link, juke->sound_period);
        nesp_resample_init(&juke->pal->resample, (float)to / (float)from,
                           (uint32_t)((uint64_t)from * NESP_RESAMPLE_ONE / to));
        juke->pal->period = juke->sound_period;
    }
    return true;
}

static void resample_restart(struct nesp_juke_pal *pal)
{
    nesp_resample_restart(&pal->resample);
    pal->in_at = pal->in_len = 0;
    pal->tail = 0;
    pal->ready_at = pal->ready_len = 0;
}

/* Samples at the PAL rate from the file's place *at, which moves on with
 * what is read: up to max, and fewer rather than read the file again once
 * there are some. None only at the sound's end, after the file's last and
 * the filter's own reach of silence, which lets out what it still holds. */
static size_t resample_read(nesp_juke_t *juke, uint32_t *at, uint8_t *out, size_t max)
{
    struct nesp_juke_pal *pal = juke->pal;
    const nesp_hal_t *hal = juke->hal;
    size_t made = 0;
    while (made < max) {
        float value;
        if (nesp_resample_take(&pal->resample, &value)) {
            float place = value / pal->loudest * (float)(NESP_DAC_STEPS - 1) + 0.5f;
            if (place < 0.0f) {
                place = 0.0f;
            } else if (place > (float)(NESP_DAC_STEPS - 1)) {
                place = (float)(NESP_DAC_STEPS - 1);
            }
            out[made++] = sample_byte(pal->level[(int)place]);
            continue;
        }
        if (pal->in_at == pal->in_len) {
            if (made != 0) {
                break;                  /* what there is, now */
            }
            size_t got = 0;
            if (*at < juke->sound_end) {
                size_t want = juke->sound_end - *at;
                got = hal->track_read(hal->ctx, juke->index, *at, pal->in,
                                      want < PAL_IN ? want : PAL_IN);
            }
            if (got == 0) {
                if (pal->tail == 2 * pal->resample.reach) {
                    break;
                }
                pal->tail++;
                nesp_resample_put(&pal->resample, 0.0f);
                continue;
            }
            *at += (uint32_t)got;
            pal->in_at = 0;
            pal->in_len = (uint8_t)got;
        }
        nesp_resample_put(&pal->resample, nesp_dac_out(sample_level(pal->in[pal->in_at++])));
    }
    return made;
}

/* The run's first samples, from the file's place now, made ahead of it. */
static void resample_prime(nesp_juke_t *juke)
{
    struct nesp_juke_pal *pal = juke->pal;
    uint32_t at = juke->sound_at;
    resample_restart(pal);
    size_t made = 0;
    while (made < PAL_READY) {
        size_t got = resample_read(juke, &at, pal->ready + made, PAL_READY - made);
        if (got == 0) {
            break;
        }
        made += got;
    }
    pal->ready_len = (uint16_t)made;
    pal->primed = true;
    pal->primed_from = juke->sound_at;
    pal->primed_to = at;
}

/* A PAL console is about to be sent a sound from where it is: from what
 * was made ahead of the run if it is from here, or started afresh. */
static void resample_from_here(nesp_juke_t *juke)
{
    if (juke->link->region != NESP_REGION_PAL || !resample_ready(juke)) {
        return;
    }
    struct nesp_juke_pal *pal = juke->pal;
    if (pal->primed && pal->primed_from == juke->sound_at) {
        juke->sound_at = pal->primed_to;
    } else {
        resample_restart(pal);
    }
    pal->primed = false;
}

/* Samples for the run: what was made ahead of it first. */
static size_t resample_send(nesp_juke_t *juke, uint8_t *out, size_t max)
{
    struct nesp_juke_pal *pal = juke->pal;
    if (pal->ready_at < pal->ready_len) {
        size_t left = (size_t)(pal->ready_len - pal->ready_at);
        size_t count = left < max ? left : max;
        memcpy(out, pal->ready + pal->ready_at, count);
        pal->ready_at = (uint16_t)(pal->ready_at + count);
        return count;
    }
    return resample_read(juke, &juke->sound_at, out, max);
}

/* The bytes of $FF a sound at this rate begins with: the console's routine
 * at the fastest rates tracks each byte's start bit from the one before,
 * and settles on them first. */
static uint8_t sound_lead(uint8_t period)
{
    return period <= NESP_SOUND_TRACKED ? NESP_SOUND_LEAD : 0;
}

/* Samples a second at the sound's rate: the nesp32 sends a byte as 11 bits. */
static uint32_t sound_hz(const nesp_juke_t *juke)
{
    return nesp_link_baud(juke->link, juke->sound_period) / NESP_TO_NES_BITS;
}

/* Samples of the file in so many sent: as many, unless they are being
 * resampled. */
static uint32_t file_samples(const nesp_juke_t *juke, uint32_t sent)
{
    if (!resampled(juke)) {
        return sent;
    }
    return (uint32_t)((uint64_t)sent * made_baud(juke->sound_period)
                      / nesp_link_baud(juke->link, juke->sound_period));
}

/* A file is already what goes on the wire, a byte a sample, to an NTSC
 * console; a PAL one's are resampled. A button on the nesp32 ends it
 * early, and so does a console that is heard, which is
 * then not listening; either way it ends with the byte that leaves the
 * console's DAC at 0. A sound that was paused begins again from the DAC's
 * rest, where the console left it. */
static size_t sound_read(void *ctx, uint8_t *out, size_t max)
{
    nesp_juke_t *juke = ctx;
    const nesp_hal_t *hal = juke->hal;
    if (juke->sound != S_PLAYING) {
        juke->sound_from = juke->sound_at;
        juke->sound_fresh = true;
        resample_from_here(juke);
    }
    juke->sound = S_PLAYING;
    if (juke->sound_ended) {
        return 0;
    }
    if (juke->sound_spoke >= NESP_JUKE_HEARD) {
        juke->sound_hushed = true;
    }
    if (juke->sound_press == 0 && !juke->sound_hushed) {
        size_t got = 0;
        if (resampled(juke)) {
            got = resample_send(juke, out, max);
        } else if (juke->sound_at < juke->sound_end) {
            size_t want = juke->sound_end - juke->sound_at;
            if (want > max) {
                want = max;
            }
            got = hal->track_read(hal->ctx, juke->index, juke->sound_at, out, want);
            juke->sound_at += (uint32_t)got;
        }
        if (got != 0) {
            for (size_t index = 0; index < got && juke->sound_rise < juke->sound_ramp; index++) {
                out[index] = quieter(out[index], juke->sound_rise++, juke->sound_ramp);
            }
            return got;
        }
    }
    juke->sound_ended = true;
    out[0] = NESP_JUKE_SOUND_LAST;
    return 1;
}

/* The console sent something while the sound had the line. */
static void sound_heard(void *ctx, size_t len)
{
    nesp_juke_t *juke = ctx;
    if (juke->sound_spoke == 0) {
        juke->sound_spoke_ms = juke->now;
    }
    juke->sound_spoke += (uint32_t)len;
}

/* Where in its file a sound was when the console was first heard. What
 * has been read is further on by all that the UART had not yet sent, so
 * this goes by the clock: a byte a sample since the run's first. */
static uint32_t hushed_at(const nesp_juke_t *juke)
{
    uint32_t played = (uint32_t)((uint64_t)(juke->sound_spoke_ms - juke->sound_began)
                                 * sound_hz(juke) / 1000u);
    played = played > juke->run.lead ? played - juke->run.lead : 0;     /* not samples */
    played = file_samples(juke, played);
    uint32_t read = juke->sound_at - juke->sound_from;
    return juke->sound_from + (played < read ? played : read);
}

static void sound_done(void *ctx, bool sent)
{
    nesp_juke_t *juke = ctx;
    if (juke->sound != S_ARMED && juke->sound != S_PLAYING) {
        return;
    }
    uint8_t pressed = juke->sound_press;
    juke->sound_press = 0;
    juke->show = true;
    if (!sent) {
        /* The console asked for something else, so it is not waiting for
         * samples, and the sound is still due. */
        juke->sound = S_DUE;
        if (pressed != 0) {
            press(juke, pressed);
        }
        return;
    }
    juke->sound = S_NONE;
    if (pressed & (NESP_PRESS_NEXT | NESP_PRESS_PREVIOUS)) {
        press(juke, pressed);
    } else if (pressed & NESP_PRESS_PLAY) {
        stop(juke);             /* the nesp32's own button does not pause a sound: it stops it */
    } else if (juke->sound_hushed && hushed_at(juke) < juke->sound_end) {
        /* The console left it, and holds no more of the stream than it
         * did: the sound is due again, from where it stopped listening. */
        juke->sound_at = hushed_at(juke);
        juke->sound_ramp = sound_hz(juke) / RAMPS_PER_SECOND;
        juke->sound_rise = 0;
        juke->sound = S_DUE;
        juke->state = NESP_PLAYER_PAUSED;
    } else {
        /* The music after a sound starts from a full buffer, as a change
         * of track does. */
        new_epoch(juke);
        advance(juke);
    }
}

/* --- reading ahead --------------------------------------------------------------- */

static bool open_track(nesp_juke_t *juke)
{
    track_t track;
    if (!look(juke, juke->index, &track)) {
        return false;
    }
    name_track(juke, &track);
    make_intro(juke, &track);
    juke->data_at = track.data_at;
    juke->data_end = track.data_end;
    juke->loop_at = track.loop_at;
    juke->passes_left = track.loop_at != 0 ? juke->loops : 1;
    juke->sound = S_NONE;
    juke->sound_ramp = juke->sound_rise = 0;
    if (track.sound) {
        juke->sound_rate = track.rate;
        juke->sound_period = periods[track.rate];
        juke->sound_at = track.data_at;
        juke->sound_end = track.data_end;
        juke->sound_ended = false;
        juke->data_end = juke->data_at;     /* none of it is the stream's */
        juke->phase = INTRO;
        return true;
    }
    juke->sound_period = 0;
    juke->phase = INTRO;
    return true;
}

/* More of the stream into pending. True if there is more to do yet. */
static bool fill(nesp_juke_t *juke)
{
    const nesp_hal_t *hal = juke->hal;
    uint8_t reads = 0;
    while (reads < READS && juke->pending_len < FILL) {
        switch (juke->phase) {
        case OPEN:
            reads++;
            if (open_track(juke)) {
                juke->failed = 0;
            } else if (++juke->failed >= juke->count) {
                juke->state = NESP_PLAYER_NO_TRACKS;    /* not one of them can be read */
                juke->show = true;
                return false;
            } else {
                advance(juke);
            }
            break;
        case INTRO: {
            uint8_t count = (uint8_t)(juke->intro_len - juke->intro_at);
            if (count > sizeof(juke->pending) - juke->pending_len) {
                count = (uint8_t)(sizeof(juke->pending) - juke->pending_len);
            }
            memcpy(juke->pending + juke->pending_len, juke->intro + juke->intro_at, count);
            juke->pending_len = (uint8_t)(juke->pending_len + count);
            juke->intro_at = (uint8_t)(juke->intro_at + count);
            if (juke->intro_at == juke->intro_len) {
                juke->phase = juke->sound_period != 0 ? RECORD : DATA;
            }
            break;
        }
        case RECORD:
            juke->pending[juke->pending_len++] = OP_CONTROL;
            juke->pending[juke->pending_len++] = CTRL_SOUND;
            juke->pending[juke->pending_len++] = juke->sound_rate;
            juke->sound = S_DUE;
            juke->phase = WAIT;
            juke->show = true;
            return false;
        case DATA: {
            size_t want = juke->data_end - juke->data_at;
            if (want > CHUNK) {
                want = CHUNK;
            }
            size_t got = hal->track_read(hal->ctx, juke->index, juke->data_at,
                                         juke->pending + juke->pending_len, want);
            reads++;
            juke->pending_len = (uint8_t)(juke->pending_len + got);
            juke->data_at += (uint32_t)got;
            if (got < want) {
                juke->data_at = juke->data_end;     /* the file has gone: no more of it */
                juke->passes_left = 1;
            }
            if (juke->data_at == juke->data_end) {
                if (juke->passes_left > 1) {
                    juke->passes_left--;
                    juke->data_at = juke->loop_at;
                } else {
                    advance(juke);
                }
            }
            break;
        }
        default:
            return false;
        }
    }
    return juke->pending_len < FILL && juke->phase < WAIT;
}

/* The nesp32's screen: the track, which may take both lines. */
static void show(nesp_juke_t *juke, uint32_t now)
{
    if (!juke->show && now - juke->shown_at < SHOW_MS) {
        return;
    }
    juke->show = false;
    juke->shown_at = now;
    if (juke->hal->show == NULL) {
        return;
    }
    char text[96];
    if (juke->count == 0 || juke->named != juke->index) {
        text[0] = 0;
    } else {
        snprintf(text, sizeof(text), "%u/%u %s", (unsigned)juke->index + 1u,
                 (unsigned)juke->count, juke->name);
    }
    juke->hal->show(juke->hal->ctx, 0, text);
    juke->hal->show(juke->hal->ctx, 1, "");
}

/* The names of the track the console asked for, from its file. */
static void read_names(nesp_juke_t *juke)
{
    track_t track;
    uint16_t index = juke->list_want;
    juke->list_want = NESP_JUKE_LIST_NONE;
    juke->list_game_len = juke->list_track_len = 0;
    if (look(juke, index, &track)) {
        size_t cut = game_ends(track.title, track.title_len);
        if (cut == track.title_len) {
            juke->list_track_len = screen_name(juke->list_track, track.title, track.title_len);
        } else {
            juke->list_game_len = screen_name(juke->list_game, track.title, cut);
            juke->list_track_len = screen_name(juke->list_track, track.title + cut + 3,
                                               track.title_len - cut - 3);
        }
    }
    juke->list_index = index;       /* a file that is not a track has no names */
}

static bool tick(void *ctx, uint32_t now)
{
    nesp_juke_t *juke = ctx;
    bool soon = false;
    juke->now = now;
    if (juke->sound_period != 0 && juke->link->region == NESP_REGION_PAL
        && (juke->pal == NULL || juke->pal->period != juke->sound_period)) {
        resample_ready(juke);       /* before its run, which cannot wait for it */
    }
    if (juke->sound == S_ARMED && juke->link->region == NESP_REGION_PAL && juke->pal != NULL
        && juke->pal->period == juke->sound_period
        && !(juke->pal->primed && juke->pal->primed_from == juke->sound_at)) {
        resample_prime(juke);       /* and its first samples, likewise */
    }
    if (juke->sound_fresh) {
        juke->sound_fresh = false;
        juke->sound_began = now;    /* RAW's tick, which sent them, was this one */
    }
    if (juke->list_want != NESP_JUKE_LIST_NONE) {
        read_names(juke);
        soon = true;
    }
    if (juke->state == NESP_PLAYER_PLAYING) {
        soon = fill(juke) || soon;
    } else if (juke->state != NESP_PLAYER_NO_TRACKS && juke->named != juke->index) {
        /* Stopped: the name of the track that Play will start. */
        track_t track;
        if (look(juke, juke->index, &track)) {
            name_track(juke, &track);
        } else {
            juke->name[0] = 0;
            juke->named = juke->index;
        }
    }
    show(juke, now);
    return soon;
}

/* --- the console's requests ------------------------------------------------------ */

/* The console's count of frames it had nothing to play, of which it sends
 * the low byte: here as a total since its hello. */
static void note_underruns(nesp_juke_t *juke, uint8_t seen)
{
    if (juke->underruns_known) {
        juke->underruns += (uint8_t)(seen - juke->underruns_seen);
    }
    juke->underruns_known = true;
    juke->underruns_seen = seen;
}

static void stream(nesp_juke_t *juke, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len != 4 || reply->max < 2) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    uint8_t room = request->data[2];
    note_underruns(juke, request->data[3]);
    if (request->data[0] == juke->epoch && juke->state != NESP_PLAYER_NO_TRACKS) {
        /* What the console now holds of the last reply's bytes is done
         * with. All of them, or none if it did not hear. */
        uint8_t taken = (uint8_t)(request->data[1] - juke->base);
        if (taken > juke->offered) {
            /* It holds what was never sent: one of the two was switched
             * off and on. Begin again where both know where they are. */
            rewind_track(juke);
            new_epoch(juke);
        } else {
            if (taken == 0 && juke->offered != 0) {
                juke->resent++;
            }
            memmove(juke->pending, juke->pending + taken,
                    (size_t)(juke->pending_len - taken));
            juke->pending_len = (uint8_t)(juke->pending_len - taken);
            juke->base = (uint8_t)(juke->base + taken);
        }
    }
    /* A console in another epoch holds nothing of this one, and is sent it
     * from its start. */
    uint8_t count = 0;
    uint8_t state = juke->state;
    if (state == NESP_PLAYER_PLAYING) {
        count = juke->pending_len;
        if (count > room) {
            count = room;
        }
        if (count > reply->max - 2) {
            count = (uint8_t)(reply->max - 2);
        }
        if (count == juke->pending_len && juke->phase >= WAIT) {
            state |= NESP_PLAYER_DRAIN;
        }
    }
    juke->offered = count;
    reply->data[0] = state;
    reply->data[1] = juke->epoch;
    memcpy(reply->data + 2, juke->pending, count);
    reply->len = (uint8_t)(2 + count);
    reply->once = true;             /* the same request again is answered anew */
}

static void sound(nesp_juke_t *juke, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len != 2) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    uint8_t answer = NESP_SOUND_GONE;
    uint8_t epoch = request->data[0];
    if (epoch == juke->epoch && juke->sound != S_NONE
        && juke->state != NESP_PLAYER_NO_TRACKS) {
        if (juke->sound_press != 0) {
            /* A button on the nesp32 was waiting for the sound to begin,
             * and the console, asking again, is not deaf yet: do it now. */
            press(juke, juke->sound_press);
        }
        if (epoch != juke->epoch) {
            /* That was a jump: the sound went with the rest. */
        } else if (juke->state == NESP_PLAYER_PAUSED) {
            answer = NESP_SOUND_WAIT;
        } else {
            juke->run.ctx = juke;
            juke->run.read = sound_read;
            juke->run.done = sound_done;
            juke->run.heard = sound_heard;
            juke->run.lead = sound_lead(juke->sound_period);
            juke->sound_ended = juke->sound_hushed = false;
            juke->sound_spoke = 0;
            if (request->data[1] == juke->sound_rate
                && nesp_raw_arm(juke->raw, juke->sound_period, &juke->run)) {
                juke->sound = S_ARMED;
                answer = NESP_SOUND_GO;
            } else {
                /* The console cannot play it, or the nesp32 cannot send
                 * it: on with whatever is next. */
                nesp_raw_drop(juke->raw);
                juke->sound = S_NONE;
                new_epoch(juke);
                advance(juke);
            }
            juke->show = true;
        }
    }
    /* Otherwise it asks for a sound from before a jump, or one there is
     * not: the stream will put it right. */
    reply->data[0] = juke->state;
    reply->data[1] = answer;
    reply->len = 2;
    reply->once = true;             /* asked again, the wait for the run starts again */
}

/* How many tracks the console's menu has. */
static uint8_t listed(const nesp_juke_t *juke)
{
    if (juke->state == NESP_PLAYER_NO_TRACKS) {
        return 0;
    }
    return juke->count > NESP_JUKE_LIST_MAX ? NESP_JUKE_LIST_MAX : (uint8_t)juke->count;
}

/* LIST: how many tracks there are and the one play would start, and the
 * names of the one asked for if tick has read them. */
static void name(nesp_juke_t *juke, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len != 1) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    uint8_t index = request->data[0];
    uint8_t count = listed(juke);
    reply->data[0] = juke->state;
    reply->data[1] = count;
    reply->data[2] = juke->index < count ? (uint8_t)juke->index : 0;
    reply->len = 3;
    reply->once = true;             /* asked again, the names may be there */
    if (index >= count) {
        return;
    }
    if (juke->list_index != index) {
        juke->list_want = index;    /* for tick to read */
        return;
    }
    /* A console with little room for a reply has the names cut to it. */
    size_t room = reply->max > 5 ? reply->max - 5 : 0;
    uint8_t game = juke->list_game_len < room ? juke->list_game_len : (uint8_t)room;
    uint8_t track = juke->list_track_len < room - game ? juke->list_track_len
                                                       : (uint8_t)(room - game);
    uint8_t *out = reply->data + 3;
    if (reply->max < 5) {
        return;
    }
    *out++ = index;
    *out++ = game;
    memcpy(out, juke->list_game, game);
    out += game;
    memcpy(out, juke->list_track, track);
    out += track;
    reply->len = (uint8_t)(out - reply->data);
}

/* CHOOSE: play a track of the menu's, from its beginning. */
static void choose(nesp_juke_t *juke, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len != 1) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    if (request->data[0] < listed(juke) && pressing(juke)) {
        juke->index = request->data[0];
        start(juke);
    }
    reply->data[0] = juke->state;
    reply->len = 1;
}

static void handle(void *ctx, const nesp_request_t *request, nesp_reply_t *reply)
{
    nesp_juke_t *juke = ctx;
    switch (request->op) {
    case NESP_JUKE_STREAM:
        stream(juke, request, reply);
        break;
    case NESP_JUKE_BUTTON:
        if (request->len != 1) {
            reply->status = NESP_ST_BAD_ARG;
            break;
        }
        press(juke, request->data[0]);
        reply->data[0] = juke->state;
        reply->len = 1;
        break;
    case NESP_JUKE_SOUND:
        sound(juke, request, reply);
        break;
    case NESP_JUKE_LIST:
        name(juke, request, reply);
        break;
    case NESP_JUKE_CHOOSE:
        choose(juke, request, reply);
        break;
    default:
        reply->status = NESP_ST_NO_OP;
        break;
    }
}

/* The nesp32's own buttons do what the console's do: A is play or pause, B
 * the previous track and the power button the next. While the line is a
 * sound's they wait for its end, which they bring on. */
static bool event(void *ctx, uint8_t code, uint8_t arg)
{
    nesp_juke_t *juke = ctx;
    uint8_t buttons;
    (void)arg;
    switch (code) {
    case NESP_EVENT_BUTTON_A: buttons = NESP_PRESS_PLAY; break;
    case NESP_EVENT_BUTTON_B: buttons = NESP_PRESS_PREVIOUS; break;
    case NESP_EVENT_BUTTON_POWER: buttons = NESP_PRESS_NEXT; break;
    default: return false;
    }
    if (juke->sound == S_ARMED || juke->sound == S_PLAYING) {
        juke->sound_press = buttons;
    } else {
        press(juke, buttons);
    }
    return true;
}

/* A hello has asked for the service. Nothing plays until a button says so;
 * the track is the one it was at, if the nesp32 still has it. */
static void activate(void *ctx)
{
    nesp_juke_t *juke = ctx;
    juke->count = juke->hal->tracks(juke->hal->ctx);
    if (juke->index >= juke->count) {
        juke->index = 0;
    }
    juke->state = juke->count != 0 ? NESP_PLAYER_STOPPED : NESP_PLAYER_NO_TRACKS;
    rewind_track(juke);
    new_epoch(juke);
    juke->named = juke->count;
    juke->name[0] = 0;
    juke->resent = juke->underruns = 0;
    juke->underruns_known = false;
    juke->list_want = juke->list_index = NESP_JUKE_LIST_NONE;    /* the files may be others */
    juke->show = true;
}

static void deactivate(void *ctx)
{
    nesp_juke_t *juke = ctx;
    juke->state = NESP_PLAYER_STOPPED;
    rewind_track(juke);
    if (juke->pal != NULL) {
        juke->hal->release(juke->hal->ctx, juke->pal);
        juke->pal = NULL;
    }
    if (juke->hal->show != NULL) {
        juke->hal->show(juke->hal->ctx, 0, "");
        juke->hal->show(juke->hal->ctx, 1, "");
    }
}

void nesp_juke_service(nesp_service_t *service, nesp_juke_t *juke, nesp_link_t *link,
                       nesp_raw_t *raw, const nesp_hal_t *hal)
{
    memset(juke, 0, sizeof(*juke));
    juke->link = link;
    juke->hal = hal;
    juke->raw = raw;
    juke->loops = 2;
    juke->repeat = true;
    juke->list_want = juke->list_index = NESP_JUKE_LIST_NONE;
    memset(service, 0, sizeof(*service));
    service->id = NESP_SVC_JUKE;
    service->name = "JUKE";
    service->activate = activate;
    service->deactivate = deactivate;
    service->handle = handle;
    service->tick = tick;
    service->event = event;
    service->ctx = juke;
}
