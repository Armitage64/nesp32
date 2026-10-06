/* A Stick on a computer: the firmware's own link and services, with a
 * stand-in for the hardware that the caller sets up and looks into.
 *
 * Built as a shared library (make host) and loaded by host/nesp.py. The
 * tests run the console's ROMs against it; with a serial cable on
 * controller port 2 it can stand in for a Stick on a real console.
 *
 * Nothing here decides anything over time. A scan that is started stays
 * RUNNING until the caller says it is done, and a join stays JOINING until
 * the caller says how it went, so a test says exactly when.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "nesp_services.h"

typedef struct {
    nesp_stick_t stick;
    nesp_hal_t hal;
    nesp_wifi_t wifi;
    uint8_t battery;
    bool time_known;
    uint32_t seconds;
    uint8_t scan_state;
    uint8_t scan_count;
    nesp_network_t networks[NESP_SCAN_MAX];
    uint32_t scans;                 /* scans started */
    uint32_t joins;                 /* joins asked for */
    uint32_t forgets;
    char password[NESP_PASSWORD_MAX];   /* of the last join */
    uint8_t password_len;
    char app[NESP_APP_ID];
    uint8_t app_version;
    uint32_t hellos;
    /* The last fetch asked for, and where its reply goes. */
    char url[512];
    char agent[128];
    uint32_t fetch_id;
    const nesp_sink_t *sink;
    bool fetching;
    bool fetch_refused;             /* set by the caller: the next fetch cannot start */
    uint32_t fetches;
    uint32_t fetch_stops;
    size_t alloc_most;              /* set by the caller: no more than this at once; 0 for any */
    uint32_t allocated;             /* blocks handed out and not given back */
    int locked;
} host_t;

static uint8_t hal_board(void *ctx)
{
    (void)ctx;
    return NESP_BOARD_HOST;
}

static const char *hal_board_name(void *ctx)
{
    (void)ctx;
    return "Computer";
}

static uint8_t hal_battery(void *ctx)
{
    return ((host_t *)ctx)->battery;
}

static bool hal_time(void *ctx, uint32_t *seconds)
{
    host_t *host = ctx;
    *seconds = host->seconds;
    return host->time_known;
}

static void hal_wifi(void *ctx, nesp_wifi_t *out)
{
    *out = ((host_t *)ctx)->wifi;
}

static bool hal_scan_start(void *ctx)
{
    host_t *host = ctx;
    if (host->scan_state == NESP_SCAN_RUNNING) {
        return true;                /* already at it */
    }
    host->scan_state = NESP_SCAN_RUNNING;
    host->scans++;
    return true;
}

static uint8_t hal_scan_state(void *ctx, uint8_t *count)
{
    host_t *host = ctx;
    *count = host->scan_state == NESP_SCAN_DONE ? host->scan_count : 0;
    return host->scan_state;
}

static bool hal_scan_result(void *ctx, uint8_t index, nesp_network_t *out)
{
    host_t *host = ctx;
    if (host->scan_state != NESP_SCAN_DONE || index >= host->scan_count) {
        return false;
    }
    *out = host->networks[index];
    return true;
}

static bool hal_join(void *ctx, const char *name, uint8_t name_len,
                     const char *password, uint8_t password_len)
{
    host_t *host = ctx;
    memset(&host->wifi, 0, sizeof(host->wifi));
    host->wifi.state = NESP_WIFI_JOINING;
    host->wifi.name_len = name_len;
    memcpy(host->wifi.name, name, name_len);
    host->password_len = password_len;
    memcpy(host->password, password, password_len);
    host->joins++;
    return true;
}

static void hal_forget(void *ctx)
{
    host_t *host = ctx;
    memset(&host->wifi, 0, sizeof(host->wifi));
    host->wifi.state = NESP_WIFI_NONE;
    host->forgets++;
}

static void hal_app(void *ctx, const char *id, uint8_t version)
{
    host_t *host = ctx;
    memcpy(host->app, id, NESP_APP_ID);
    host->app_version = version;
    host->hellos++;
}

