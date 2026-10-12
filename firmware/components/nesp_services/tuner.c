/* TUNER: a radio station from the Internet, played on the console as
 * sampled sound (docs/PROTOCOL.md).
 *
 * There is one station, NPR's. Its stream is MP3, fetched as any address
 * is and never ending. As it arrives it is decoded, mixed to one channel,
 * brought to the rate the console plays at and made into levels for the
 * console's DAC, and those are kept in a ring: a dozen seconds of them.
 * When a couple of seconds are held the console is told the station is
 * ready; it asks for the sound, and the ring goes to it as a run of RAW's,
 * a byte a sample, for as long as the station is wanted. That is JUKE's
 * sampled sound with no file behind it and no end.
 *
 * The console is deaf while a sound plays, so the way to stop one is the
 * nesp32's front button. A console that is reset says hello, at the
 * link's rate, into a line that is the run's: RAW tells of anything heard
 * during a run, and a few bytes of it end the station.
 *
 * Nothing keeps the station's clock and the console's together. The ring
 * is the slack: when the station runs ahead and the ring fills, its oldest
 * second is dropped; when the ring runs dry the console's DAC is held
 * where it is until a second has come. Neither should happen more than
 * once in some hours.
 *
 * Two tasks meet here. The link's task runs handle(), tick() and the run;
 * the fetch's runs body() and done(), and the decoder's memory (`work`) is
 * its alone. The ring, and which fetch is wanted (`generation`), are both
 * tasks', under the hal's lock.
 */
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "nesp_mp3.h"
#include "nesp_services.h"

#define STATION "https://npr-ice.streamguys1.com/live.mp3"
#define STATION_NAME "NPR"
#define AGENT "nesp32-npr/0.1 (NPR on a NES, on a nesp32; +https://github.com/Armitage64/nesp32)"

/* Samples a second, on the wire: the UART is the clock, a byte a sample. */
#define BAUD ((NESP_CPU_HZ + NESP_TUNER_PERIOD / 2u) / NESP_TUNER_PERIOD)
#define RATE (BAUD / NESP_TO_NES_BITS)
#define READY_SAMPLES (RATE * NESP_TUNER_READY_MS / 1000u)
#define RESUME_SAMPLES RATE         /* held again before a ring that ran dry is played */
#define DROP_SAMPLES RATE           /* dropped from a ring that is full */
#define RAMP_SAMPLES (RATE / 50u)   /* 20 ms from the DAC's rest, and back to it */
#define SPOKE_SAMPLES (2u * RATE)   /* bytes from the console count together within this */
#define SHOW_MS 1000

/* The resampler: a sinc under a Hann window, cut off below the lower of
 * the two rates' Nyquist, as tools/wav2pcm.py's is; worked out once for
 * PHASES places between two samples, and the nearest used. */
#define PHASES 64
#define TAPS_MAX 48
#define HISTORY 64                  /* samples kept: a power of two, and TAPS_MAX at least */
#define ZEROS 8                     /* zero crossings each side of the middle */
#define PASSBAND 0.92f
#define ONE 65536u                  /* a sample, where parts of one are counted */
#define PI 3.14159265f

#define LEVELS 128                  /* the DAC takes 7 bits */
#define STEPS 1024                  /* places between silence's two ends a sample is rounded to */
#define MORE 0x80                   /* in what the console holds for every byte but the last */
#define OUT 256

static const uint32_t rings[] = {256 * 1024, 128 * 1024, 64 * 1024};

enum {
    S_NONE,
    S_ARMED,        /* GO was said: the run is agreed, and has not begun */
    S_PLAYING,
};

struct nesp_tuner_work {
    nesp_tuner_t *tuner;
    uint32_t parsing;               /* the fetch the rest is in the middle of */
    bool begun;
    bool levelled;                  /* level[] has been worked out */
    nesp_mp3_t mp3;
    int hz;                         /* the stream's rate, which the kernel is for; 0: none yet */
    uint32_t reach;                 /* samples each side of the middle that the kernel takes */
    uint32_t step;                  /* samples in for one out, in ONEths */
    int32_t lag;                    /* from the next sample out back to the newest in, likewise */
    uint32_t newest;                /* the count of samples in */
    float history[HISTORY];
    float kernel[PHASES][TAPS_MAX];
    uint8_t level[STEPS];           /* the DAC's level for each place */
    uint8_t out[OUT];               /* levels on their way to the ring */
    size_t out_len;
};

