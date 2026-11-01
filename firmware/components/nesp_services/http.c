/* HTTP: any address the console names, fetched with a GET, and the reply as
 * it came (docs/PROTOCOL.md). For a ROM that wants something from the
 * Internet that no other service lays out for it, and for the sample that
 * shows how (samplecode/https).
 *
 * URL sets the address, in pieces as TUNER's URL does. GET fetches it, and
 * carries an id: a GET whose id is not the last one's starts a fetch, and
 * the same one again only says how it stands, so the console sends it
 * until it is answered. STATE says how it stands: the reply's status, its
 * Content-Type and Content-Length once the server has answered, how much
 * of the body is held, and how long it has taken. READ hands over the
 * body that is held, from an offset.
 *
 * The first NESP_HTTP_KEEP bytes of the body are held and the rest is not
 * read: the console has 2 KB of memory, and a screen of 960 tiles. Every
 * status is a reply, not only a 200: a 404's body is held as a 200's is.
 *
 * Two tasks meet here, as in wiki.c: the link's runs handle() and tick(),
 * the fetch's runs the sink, and what both touch is under the hal's lock.
 * `generation` is which fetch the reply held is from, and an older one's
 * bytes are refused.
 */
#include <string.h>

#include "nesp_services.h"

#define AGENT "nesp32 (a network interface for the NES; github.com/Armitage64/nesp32)"
#define STATE_FIXED 12              /* STATE's reply before its text */
#define READ_FIXED 3                /* and READ's before its bytes */
#define MS_MOST 0xFFFF

static void lock(nesp_http_t *http)
{
    http->hal->lock(http->hal->ctx);
}

static void unlock(nesp_http_t *http)
{
    http->hal->unlock(http->hal->ctx);
}

/* text, cut to fit, as the reply's words. Called locked. */
static void set_text(nesp_http_t *http, const char *text)
{
    size_t len = text != NULL ? strlen(text) : 0;
    if (len > NESP_HTTP_TEXT_MAX) {
        len = NESP_HTTP_TEXT_MAX;
    }
    memcpy(http->text, text, len);
    http->text[len] = '\0';
}

/* --- the fetch's task ---------------------------------------------------------- */

static void head(void *ctx, uint32_t id, uint16_t status, const char *type, uint32_t length)
{
    nesp_http_t *http = ctx;
    lock(http);
    if (http->generation == id) {
        http->state = NESP_FETCH_READING;
        http->status = status;
        http->length = length;
        set_text(http, type);
    }
    unlock(http);
}

static bool body(void *ctx, uint32_t id, const uint8_t *data, size_t len)
{
    nesp_http_t *http = ctx;
    bool more = false;
    lock(http);
    if (http->generation == id) {
        size_t room = NESP_HTTP_KEEP - http->held;
        if (len > room) {
            len = room;
        }
        memcpy(http->body + http->held, data, len);
        http->held = (uint16_t)(http->held + len);
        more = http->held < NESP_HTTP_KEEP;
    }
    unlock(http);
    return more;                    /* false, and the fetch is over: done says so */
}

static void done(void *ctx, uint32_t id, bool ok, const char *why)
{
    nesp_http_t *http = ctx;
    lock(http);
    if (http->generation == id) {
        if (ok) {
            http->state = NESP_FETCH_DONE;
        } else {
            http->state = NESP_FETCH_FAILED;
            set_text(http, why != NULL && why[0] != '\0' ? why : "THE FETCH FAILED");
        }
    }
    unlock(http);
}

/* --- the link's task ----------------------------------------------------------- */

static bool over(uint8_t state)
{
    return state == NESP_FETCH_NO_WIFI || state == NESP_FETCH_DONE
           || state == NESP_FETCH_FAILED;
}

static void begin(nesp_http_t *http)
{
    nesp_wifi_t wifi;
    memset(&wifi, 0, sizeof(wifi));
    http->hal->wifi(http->hal->ctx, &wifi);
    bool online = wifi.state == NESP_WIFI_JOINED;

    lock(http);
    http->generation++;             /* whatever was being fetched is no longer wanted */
    http->state = online ? NESP_FETCH_ASKING : NESP_FETCH_NO_WIFI;
    http->status = 0;
    http->length = NESP_HTTP_LENGTH_UNKNOWN;
    http->held = 0;
    set_text(http, "");
    uint32_t id = http->generation;
    unlock(http);
    http->began = http->now;
    http->timed = false;
    if (!online) {
        http->hal->fetch_stop(http->hal->ctx);
    } else if (!http->hal->fetch(http->hal->ctx, http->url, AGENT, id, &http->sink)) {
        lock(http);
        http->state = NESP_FETCH_FAILED;
        set_text(http, "THE NESP32 IS BUSY");
        unlock(http);
    }
}

/* The reply of GET and STATE: STATE, ID, STATUS (2), LENGTH (4), HELD (2),
 * MS (2), and the Content-Type or why it failed. */