static bool hal_fetch(void *ctx, const char *url, const char *agent, uint32_t id,
                      const nesp_sink_t *sink)
{
    host_t *host = ctx;
    if (host->fetch_refused) {
        return false;
    }
    snprintf(host->url, sizeof(host->url), "%s", url);
    snprintf(host->agent, sizeof(host->agent), "%s", agent);
    host->fetch_id = id;
    host->sink = sink;
    host->fetching = true;
    host->fetches++;
    return true;
}

static void hal_fetch_stop(void *ctx)
{
    host_t *host = ctx;
    host->fetching = false;
    host->fetch_stops++;
}

static void *hal_alloc(void *ctx, size_t bytes)
{
    host_t *host = ctx;
    if (host->alloc_most != 0 && bytes > host->alloc_most) {
        return NULL;
    }
    host->allocated++;
    return malloc(bytes);
}

static void hal_release(void *ctx, void *memory)
{
    host_t *host = ctx;
    host->allocated--;
    free(memory);
}

/* One task here, so there is nothing to keep out; but a lock taken twice,
 * or left taken, would hang a Stick, and that is caught. */
static void hal_lock(void *ctx)
{
    host_t *host = ctx;
    if (host->locked != 0) {
        abort();
    }
    host->locked = 1;
}

static void hal_unlock(void *ctx)
{
    host_t *host = ctx;
    if (host->locked != 1) {
        abort();
    }
    host->locked = 0;
}

host_t *host_new(void)
{
    host_t *host = calloc(1, sizeof(*host));
    if (host == NULL) {
        return NULL;
    }
    host->hal.ctx = host;
    host->hal.board = hal_board;
    host->hal.board_name = hal_board_name;
    host->hal.battery = hal_battery;
    host->hal.time = hal_time;
    host->hal.wifi = hal_wifi;
    host->hal.scan_start = hal_scan_start;
    host->hal.scan_state = hal_scan_state;
    host->hal.scan_result = hal_scan_result;
    host->hal.join = hal_join;
    host->hal.forget = hal_forget;
    host->hal.app = hal_app;
    host->hal.fetch = hal_fetch;
    host->hal.fetch_stop = hal_fetch_stop;
    host->hal.alloc = hal_alloc;
    host->hal.release = hal_release;
    host->hal.lock = hal_lock;
    host->hal.unlock = hal_unlock;
    host->battery = 0xFF;
    nesp_stick_init(&host->stick, &host->hal);
    return host;
}

void host_free(host_t *host)
{
    /* As a Stick switched off: whatever its services hold goes with it. */
    uint8_t none[1];
    nesp_link_hello(&host->stick.link, none, 0, NESP_REPLY_MIN, none);
    free(host);
}

/* out must hold NESP_FRAME_MAX bytes. */
size_t host_feed(host_t *host, const uint8_t *data, size_t len, uint8_t *out)
{
    return nesp_link_feed(&host->stick.link, data, len, out);
}

void host_event(host_t *host, uint8_t code, uint8_t arg)
{
    nesp_stick_event(&host->stick, code, arg);
}

void host_note_turnaround(host_t *host, uint32_t microseconds)
{
    nesp_link_note_turnaround(&host->stick.link, microseconds);
}

/* --- what the stand-in hardware says --------------------------------------- */

void host_set_wifi(host_t *host, uint8_t state, uint8_t why, int8_t rssi,
                   const uint8_t *address)
{
    host->wifi.state = state;
    host->wifi.why = why;
    host->wifi.rssi = rssi;
    memcpy(host->wifi.address, address, 4);
}

void host_set_saved(host_t *host, const char *name, uint8_t name_len)
{
    host->wifi.name_len = name_len;
    memcpy(host->wifi.name, name, name_len);
}

void host_set_battery(host_t *host, uint8_t percent)
{
    host->battery = percent;
}