static void lock(nesp_tuner_t *tuner)
{
    tuner->hal->lock(tuner->hal->ctx);
}

static void unlock(nesp_tuner_t *tuner)
{
    tuner->hal->unlock(tuner->hal->ctx);
}

/* --- the fetch's task ---------------------------------------------------------- */

/* The DAC is not a straight line: the console's mixer squeezes the top of
 * its range. Each place between the two ends gets the level whose output
 * is nearest, as wav2pcm.nearest_level has it. */
static void make_levels(struct nesp_tuner_work *work)
{
    double dac[LEVELS];
    dac[0] = 0.0;
    for (int level = 1; level < LEVELS; level++) {
        dac[level] = 159.79 / (22638.0 / level + 100.0);
    }
    int above = 0;
    for (int place = 0; place < STEPS; place++) {
        double target = (double)place / (STEPS - 1) * dac[LEVELS - 1];
        while (above < LEVELS - 1 && dac[above] < target) {
            above++;
        }
        int below = above > 0 ? above - 1 : 0;
        work->level[place] = (uint8_t)(target - dac[below] <= dac[above] - target ? below : above);
    }
    work->levelled = true;
}

/* The kernel for a stream at this rate. */
static void make_kernel(struct nesp_tuner_work *work, int hz)
{
    float ratio = (float)BAUD / (float)NESP_TO_NES_BITS / (float)hz;
    float cutoff = PASSBAND * (ratio < 1.0f ? ratio : 1.0f) / 2.0f;     /* cycles a sample in */
    float half = (float)ZEROS / (2.0f * cutoff);
    uint32_t reach = (uint32_t)ceilf(half);
    if (reach > TAPS_MAX / 2) {
        reach = TAPS_MAX / 2;       /* a rate above any a station has: a narrower window */
        half = (float)reach;
    }
    for (int phase = 0; phase < PHASES; phase++) {
        float sum = 0.0f;
        for (uint32_t tap = 0; tap < 2 * reach; tap++) {
            float t = (float)((int)tap - (int)reach + 1) - (float)phase / (float)PHASES;
            float weight = 0.0f;
            if (fabsf(t) < half) {
                float x = 2.0f * PI * cutoff * t;
                weight = (x != 0.0f ? sinf(x) / x : 1.0f)
                         * (0.5f + 0.5f * cosf(PI * t / half));
            }
            work->kernel[phase][tap] = weight;
            sum += weight;
        }
        for (uint32_t tap = 0; tap < 2 * reach; tap++) {
            work->kernel[phase][tap] /= sum;
        }
    }
    work->hz = hz;
    work->reach = reach;
    work->step = (uint32_t)((uint64_t)hz * ONE * NESP_TO_NES_BITS / BAUD);
    work->lag = 0;
    work->newest = 0;
    memset(work->history, 0, sizeof(work->history));
}

/* The levels worked out so far into the ring, if this fetch is still the
 * one wanted. A ring with no room loses its oldest second. */
static void flush(struct nesp_tuner_work *work)
{
    nesp_tuner_t *tuner = work->tuner;
    lock(tuner);
    if (tuner->generation == work->parsing && tuner->ring != NULL) {
        if (tuner->held + work->out_len > tuner->ring_size) {
            uint32_t drop = tuner->held < DROP_SAMPLES ? tuner->held : DROP_SAMPLES;
            tuner->head = (tuner->head + drop) % tuner->ring_size;
            tuner->held -= drop;
            tuner->dropped += drop;
        }
        uint32_t at = (tuner->head + tuner->held) % tuner->ring_size;
        uint32_t first = tuner->ring_size - at;
        if (first > work->out_len) {
            first = (uint32_t)work->out_len;
        }
        memcpy(tuner->ring + at, work->out, first);
        memcpy(tuner->ring, work->out + first, work->out_len - first);
        tuner->held += (uint32_t)work->out_len;
    }
    unlock(tuner);
    work->out_len = 0;
}

/* One more sample of the stream, and whatever samples for the console it
 * completes. */