static void tell(nesp_http_t *http, nesp_reply_t *reply)
{
    lock(http);
    uint8_t state = http->state;
    uint16_t status = http->status;
    uint32_t length = http->length;
    uint16_t held = http->held;
    size_t len = strlen(http->text);
    if (len > (size_t)(reply->max - STATE_FIXED)) {
        len = (size_t)(reply->max - STATE_FIXED);
    }
    memcpy(reply->data + STATE_FIXED, http->text, len);
    unlock(http);
    uint32_t ms = 0;
    if (http->got && state != NESP_FETCH_IDLE) {
        ms = http->timed ? http->took : http->now - http->began;
    }
    if (ms > MS_MOST) {
        ms = MS_MOST;
    }
    uint8_t *data = reply->data;
    data[0] = state;
    data[1] = http->get_id;
    data[2] = (uint8_t)status;
    data[3] = (uint8_t)(status >> 8);
    for (int index = 0; index < 4; index++) {
        data[4 + index] = (uint8_t)(length >> (8 * index));
    }
    data[8] = (uint8_t)held;
    data[9] = (uint8_t)(held >> 8);
    data[10] = (uint8_t)ms;
    data[11] = (uint8_t)(ms >> 8);
    reply->len = (uint8_t)(STATE_FIXED + len);
    reply->once = true;             /* the same request again asks how it stands now */
}

/* URL: AT, then the address from there to its end. What was set before AT
 * stays, and AT may be no further than its end, so a long address goes in
 * pieces, in order. */
static bool set_url(nesp_http_t *http, const nesp_request_t *request)
{
    if (request->len < 1) {
        return false;
    }
    size_t at = request->data[0];
    size_t len = (size_t)request->len - 1;
    if (at > strlen(http->url) || at + len > NESP_HTTP_URL_MAX
        || memchr(request->data + 1, 0, len) != NULL) {
        return false;
    }
    memcpy(http->url + at, request->data + 1, len);
    http->url[at + len] = '\0';
    return true;
}

static void read_body(nesp_http_t *http, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len != 3) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    uint16_t offset = (uint16_t)(request->data[0] | request->data[1] << 8);
    size_t count = request->data[2];
    if (count > (size_t)(reply->max - READ_FIXED)) {
        count = (size_t)(reply->max - READ_FIXED);
    }
    lock(http);
    uint8_t state = http->state;
    size_t held = http->held;
    size_t len = offset < held ? held - offset : 0;
    if (len > count) {
        len = count;
    }
    memcpy(reply->data + READ_FIXED, http->body + offset, len);
    unlock(http);
    reply->data[0] = state;
    reply->data[1] = request->data[0];
    reply->data[2] = request->data[1];
    reply->len = (uint8_t)(READ_FIXED + len);
    reply->once = true;             /* bytes not held yet may be by the next time */
}

static void handle(void *ctx, const nesp_request_t *request, nesp_reply_t *reply)
{
    nesp_http_t *http = ctx;
    switch (request->op) {
    case NESP_HTTP_URL:
        if (!set_url(http, request)) {
            reply->status = NESP_ST_BAD_ARG;
            return;
        }
        lock(http);
        reply->data[0] = http->state;
        unlock(http);
        reply->len = 1;
        break;
    case NESP_HTTP_GET:
        if (request->len != 1 || http->url[0] == '\0') {
            reply->status = NESP_ST_BAD_ARG;
            return;
        }
        if (!http->got || request->data[0] != http->get_id) {
            http->got = true;
            http->get_id = request->data[0];
            begin(http);
        }
        tell(http, reply);
        break;
    case NESP_HTTP_STATE:
        tell(http, reply);
        break;
    case NESP_HTTP_READ:
        read_body(http, request, reply);
        break;
    default:
        reply->status = NESP_ST_NO_OP;
        break;
    }
}

/* The clock, and how long the fetch took, once it is over. */
static bool tick(void *ctx, uint32_t now_ms)
{
    nesp_http_t *http = ctx;
    http->now = now_ms;
    if (http->got && !http->timed) {
        lock(http);
        bool ended = over(http->state);
        unlock(http);
        if (ended) {
            http->took = now_ms - http->began;
            http->timed = true;
        }
    }
    return false;
}

/* A hello has asked for the service, or another ROM is on the console:
 * no address, and nothing held. */
static void reset(void *ctx)
{
    nesp_http_t *http = ctx;
    http->hal->fetch_stop(http->hal->ctx);
    lock(http);
    http->generation++;             /* a fetch still on its way adds nothing */
    http->state = NESP_FETCH_IDLE;
    http->status = 0;
    http->length = NESP_HTTP_LENGTH_UNKNOWN;
    http->held = 0;
    set_text(http, "");
    unlock(http);
    http->url[0] = '\0';
    http->got = false;
    http->get_id = 0;
    http->timed = false;
}

void nesp_http_service(nesp_service_t *service, nesp_http_t *http, const nesp_hal_t *hal)
{
    memset(http, 0, sizeof(*http));
    http->hal = hal;
    http->length = NESP_HTTP_LENGTH_UNKNOWN;
    http->sink.ctx = http;
    http->sink.body = body;
    http->sink.done = done;
    http->sink.head = head;
    memset(service, 0, sizeof(*service));
    service->id = NESP_SVC_HTTP;
    service->name = "HTTP";
    service->activate = reset;
    service->deactivate = reset;
    service->handle = handle;
    service->tick = tick;
    service->ctx = http;
}