void host_set_time(host_t *host, bool known, uint32_t seconds)
{
    host->time_known = known;
    host->seconds = seconds;
}

void host_scan_clear(host_t *host)
{
    host->scan_count = 0;
}

bool host_scan_add(host_t *host, const char *name, uint8_t name_len, int8_t rssi,
                   uint8_t auth, uint8_t channel)
{
    if (host->scan_count == NESP_SCAN_MAX || name_len > NESP_NAME_MAX) {
        return false;
    }
    nesp_network_t *network = &host->networks[host->scan_count++];
    memset(network, 0, sizeof(*network));
    network->rssi = rssi;
    network->auth = auth;
    network->channel = channel;
    network->name_len = name_len;
    memcpy(network->name, name, name_len);
    return true;
}

void host_scan_finish(host_t *host, uint8_t state)
{
    host->scan_state = state;
}

/* --- what happened ---------------------------------------------------------- */

uint8_t host_scan_state(const host_t *host) { return host->scan_state; }
uint32_t host_scans(const host_t *host) { return host->scans; }
uint32_t host_joins(const host_t *host) { return host->joins; }
uint32_t host_forgets(const host_t *host) { return host->forgets; }
uint32_t host_hellos(const host_t *host) { return host->hellos; }
uint8_t host_wifi_state(const host_t *host) { return host->wifi.state; }
uint8_t host_app_version(const host_t *host) { return host->app_version; }

uint8_t host_joined_name(const host_t *host, char *out)
{
    memcpy(out, host->wifi.name, host->wifi.name_len);
    return host->wifi.name_len;
}

uint8_t host_joined_password(const host_t *host, char *out)
{
    memcpy(out, host->password, host->password_len);
    return host->password_len;
}

void host_app(const host_t *host, char *out)
{
    memcpy(out, host->app, NESP_APP_ID);
}

bool host_active(const host_t *host, uint8_t service)
{
    return nesp_link_active(&host->stick.link, service);
}

/* 0 requests, 1 repeats, 2 dropped, 3 noise. */
uint32_t host_counter(const host_t *host, int which)
{
    const nesp_counters_t *counters = &host->stick.link.counters;
    switch (which) {
    case 0: return counters->requests;
    case 1: return counters->repeats;
    case 2: return counters->dropped;
    case 3: return counters->noise;
    default: return 0;
    }
}

void host_checks(const uint8_t *data, size_t len, uint8_t *out)
{
    nesp_checks(data, len, out, out + 1);
}

void host_pattern(uint16_t seed, uint8_t *out, size_t count)
{
    nesp_pattern(seed, out, count);
}

/* --- fetches: the caller is the Internet ------------------------------------- */

uint32_t host_fetches(const host_t *host) { return host->fetches; }
uint32_t host_fetch_stops(const host_t *host) { return host->fetch_stops; }
uint32_t host_fetch_id(const host_t *host) { return host->fetch_id; }
bool host_fetching(const host_t *host) { return host->fetching; }
const char *host_fetch_url(const host_t *host) { return host->url; }
const char *host_fetch_agent(const host_t *host) { return host->agent; }
uint32_t host_allocated(const host_t *host) { return host->allocated; }
void host_set_fetch_refused(host_t *host, bool refused) { host->fetch_refused = refused; }
void host_set_alloc_most(host_t *host, size_t bytes) { host->alloc_most = bytes; }

/* More of the reply to the fetch with this id, which need not be the last
 * one asked for: a fetch that was replaced may still have bytes on their
 * way. Returns what the sink said: whether it wants more. */
bool host_fetch_body(host_t *host, uint32_t id, const uint8_t *data, size_t len)
{
    return host->sink != NULL && host->sink->body(host->sink->ctx, id, data, len);
}

void host_fetch_done(host_t *host, uint32_t id, bool ok, const char *why)
{
    if (host->sink != NULL) {
        host->sink->done(host->sink->ctx, id, ok, why);
    }
    if (id == host->fetch_id) {
        host->fetching = false;
    }
}