static void put(struct nesp_tuner_work *work, float sample)
{
    work->newest++;
    work->history[work->newest % HISTORY] = sample;
    work->lag += (int32_t)ONE;
    while (work->lag >= (int32_t)(work->reach * ONE)) {
        /* The next sample out lies `lag` behind the newest in: between
         * `base` and the one after it, at the nearest of the PHASES. */
        uint32_t whole = (uint32_t)work->lag / ONE;
        uint32_t part = (uint32_t)work->lag % ONE;
        uint32_t base = work->newest - whole;
        uint32_t phase = 0;
        if (part != 0) {
            base--;
            phase = ((ONE - part) * PHASES + ONE / 2) / ONE;
            if (phase == PHASES) {
                phase = 0;
                base++;
            }
        }
        const float *weights = work->kernel[phase];
        uint32_t first = base - work->reach + 1;
        float sum = 0.0f;
        for (uint32_t tap = 0; tap < 2 * work->reach; tap++) {
            sum += weights[tap] * work->history[(first + tap) % HISTORY];
        }
        float place = (sum / 32768.0f + 1.0f) * 0.5f * (float)(STEPS - 1) + 0.5f;
        if (place < 0.0f) {
            place = 0.0f;
        } else if (place > (float)(STEPS - 1)) {
            place = (float)(STEPS - 1);
        }
        work->out[work->out_len++] = work->level[(int)place];
        if (work->out_len == OUT) {
            flush(work);
        }
        work->lag -= (int32_t)work->step;
    }
}

/* A frame of the stream, decoded. */
static void frame(void *ctx, const int16_t *pcm, size_t count, int channels, int hz)
{
    struct nesp_tuner_work *work = ctx;
    if (hz <= 0 || channels < 1 || channels > 2) {
        return;
    }
    if (hz != work->hz) {
        make_kernel(work, hz);
    }
    if (channels == 2) {
        for (size_t index = 0; index < count; index++) {
            put(work, ((float)pcm[2 * index] + (float)pcm[2 * index + 1]) * 0.5f);
        }
    } else {
        for (size_t index = 0; index < count; index++) {
            put(work, (float)pcm[index]);
        }
    }
}

static bool current(nesp_tuner_t *tuner, uint32_t id)
{
    lock(tuner);
    bool same = tuner->generation == id;
    unlock(tuner);
    return same;
}

static bool body(void *ctx, uint32_t id, const uint8_t *data, size_t len)
{
    nesp_tuner_t *tuner = ctx;
    struct nesp_tuner_work *work = tuner->work;
    if (work == NULL || !current(tuner, id)) {
        return false;
    }
    if (!work->begun || work->parsing != id) {
        work->tuner = tuner;
        work->parsing = id;
        work->begun = true;
        work->hz = 0;
        work->out_len = 0;
        nesp_mp3_init(&work->mp3);
        if (!work->levelled) {
            make_levels(work);
        }
    }
    nesp_mp3_feed(&work->mp3, data, len, frame, work);
    return true;
}

/* A station's stream has no end: one that ends, however it ends, is lost. */
static void done(void *ctx, uint32_t id, bool ok, const char *why)
{
    nesp_tuner_t *tuner = ctx;
    lock(tuner);
    if (tuner->generation == id && tuner->landed == 0) {
        tuner->landed = 1;
        snprintf(tuner->landed_why, sizeof(tuner->landed_why), "%s",
                 ok ? "THE STATION WENT OFF THE AIR" : why);
    }
    unlock(tuner);
}

/* --- the link's task ----------------------------------------------------------- */

/* The byte on the wire for a level. The console's receiver ends up with a
 * byte's bits reversed and inverted, and with the $40 its port's unused
 * bits read left in from its last two reads (the jukebox's tools/pcm.py,
 * sample_byte); nothing puts that right there. */
static uint8_t wire(uint8_t level)
{
    uint8_t raw = (uint8_t)((level | MORE) ^ 0x3F);
    uint8_t byte = 0;
    for (int bit = 0; bit < 8; bit++) {
        byte = (uint8_t)(byte << 1 | (raw >> bit & 1));
    }
    return byte;
}

/* No fetch is wanted, and nothing of one is held. */
static void forget(nesp_tuner_t *tuner)
{
    tuner->hal->fetch_stop(tuner->hal->ctx);
    lock(tuner);
    tuner->generation++;            /* a fetch still on its way adds nothing */
    tuner->head = tuner->held = 0;
    tuner->landed = 0;
    unlock(tuner);
}

static void stop(nesp_tuner_t *tuner)
{
    forget(tuner);
    tuner->state = NESP_TUNER_OFF;
    tuner->show = true;
}

static void fail(nesp_tuner_t *tuner, const char *why)
{
    forget(tuner);
    snprintf(tuner->why, sizeof(tuner->why), "%s", why);
    tuner->state = NESP_TUNER_FAILED;
    tuner->show = true;
}

