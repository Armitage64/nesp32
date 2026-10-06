/* RAW: the line with framing off (docs/PROTOCOL.md).
 *
 * The link's frames cost seven bytes each and a wait for every reply, at one
 * rate. A run is the other way to use the wire: a stretch of bytes one way,
 * with nothing round them, at a rate of its own. Sampled sound is a run to
 * the console of a byte a sample; the throughput test's trials are runs of
 * the test pattern, either way.
 *
 * A run is agreed in frames, by a request and its reply, and from there
 * goes by the clock, in milliseconds from that reply:
 *
 *   to RAW_LISTEN_MS    the nesp32 goes on listening at the link's rate. A
 *                       console that did not hear the reply asks again, and
 *                       the wait starts again; one that asks for anything
 *                       else has called the run off
 *   at RAW_LISTEN_MS    the nesp32 changes its UART's rate. The console, who
 *                       heard the reply, has been silent since
 *   at RAW_SETTLE_MS    the console is listening for the run, or sending it
 *   at RAW_START_MS     the nesp32's first byte, if the run is its own
 *
 * and when the run's last byte has left, or the console's has come, the
 * nesp32 puts its UART back and the link is as it was. The console waits
 * RAW_REST_MS before it asks for anything.
 *
 * So the reply that agrees to a run is never held for a repeat: the same
 * request again is the console saying it did not hear, and must start the
 * wait again.
 *
 * Everything here that goes by the clock is done in tick, which the port
 * calls every couple of milliseconds while a run is on (nesp_core.h).
 * handle only agrees.
 */
#include <string.h>

#include "nesp_services.h"

enum {
    IDLE,
    ARMED,          /* agreed; listening in case the console asks again */
    WAITING,        /* the rate is the run's; its first byte is not due yet */
    SENDING,
    DRAINING,       /* all of it is with the UART, and not all has left */
    SETTLING,       /* the rate is the run's; what comes is not the console's yet */
    LISTENING,
};

/* An ESP32's UART leaves a byte of junk in its receiver when its rate is
 * changed (nes-jukebox's throughput test found it). The console sends
 * nothing until well after this. */
#define JUNK_MS 20

static void put16(uint8_t *out, uint32_t value)
{
    if (value > 0xFFFF) {
        value = 0xFFFF;
    }
    out[0] = (uint8_t)value;
    out[1] = (uint8_t)(value >> 8);
}

/* The pattern as a run: `lead` bytes of $FF for a receiver that needs some
 * to settle on, then the pattern from its seed. */
static size_t pattern_read(void *ctx, uint8_t *out, size_t max)
{
    nesp_raw_t *raw = ctx;
    size_t count = 0;
    while (count < max && raw->lead_left != 0) {
        out[count++] = 0xFF;
        raw->lead_left--;
    }
    size_t take = max - count;
    if (take > raw->left) {
        take = raw->left;
    }
    raw->rng = nesp_pattern(raw->rng, out + count, take);
    raw->left -= (uint32_t)take;
    return count + take;
}

/* Agree to a run. One that was agreed and has not begun is replaced, and
 * its owner told, unless this is the same owner asking again. */
static void agree(nesp_raw_t *raw, uint8_t period, bool from_console, const nesp_run_t *run)
{
    if (raw->phase == ARMED && raw->run.done != NULL
        && (run == NULL || run->done != raw->run.done || run->ctx != raw->run.ctx)) {
        raw->run.done(raw->run.ctx, false);
    }
    memset(&raw->run, 0, sizeof(raw->run));
    if (run != NULL) {
        raw->run = *run;
    }
    raw->patterned = run == NULL;
    raw->from_console = from_console;
    raw->period = period;
    raw->state = NESP_RUN_ARMED;
    raw->phase = ARMED;
    raw->requests = raw->link->counters.requests;
    raw->stamp = true;
    raw->ended = false;
    raw->held_len = raw->held_at = 0;
    raw->count = raw->bad = 0;
    raw->rng = raw->seed;
    raw->left = raw->length;
    raw->lead_left = raw->lead;
}