/* --- the text code, without a Stick round it ---------------------------------- */

int host_to_ascii(uint32_t code, char *out)
{
    return nesp_to_ascii(code, out);
}

size_t host_wiki_url(const uint8_t *query, size_t len, char *out, size_t max)
{
    return nesp_wiki_url(query, len, out, max);
}

/* A wrapper, and the lines it has laid out: each the width, padded with
 * spaces, a heading's characters with NESP_HEADING set. */
typedef struct {
    nesp_wrap_t wrap;
    uint8_t width;
    size_t count;
    size_t room;
    uint8_t *lines;
} host_wrap_t;

static bool wrap_add(void *ctx, const uint8_t *text, size_t len, uint8_t flags)
{
    host_wrap_t *out = ctx;
    if (out->count == out->room) {
        out->room = out->room != 0 ? 2 * out->room : 64;
        out->lines = realloc(out->lines, out->room * out->width);
    }
    uint8_t *line = out->lines + out->count * out->width;
    for (size_t index = 0; index < out->width; index++) {
        line[index] = index < len ? (uint8_t)(text[index] | flags) : ' ';
    }
    out->count++;
    return true;
}

host_wrap_t *host_wrap_new(uint8_t width)
{
    host_wrap_t *out = calloc(1, sizeof(*out));
    out->width = width;
    nesp_wrap_init(&out->wrap, width, wrap_add, out);
    return out;
}

void host_wrap_free(host_wrap_t *out)
{
    free(out->lines);
    free(out);
}

void host_wrap_title(host_wrap_t *out, const uint8_t *text, size_t len)
{
    nesp_wrap_title(&out->wrap, text, len);
}

void host_wrap_put(host_wrap_t *out, const uint8_t *data, size_t len)
{
    nesp_wrap_put(&out->wrap, data, len);
}

void host_wrap_close(host_wrap_t *out)
{
    nesp_wrap_close(&out->wrap);
}

size_t host_wrap_count(const host_wrap_t *out) { return out->count; }
size_t host_wrap_held(const host_wrap_t *out) { return out->wrap.len; }
const uint8_t *host_wrap_lines(const host_wrap_t *out) { return out->lines; }

/* An extractor, and what it has found. */
typedef struct {
    nesp_extract_t extract;
    int titles;
    size_t title_len;
    uint8_t title[NESP_TITLE_MAX];
    size_t text_len;
    size_t text_room;
    uint8_t *text;
} host_extract_t;

static void extract_title(void *ctx, const uint8_t *text, size_t len)
{
    host_extract_t *out = ctx;
    out->titles++;
    out->title_len = len;
    memcpy(out->title, text, len);
}

static void extract_text(void *ctx, const uint8_t *data, size_t len)
{
    host_extract_t *out = ctx;
    if (out->text_len + len > out->text_room) {
        out->text_room = 2 * (out->text_len + len) + 256;
        out->text = realloc(out->text, out->text_room);
    }
    memcpy(out->text + out->text_len, data, len);
    out->text_len += len;
}

host_extract_t *host_extract_new(void)
{
    host_extract_t *out = calloc(1, sizeof(*out));
    nesp_extract_init(&out->extract, extract_title, extract_text, out);
    return out;
}

void host_extract_free(host_extract_t *out)
{
    free(out->text);
    free(out);
}

void host_extract_feed(host_extract_t *out, const uint8_t *data, size_t len)
{
    nesp_extract_feed(&out->extract, data, len);
}

int host_extract_titles(const host_extract_t *out) { return out->titles; }
size_t host_extract_title(const host_extract_t *out, uint8_t *to)
{
    memcpy(to, out->title, out->title_len);
    return out->title_len;
}
size_t host_extract_text_len(const host_extract_t *out) { return out->text_len; }
const uint8_t *host_extract_text(const host_extract_t *out) { return out->text; }
bool host_extract_found(const host_extract_t *out) { return out->extract.found; }
bool host_extract_done(const host_extract_t *out) { return out->extract.done; }