/* Start on the station's stream. */
static void play(nesp_tuner_t *tuner)
{
    nesp_wifi_t wifi;
    memset(&wifi, 0, sizeof(wifi));
    tuner->hal->wifi(tuner->hal->ctx, &wifi);
    forget(tuner);
    tuner->show = true;
    if (wifi.state != NESP_WIFI_JOINED) {
        tuner->state = NESP_TUNER_NO_WIFI;
        return;
    }
    if (tuner->ring == NULL || tuner->work == NULL) {
        fail(tuner, "THE NESP32 IS OUT OF MEMORY");
        return;
    }
    lock(tuner);
    uint32_t id = tuner->generation;
    tuner->dropped = 0;
    unlock(tuner);
    tuner->dry = 0;
    if (!tuner->hal->fetch(tuner->hal->ctx, STATION, AGENT, id, &tuner->sink)) {
        fail(tuner, "THE NESP32 IS BUSY");
        return;
    }
    tuner->state = NESP_TUNER_TUNING;
}

/* More of the station for the console, from RAW's tick. It ends when the
 * nesp32's button says so, when the console is heard, which is then not
 * listening, or when the stream is lost and all of it has been played:
 * with the DAC brought back to its rest, and the byte that says that was
 * the last. A ring that is dry holds the DAC where it is. */
static size_t run_read(void *ctx, uint8_t *out, size_t max)
{
    nesp_tuner_t *tuner = ctx;
    tuner->sound = S_PLAYING;
    if (tuner->ended) {
        return 0;
    }
    if (tuner->spoke != 0 && tuner->sent - tuner->spoke_at > SPOKE_SAMPLES) {
        tuner->spoke = 0;           /* noise, long ago */
    }
    bool spoken = tuner->spoke >= NESP_TUNER_HEARD;
    if (!tuner->press && !spoken && !tuner->lost) {
        size_t count = 0;
        lock(tuner);
        if (tuner->holding && (tuner->held >= RESUME_SAMPLES || tuner->landed != 0)) {
            tuner->holding = false;
        }
        if (!tuner->holding) {
            count = tuner->held < max ? tuner->held : max;
            for (size_t index = 0; index < count; index++) {
                out[index] = tuner->ring[(tuner->head + index) % tuner->ring_size];
            }
            if (count != 0) {
                tuner->head = (tuner->head + (uint32_t)count) % tuner->ring_size;
                tuner->held -= (uint32_t)count;
            } else {
                if (tuner->landed != 0) {
                    tuner->lost = true;
                } else {
                    tuner->holding = true;
                    tuner->dry++;
                }
            }
        }
        unlock(tuner);
        if (!tuner->lost) {
            if (count == 0) {
                memset(out, wire(tuner->last), max);
                count = max;
            } else {
                for (size_t index = 0; index < count; index++) {
                    uint32_t level = out[index];
                    if (tuner->rise < RAMP_SAMPLES) {
                        level = level * tuner->rise++ / RAMP_SAMPLES;
                    }
                    tuner->last = (uint8_t)level;
                    out[index] = wire(tuner->last);
                }
            }
            tuner->sent += (uint32_t)count;
            return count;
        }
    }
    size_t count = 0;
    if (spoken) {
        tuner->fall = RAMP_SAMPLES; /* nobody is listening */
    }
    while (count < max && tuner->fall < RAMP_SAMPLES) {
        tuner->fall++;
        out[count++] = wire((uint8_t)(tuner->last * (RAMP_SAMPLES - tuner->fall) / RAMP_SAMPLES));
    }
    if (count < max) {
        out[count++] = NESP_JUKE_SOUND_LAST;
        tuner->ended = true;
    }
    return count;
}

static void run_done(void *ctx, bool sent)
{
    nesp_tuner_t *tuner = ctx;
    if (tuner->sound == S_NONE) {
        return;
    }
    bool pressed = tuner->press;
    tuner->sound = S_NONE;
    tuner->press = false;
    tuner->show = true;
    if (!sent) {
        /* The console asked for something else, so it is not waiting for
         * samples; the station is as ready as it was. */
        if (pressed) {
            stop(tuner);
        }
        return;
    }
    if (tuner->lost) {
        char why[sizeof(tuner->why)];
        lock(tuner);
        memcpy(why, tuner->landed_why, sizeof(why));
        unlock(tuner);
        fail(tuner, why);
    } else {
        stop(tuner);
    }
}

