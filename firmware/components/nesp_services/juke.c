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

/* The stream's records (nes-jukebox's docs/PROTOCOL.md, part 1). */
#define OP_CONTROL 0x80
#define CTRL_END 0x00
#define CTRL_TITLE 0x02
#define CTRL_GAME 0x03
#define CTRL_LENGTH 0x04
#define CTRL_SOUND 0x05

/* A sound's rates, in CPU cycles a bit; the console is told the index. */
static const uint8_t periods[NESP_JUKE_SOUND_RATES] = {21, 16, 14, 12, 10, 8};

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
        /* A byte is a sample, and the nesp32 sends it as 11 bits. */
        uint32_t baud = (NESP_CPU_HZ + head[5] / 2u) / head[5];
        track->frames = (uint32_t)((uint64_t)(size - track->data_at) * FRAMES_PER_SECOND
                                   * NESP_TO_NES_BITS / baud);
        return true;
    }
    return false;
}

/* A control record with a name in it: what is left of the text when it has
 * been cut to a line of the console's screen and trimmed. */
static uint8_t put_name(uint8_t *out, uint8_t code, const uint8_t *text, size_t len)
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
    out[0] = OP_CONTROL;
    out[1] = code;
    out[2] = (uint8_t)len;
    for (size_t index = 0; index < len; index++) {
        /* The console's font is printable ASCII. */
        out[3 + index] = text[index] >= 0x20 && text[index] < 0x7F ? text[index] : (uint8_t)'?';
    }
    return (uint8_t)(3 + len);
}

/* What goes ahead of a track: the game's name, the track's, and how long
 * it will play, as nes-jukebox's tools/jbs.py builds them. A title is
 * "game - track"; one with no " - " is a track's name with no game. */
static void make_intro(nesp_juke_t *juke, const track_t *track)
{
    const uint8_t *title = track->title;
    size_t len = track->title_len;
    size_t cut = len;
    for (size_t index = 0; index + 3 <= len; index++) {
        if (memcmp(title + index, " - ", 3) == 0) {
            cut = index;
            break;
        }
    }
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

/* Do what a button asks (NESP_PRESS_*), the console's or the nesp32's own.
 * Next and previous change the track and play it, also from stopped or
 * paused. Play pauses and resumes; from stopped, or after the playlist's
 * end, it plays the current track from its beginning. */
static void press(nesp_juke_t *juke, uint8_t buttons)
{
    if (juke->count == 0 || juke->state == NESP_PLAYER_NO_TRACKS) {
        return;
    }
    juke->sound_press = 0;
    if (juke->sound == S_ARMED) {
        nesp_raw_drop(juke->raw);
        juke->sound = S_DUE;
    }
    if (buttons & (NESP_PRESS_NEXT | NESP_PRESS_PREVIOUS)) {
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

/* A file is already what goes on the wire, a byte a sample. A button on
 * the nesp32 ends it early; either way it ends with the byte that leaves
 * the console's DAC at 0. */
static size_t sound_read(void *ctx, uint8_t *out, size_t max)
{
    nesp_juke_t *juke = ctx;
    const nesp_hal_t *hal = juke->hal;
    juke->sound = S_PLAYING;
    if (juke->sound_ended) {
        return 0;
    }
    if (juke->sound_press == 0 && juke->sound_at < juke->sound_end) {
        size_t want = juke->sound_end - juke->sound_at;
        if (want > max) {
            want = max;
        }
        size_t got = hal->track_read(hal->ctx, juke->index, juke->sound_at, out, want);
        if (got != 0) {
            juke->sound_at += (uint32_t)got;
            return got;
        }
    }
    juke->sound_ended = true;
    out[0] = NESP_JUKE_SOUND_LAST;
    return 1;
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
        stop(juke);             /* a sound cannot be paused: Play stops it */
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

static const char *state_text(const nesp_juke_t *juke)
{
    if (juke->sound == S_ARMED || juke->sound == S_PLAYING) {
        return "SOUND";
    }
    switch (juke->state) {
    case NESP_PLAYER_PLAYING: return "PLAYING";
    case NESP_PLAYER_PAUSED: return "PAUSED";
    case NESP_PLAYER_NO_TRACKS: return "NO MUSIC";
    default: return "STOPPED";
    }
}

/* The nesp32's screen: the track, and how the stream is doing. */
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
    snprintf(text, sizeof(text), "%s, %lu again, %lu dry", state_text(juke),
             (unsigned long)juke->resent, (unsigned long)juke->underruns);
    juke->hal->show(juke->hal->ctx, 1, text);
}

static bool tick(void *ctx, uint32_t now)
{
    nesp_juke_t *juke = ctx;
    bool soon = false;
    if (juke->state == NESP_PLAYER_PLAYING) {
        soon = fill(juke);
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
    juke->show = true;
}

static void deactivate(void *ctx)
{
    nesp_juke_t *juke = ctx;
    juke->state = NESP_PLAYER_STOPPED;
    rewind_track(juke);
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