bool nesp_raw_arm(nesp_raw_t *raw, uint8_t period, const nesp_run_t *run)
{
    if (!nesp_link_active(raw->link, NESP_SVC_RAW) || period < NESP_RAW_PERIOD_MIN
        || raw->phase > ARMED) {
        return false;
    }
    raw->lead = 0;
    raw->seed = 0;
    raw->length = 0;
    agree(raw, period, false, run);
    return true;
}

void nesp_raw_drop(nesp_raw_t *raw)
{
    if (raw->phase == ARMED) {
        raw->phase = IDLE;
        raw->state = NESP_RUN_DROPPED;
    }
}

bool nesp_raw_owns_line(const nesp_raw_t *raw)
{
    return raw->phase > ARMED;
}

void nesp_raw_heard(nesp_raw_t *raw, const uint8_t *data, size_t len)
{
    if (raw->phase != LISTENING) {
        return;                     /* the nesp32 is sending, or this is junk */
    }
    uint8_t expected[32];
    while (len != 0 && raw->left != 0) {
        size_t take = len < sizeof(expected) ? len : sizeof(expected);
        if (take > raw->left) {
            take = raw->left;
        }
        raw->rng = nesp_pattern(raw->rng, expected, take);
        for (size_t index = 0; index < take; index++) {
            if (data[index] != expected[index]) {
                raw->bad++;
            }
        }
        raw->left -= (uint32_t)take;
        raw->count += (uint32_t)take;
        data += take;
        len -= take;
    }
    raw->stamp = true;              /* tick notes when */
}

/* The run is over: the line is the link's again. */
static void finish(nesp_raw_t *raw)
{
    raw->hal->line_rate(raw->hal->ctx, NESP_PERIOD);
    raw->phase = IDLE;
    raw->state = NESP_RUN_DONE;
    if (raw->run.done != NULL) {
        raw->run.done(raw->run.ctx, true);
    }
}

/* Hand the UART as much of the run as it has room for. */
static void pump(nesp_raw_t *raw)
{
    for (;;) {
        if (raw->held_at == raw->held_len) {
            if (raw->ended) {
                return;
            }
            size_t count = raw->patterned
                ? pattern_read(raw, raw->held, sizeof(raw->held))
                : raw->run.read(raw->run.ctx, raw->held, sizeof(raw->held));
            raw->held_at = 0;
            raw->held_len = (uint8_t)count;
            if (count == 0) {
                raw->ended = true;
                return;
            }
        }
        size_t left = (size_t)(raw->held_len - raw->held_at);
        size_t taken = raw->hal->line_write(raw->hal->ctx, raw->held + raw->held_at, left);
        if (taken > left) {
            taken = left;
        }
        raw->held_at = (uint8_t)(raw->held_at + taken);
        raw->count += (uint32_t)taken;
        if (raw->held_at != raw->held_len) {
            return;                 /* the UART is full */
        }
    }
}