/* The console sent something while the run had the line. */
static void run_heard(void *ctx, size_t len)
{
    nesp_tuner_t *tuner = ctx;
    if (tuner->spoke == 0) {
        tuner->spoke_at = tuner->sent;
    }
    tuner->spoke += (uint32_t)len;
}

/* What the fetch's task has done since this one last looked: the stream
 * has ended, or enough of it has come to play. */
static void settle(nesp_tuner_t *tuner)
{
    if (tuner->sound != S_NONE
        || (tuner->state != NESP_TUNER_TUNING && tuner->state != NESP_TUNER_READY)) {
        return;
    }
    char why[sizeof(tuner->why)];
    lock(tuner);
    bool landed = tuner->landed != 0;
    uint32_t held = tuner->held;
    memcpy(why, tuner->landed_why, sizeof(why));
    unlock(tuner);
    if (landed) {
        fail(tuner, why);
    } else if (tuner->state == NESP_TUNER_TUNING && held >= READY_SAMPLES) {
        tuner->state = NESP_TUNER_READY;
        tuner->show = true;
    }
}

static void sound(nesp_tuner_t *tuner, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len != 1) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    uint8_t answer = NESP_SOUND_GONE;
    if (tuner->state == NESP_TUNER_TUNING) {
        answer = NESP_SOUND_WAIT;
    } else if (tuner->state == NESP_TUNER_READY) {
        if (tuner->press) {
            /* The button was waiting for the sound to begin, and the
             * console, asking again, is not deaf yet. */
            nesp_raw_drop(tuner->raw);
            tuner->sound = S_NONE;
            tuner->press = false;
            stop(tuner);
        } else if (request->data[0] != NESP_TUNER_RATE) {
            nesp_raw_drop(tuner->raw);
            tuner->sound = S_NONE;
            fail(tuner, "THIS NES CANNOT PLAY IT");
        } else {
            tuner->run.ctx = tuner;
            tuner->run.read = run_read;
            tuner->run.done = run_done;
            tuner->run.heard = run_heard;
            tuner->ended = tuner->lost = tuner->holding = false;
            tuner->last = 0;
            tuner->rise = tuner->fall = 0;
            tuner->spoke = tuner->sent = 0;
            if (nesp_raw_arm(tuner->raw, NESP_TUNER_PERIOD, &tuner->run)) {
                tuner->sound = S_ARMED;
                answer = NESP_SOUND_GO;
            } else {
                tuner->sound = S_NONE;
                fail(tuner, "THE NESP32 CANNOT SEND IT");
            }
        }
    }
    reply->data[0] = tuner->state;
    reply->data[1] = answer;
    reply->len = 2;
    reply->once = true;             /* asked again, the wait for the run starts again */
}

static void handle(void *ctx, const nesp_request_t *request, nesp_reply_t *reply)
{
    nesp_tuner_t *tuner = ctx;
    settle(tuner);
    switch (request->op) {
    case NESP_TUNER_PLAY:
        if (tuner->state != NESP_TUNER_TUNING && tuner->state != NESP_TUNER_READY) {
            play(tuner);
        }
        break;
    case NESP_TUNER_STOP:
        if (tuner->sound == S_ARMED) {
            nesp_raw_drop(tuner->raw);  /* it asks, so it did not hear GO */
            tuner->sound = S_NONE;
            tuner->press = false;
        }
        stop(tuner);
        break;
    case NESP_TUNER_STATE:
        break;
    case NESP_TUNER_SOUND:
        sound(tuner, request, reply);
        return;
    default:
        reply->status = NESP_ST_NO_OP;
        return;
    }
    /* How it stands, and why if it failed. */
    reply->data[0] = tuner->state;
    reply->len = 1;
    if (tuner->state == NESP_TUNER_FAILED) {
        size_t len = strlen(tuner->why);
        if (len > (size_t)(reply->max - 1)) {
            len = (size_t)(reply->max - 1);
        }
        memcpy(reply->data + 1, tuner->why, len);
        reply->len = (uint8_t)(1 + len);
    }
    reply->once = true;             /* it may stand otherwise by the next time */
}