static bool tick(void *ctx, uint32_t now)
{
    nesp_raw_t *raw = ctx;
    switch (raw->phase) {
    case ARMED:
        if (raw->stamp) {
            raw->stamp = false;
            raw->armed_at = now;
        }
        if (raw->link->counters.requests != raw->requests) {
            /* The console asked for something else: it is not waiting. */
            raw->phase = IDLE;
            raw->state = NESP_RUN_DROPPED;
            if (raw->run.done != NULL) {
                raw->run.done(raw->run.ctx, false);
            }
            return false;
        }
        if (now - raw->armed_at >= NESP_RAW_LISTEN_MS) {
            raw->hal->line_rate(raw->hal->ctx, raw->period);
            raw->changed_at = raw->heard_at = now;
            raw->stamp = false;
            raw->state = NESP_RUN_RUNNING;
            raw->phase = raw->from_console ? SETTLING : WAITING;
        }
        return true;
    case WAITING:
        if (now - raw->armed_at < NESP_RAW_START_MS) {
            return true;
        }
        raw->phase = SENDING;
        /* fall through */
    case SENDING:
        pump(raw);
        if (!raw->ended || raw->held_at != raw->held_len) {
            return true;
        }
        raw->phase = DRAINING;
        /* fall through */
    case DRAINING:
        if (!raw->hal->line_idle(raw->hal->ctx)) {
            return true;
        }
        finish(raw);
        return false;
    case SETTLING:
        if (now - raw->changed_at >= JUNK_MS) {
            raw->phase = LISTENING;
        }
        return true;
    case LISTENING:
        if (raw->stamp) {
            raw->stamp = false;
            raw->heard_at = now;
        }
        if (raw->left != 0
            && (raw->count == 0 || now - raw->heard_at < NESP_RAW_QUIET_MS)
            && now - raw->changed_at < NESP_RAW_GIVE_UP_MS) {
            return true;
        }
        finish(raw);
        return false;
    default:
        return false;
    }
}

static void handle(void *ctx, const nesp_request_t *request, nesp_reply_t *reply)
{
    nesp_raw_t *raw = ctx;
    const uint8_t *data = request->data;
    switch (request->op) {
    case NESP_RAW_SEND:
    case NESP_RAW_LISTEN: {
        bool listen = request->op == NESP_RAW_LISTEN;
        if (request->len != (listen ? 5 : 6)) {
            reply->status = NESP_ST_BAD_ARG;
            break;
        }
        const uint8_t *numbers = data + (listen ? 1 : 2);
        uint16_t seed = (uint16_t)(numbers[0] | numbers[1] << 8);
        uint16_t length = (uint16_t)(numbers[2] | numbers[3] << 8);
        if (data[0] < NESP_RAW_PERIOD_MIN || seed == 0 || length == 0) {
            reply->status = NESP_ST_BAD_ARG;
            break;
        }
        raw->lead = listen ? 0 : data[1];
        raw->seed = seed;
        raw->length = length;
        agree(raw, data[0], listen, NULL);
        reply->once = true;         /* asked again, the wait starts again */
        break;
    }
    case NESP_RAW_RESULT:
        reply->data[0] = raw->state;
        reply->data[1] = raw->period;
        put16(reply->data + 2, raw->count);
        put16(reply->data + 4, raw->bad);
        reply->len = 6;
        reply->once = true;
        break;
    default:
        reply->status = NESP_ST_NO_OP;
        break;
    }
}

static void activate(void *ctx)
{
    nesp_raw_t *raw = ctx;
    raw->phase = IDLE;
    raw->state = NESP_RUN_IDLE;
    raw->period = 0;
    raw->count = raw->bad = 0;
    memset(&raw->run, 0, sizeof(raw->run));
}

/* A hello can only have come at the link's rate, so no run has the line;
 * but a nesp32's services are also stopped when it is done with. */
static void deactivate(void *ctx)
{
    nesp_raw_t *raw = ctx;
    if (nesp_raw_owns_line(raw)) {
        raw->hal->line_rate(raw->hal->ctx, NESP_PERIOD);
    }
    raw->phase = IDLE;
    raw->state = NESP_RUN_IDLE;
}

void nesp_raw_service(nesp_service_t *service, nesp_raw_t *raw, nesp_link_t *link,
                      const nesp_hal_t *hal)
{
    memset(raw, 0, sizeof(*raw));
    raw->link = link;
    raw->hal = hal;
    memset(service, 0, sizeof(*service));
    service->id = NESP_SVC_RAW;
    service->name = "RAW";
    service->activate = activate;
    service->deactivate = deactivate;
    service->handle = handle;
    service->tick = tick;
    service->ctx = raw;
}