/* The nesp32's screen: the station, and how it stands. */
static void show(nesp_tuner_t *tuner, uint32_t now)
{
    if (!tuner->show && now - tuner->shown_at < SHOW_MS) {
        return;
    }
    tuner->show = false;
    tuner->shown_at = now;
    if (tuner->hal->show == NULL) {
        return;
    }
    char text[48];
    lock(tuner);
    uint32_t held = tuner->held;
    uint32_t dropped = tuner->dropped;
    unlock(tuner);
    if (tuner->sound == S_PLAYING) {
        snprintf(text, sizeof(text), "ON THE AIR %us dry %u cut %u", (unsigned)(held / RATE),
                 (unsigned)tuner->dry, (unsigned)(dropped / DROP_SAMPLES));
    } else {
        static const char *const states[] = {"OFF", "NO WI-FI", "TUNING", "READY"};
        snprintf(text, sizeof(text), "%s",
                 tuner->state < sizeof(states) / sizeof(states[0]) ? states[tuner->state]
                                                                   : tuner->why);
    }
    tuner->hal->show(tuner->hal->ctx, 0, STATION_NAME);
    tuner->hal->show(tuner->hal->ctx, 1, text);
}

static bool tick(void *ctx, uint32_t now)
{
    nesp_tuner_t *tuner = ctx;
    settle(tuner);
    show(tuner, now);
    return false;
}

/* The nesp32's front button is the station's: on, and off. While the line
 * is the sound's it waits for the sound's end, which it brings on. */
static bool event(void *ctx, uint8_t code, uint8_t arg)
{
    nesp_tuner_t *tuner = ctx;
    (void)arg;
    if (code != NESP_EVENT_BUTTON_A) {
        return false;
    }
    if (tuner->sound != S_NONE) {
        tuner->press = true;
    } else if (tuner->state == NESP_TUNER_TUNING || tuner->state == NESP_TUNER_READY) {
        stop(tuner);
    } else {
        play(tuner);
    }
    return true;
}

/* A hello has asked for the service: room for the ring, and for the
 * decoder. Nothing is fetched until a button says so. */
static void activate(void *ctx)
{
    nesp_tuner_t *tuner = ctx;
    /* The decoder's memory is asked for once and kept: the fetch's task
     * may be in the middle of it whenever this one would give it back. */
    if (tuner->work == NULL) {
        tuner->work = tuner->hal->alloc(tuner->hal->ctx, sizeof(*tuner->work));
        if (tuner->work != NULL) {
            memset(tuner->work, 0, sizeof(*tuner->work));
        }
    }
    uint8_t *ring = tuner->ring;
    uint32_t size = tuner->ring_size;
    for (size_t index = 0; index < sizeof(rings) / sizeof(rings[0]) && ring == NULL; index++) {
        ring = tuner->hal->alloc(tuner->hal->ctx, rings[index]);
        size = rings[index];
    }
    tuner->hal->fetch_stop(tuner->hal->ctx);
    lock(tuner);
    tuner->ring = ring;
    tuner->ring_size = ring != NULL ? size : 0;
    tuner->generation++;
    tuner->head = tuner->held = 0;
    tuner->landed = 0;
    tuner->dropped = 0;
    unlock(tuner);
    tuner->state = NESP_TUNER_OFF;
    tuner->sound = S_NONE;
    tuner->press = false;
    tuner->dry = 0;
    tuner->show = true;
}

/* Another ROM is on the console. */
static void deactivate(void *ctx)
{
    nesp_tuner_t *tuner = ctx;
    tuner->hal->fetch_stop(tuner->hal->ctx);
    lock(tuner);
    uint8_t *ring = tuner->ring;
    tuner->ring = NULL;
    tuner->ring_size = 0;
    tuner->generation++;
    tuner->head = tuner->held = 0;
    unlock(tuner);
    if (ring != NULL) {
        tuner->hal->release(tuner->hal->ctx, ring);
    }
    tuner->state = NESP_TUNER_OFF;
    tuner->sound = S_NONE;
    tuner->press = false;
    if (tuner->hal->show != NULL) {
        tuner->hal->show(tuner->hal->ctx, 0, "");
        tuner->hal->show(tuner->hal->ctx, 1, "");
    }
}

void nesp_tuner_service(nesp_service_t *service, nesp_tuner_t *tuner, nesp_raw_t *raw,
                        const nesp_hal_t *hal)
{
    memset(tuner, 0, sizeof(*tuner));
    tuner->hal = hal;
    tuner->raw = raw;
    tuner->sink.ctx = tuner;
    tuner->sink.body = body;
    tuner->sink.done = done;
    memset(service, 0, sizeof(*service));
    service->id = NESP_SVC_TUNER;
    service->name = "TUNER";
    service->activate = activate;
    service->deactivate = deactivate;
    service->handle = handle;
    service->tick = tick;
    service->event = event;
    service->ctx = tuner;
}
