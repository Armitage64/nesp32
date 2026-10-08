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

#define HOST_TRACKS_MAX 64
#define HOST_SHOWN_MAX 96
#define HOST_CONN_MAX 256

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
    /* The line with framing off: the caller's, if it gave one. */
    void (*line_rate)(uint8_t period);
    size_t (*line_write)(const uint8_t *data, size_t len);
    bool (*line_idle)(void);
    /* The nesp32's files, and how often they were read. */
    uint16_t track_count;
    struct {
        uint8_t *data;
        size_t len;
    } tracks[HOST_TRACKS_MAX];
    uint32_t track_reads;
    bool answering;                 /* in a feed: a file read now would hold up the reply */
    char shown[2][HOST_SHOWN_MAX];  /* the application's lines of the screen */
    /* The connection to another nesp32. The caller is the network: it says
     * when a call is answered, takes what was sent and gives what comes. */
    uint8_t conn;                   /* NESP_CONN_* */
    uint16_t conn_port;
    uint8_t conn_target[4];
    bool conn_refused;              /* set by the caller: it cannot listen or call */
    size_t conn_room;               /* set by the caller: the most taken at one send; 0 for any */
    uint8_t conn_out[HOST_CONN_MAX];
    size_t conn_out_len;
    uint8_t conn_in[HOST_CONN_MAX];
    size_t conn_in_len;
    uint32_t conn_rtt;              /* set by the caller: microseconds, 0 not known */
    uint8_t note_out[NESP_ARQ_NOTE];    /* the service's latest for the other nesp32 */
    uint32_t notes;                 /* how many it has left */
    uint8_t note_in[NESP_ARQ_NOTE]; /* set by the caller: the other's */
    uint32_t spread[NESP_ARQ_NEEDS];    /* the caller's measurements of the network */
    uint32_t listens;
    uint32_t calls;
    uint32_t closes;
    bool have_last;
    uint8_t last[4];
    uint32_t keeps;
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

static void hal_line_rate(void *ctx, uint8_t period)
{
    host_t *host = ctx;
    if (host->line_rate != NULL) {
        host->line_rate(period);
    }
}

static size_t hal_line_write(void *ctx, const uint8_t *data, size_t len)
{
    host_t *host = ctx;
    return host->line_write != NULL ? host->line_write(data, len) : len;
}

static bool hal_line_idle(void *ctx)
{
    host_t *host = ctx;
    return host->line_idle == NULL || host->line_idle();
}

static uint16_t hal_tracks(void *ctx)
{
    return ((host_t *)ctx)->track_count;
}

static uint32_t hal_track_size(void *ctx, uint16_t track)
{
    host_t *host = ctx;
    return track < host->track_count ? (uint32_t)host->tracks[track].len : 0;
}

/* A nesp32 reads its flash here, which takes a while: a service that did so
 * on the way to a reply would be late with it, and that is caught. */
static size_t hal_track_read(void *ctx, uint16_t track, uint32_t offset, uint8_t *out,
                             size_t len)
{
    host_t *host = ctx;
    if (host->answering) {
        abort();
    }
    host->track_reads++;
    if (track >= host->track_count || offset >= host->tracks[track].len) {
        return 0;
    }
    if (len > host->tracks[track].len - offset) {
        len = host->tracks[track].len - offset;
    }
    memcpy(out, host->tracks[track].data + offset, len);
    return len;
}

static void hal_show(void *ctx, uint8_t row, const char *text)
{
    host_t *host = ctx;
    if (row < 2) {
        snprintf(host->shown[row], sizeof(host->shown[row]), "%s", text);
    }
}

static uint8_t hal_peer_state(void *ctx)
{
    return ((host_t *)ctx)->conn;
}

static bool conn_begin(host_t *host, uint8_t state, uint16_t port)
{
    if (host->conn_refused) {
        return false;
    }
    host->conn = state;
    host->conn_port = port;
    host->conn_out_len = host->conn_in_len = 0;
    return true;
}

static bool hal_peer_listen(void *ctx, uint16_t port)
{
    host_t *host = ctx;
    host->listens++;
    return conn_begin(host, NESP_CONN_LISTENING, port);
}

static bool hal_peer_call(void *ctx, const uint8_t *address, uint16_t port)
{
    host_t *host = ctx;
    host->calls++;
    memcpy(host->conn_target, address, 4);
    return conn_begin(host, NESP_CONN_CALLING, port);
}

static void hal_peer_close(void *ctx)
{
    host_t *host = ctx;
    host->closes++;
    host->conn = NESP_CONN_NONE;
    host->conn_out_len = host->conn_in_len = 0;
}

static size_t hal_peer_send(void *ctx, const uint8_t *data, size_t len)
{
    host_t *host = ctx;
    if (host->conn != NESP_CONN_ANSWERED && host->conn != NESP_CONN_CALLED) {
        return 0;
    }
    if (host->conn_room != 0 && len > host->conn_room) {
        len = host->conn_room;
    }
    if (len > HOST_CONN_MAX - host->conn_out_len) {
        len = HOST_CONN_MAX - host->conn_out_len;
    }
    memcpy(host->conn_out + host->conn_out_len, data, len);
    host->conn_out_len += len;
    return len;
}

static size_t hal_peer_recv(void *ctx, uint8_t *out, size_t max)
{
    host_t *host = ctx;
    if (max > host->conn_in_len) {
        max = host->conn_in_len;
    }
    memcpy(out, host->conn_in, max);
    host->conn_in_len -= max;
    memmove(host->conn_in, host->conn_in + max, host->conn_in_len);
    return max;
}

static uint32_t hal_peer_rtt(void *ctx)
{
    return ((host_t *)ctx)->conn_rtt;
}

static void hal_peer_note(void *ctx, const uint8_t *note)
{
    host_t *host = ctx;
    memcpy(host->note_out, note, NESP_ARQ_NOTE);
    host->notes++;
}

static void hal_peer_noted(void *ctx, uint8_t *note)
{
    memcpy(note, ((host_t *)ctx)->note_in, NESP_ARQ_NOTE);
}

static void hal_peer_spread(void *ctx, uint32_t *counts)
{
    memcpy(counts, ((host_t *)ctx)->spread, sizeof(((host_t *)ctx)->spread));
}

static bool hal_peer_last(void *ctx, uint8_t *address)
{
    host_t *host = ctx;
    if (host->have_last) {
        memcpy(address, host->last, 4);
    }
    return host->have_last;
}

static void hal_peer_keep(void *ctx, const uint8_t *address)
{
    host_t *host = ctx;
    host->have_last = true;
    memcpy(host->last, address, 4);
    host->keeps++;
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
    host->hal.line_rate = hal_line_rate;
    host->hal.line_write = hal_line_write;
    host->hal.line_idle = hal_line_idle;
    host->hal.tracks = hal_tracks;
    host->hal.track_size = hal_track_size;
    host->hal.track_read = hal_track_read;
    host->hal.show = hal_show;
    host->hal.peer_state = hal_peer_state;
    host->hal.peer_listen = hal_peer_listen;
    host->hal.peer_call = hal_peer_call;
    host->hal.peer_close = hal_peer_close;
    host->hal.peer_send = hal_peer_send;
    host->hal.peer_recv = hal_peer_recv;
    host->hal.peer_last = hal_peer_last;
    host->hal.peer_keep = hal_peer_keep;
    host->hal.peer_rtt = hal_peer_rtt;
    host->hal.peer_note = hal_peer_note;
    host->hal.peer_noted = hal_peer_noted;
    host->hal.peer_spread = hal_peer_spread;
    host->battery = 0xFF;
    nesp_stick_init(&host->stick, &host->hal);
    return host;
}

void host_free(host_t *host)
{
    /* As a Stick switched off: whatever its services hold goes with it. */
    uint8_t none[1];
    nesp_link_hello(&host->stick.link, none, 0, NESP_REPLY_MIN, none);
    for (uint16_t index = 0; index < host->track_count; index++) {
        free(host->tracks[index].data);
    }
    free(host);
}

/* out must hold NESP_FRAME_MAX bytes. */
size_t host_feed(host_t *host, const uint8_t *data, size_t len, uint8_t *out)
{
    host->answering = true;
    size_t sent = nesp_stick_feed(&host->stick, data, len, out);
    host->answering = false;
    return sent;
}

/* The clock, in milliseconds: what the services do between requests. */
bool host_tick(host_t *host, uint32_t now_ms)
{
    return nesp_stick_tick(&host->stick, now_ms);
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

void host_set_line(host_t *host, void (*rate)(uint8_t), size_t (*write)(const uint8_t *, size_t),
                   bool (*idle)(void))
{
    host->line_rate = rate;
    host->line_write = write;
    host->line_idle = idle;
}

/* A file on the nesp32, after the ones already there. Asked for by a
 * service only at its next hello. */
bool host_track_add(host_t *host, const uint8_t *data, size_t len)
{
    if (host->track_count == HOST_TRACKS_MAX) {
        return false;
    }
    uint8_t *copy = malloc(len != 0 ? len : 1);
    memcpy(copy, data, len);
    host->tracks[host->track_count].data = copy;
    host->tracks[host->track_count].len = len;
    host->track_count++;
    return true;
}

/* A file that has gone bad since it was listed: it reads as this much. */
void host_track_cut(host_t *host, uint16_t track, size_t len)
{
    if (track < host->track_count && len < host->tracks[track].len) {
        host->tracks[track].len = len;
    }
}

/* What a nesp32 would have in a file of settings, if it had one. */
void host_juke_set(host_t *host, uint8_t loops, bool repeat)
{
    host->stick.juke.loops = loops;
    host->stick.juke.repeat = repeat;
}

/* --- the connection to another nesp32: the caller is the network -------------- */

uint8_t host_conn(const host_t *host) { return host->conn; }
uint16_t host_conn_port(const host_t *host) { return host->conn_port; }
void host_conn_target(const host_t *host, uint8_t *out) { memcpy(out, host->conn_target, 4); }
void host_conn_set(host_t *host, uint8_t state) { host->conn = state; }
void host_conn_refuse(host_t *host, bool refused) { host->conn_refused = refused; }
void host_conn_room(host_t *host, size_t bytes) { host->conn_room = bytes; }
uint32_t host_listens(const host_t *host) { return host->listens; }
uint32_t host_calls(const host_t *host) { return host->calls; }
uint32_t host_closes(const host_t *host) { return host->closes; }
uint32_t host_keeps(const host_t *host) { return host->keeps; }

/* What the nesp32 has sent to the other, and not yet been taken. */
size_t host_conn_take(host_t *host, uint8_t *out, size_t max)
{
    if (max > host->conn_out_len) {
        max = host->conn_out_len;
    }
    memcpy(out, host->conn_out, max);
    host->conn_out_len -= max;
    memmove(host->conn_out, host->conn_out + max, host->conn_out_len);
    return max;
}

/* Bytes from the other nesp32. Returns how many there was room for. */
size_t host_conn_give(host_t *host, const uint8_t *data, size_t len)
{
    if (len > HOST_CONN_MAX - host->conn_in_len) {
        len = HOST_CONN_MAX - host->conn_in_len;
    }
    memcpy(host->conn_in + host->conn_in_len, data, len);
    host->conn_in_len += len;
    return len;
}

/* The address a nesp32 has kept from before it was switched on, if any. */
void host_set_last(host_t *host, const uint8_t *address)
{
    host->have_last = address != NULL;
    if (address != NULL) {
        memcpy(host->last, address, 4);
    }
}

bool host_last(const host_t *host, uint8_t *out)
{
    memcpy(out, host->last, 4);
    return host->have_last;
}

void host_conn_rtt(host_t *host, uint32_t microseconds) { host->conn_rtt = microseconds; }
/* A measurement of the network's time, there and back, `times` over. */
void host_conn_took(host_t *host, uint32_t microseconds, uint32_t times)
{
    uint32_t ticks = nesp_arq_ticks(microseconds);
    host->spread[(ticks > NESP_ARQ_NEEDS ? NESP_ARQ_NEEDS : ticks) - 1] += times;
}
uint32_t host_notes(const host_t *host) { return host->notes; }
void host_note_take(const host_t *host, uint8_t *out) { memcpy(out, host->note_out, NESP_ARQ_NOTE); }
void host_note_give(host_t *host, const uint8_t *note) { memcpy(host->note_in, note, NESP_ARQ_NOTE); }

/* --- the stream over datagrams, on its own (arq.c) ------------------------------ */

nesp_arq_t *host_arq_new(uint32_t session)
{
    nesp_arq_t *arq = malloc(sizeof(*arq));
    if (arq != NULL) {
        nesp_arq_open(arq, session);
    }
    return arq;
}

void host_arq_free(nesp_arq_t *arq) { free(arq); }
size_t host_arq_write(nesp_arq_t *arq, const uint8_t *data, size_t len)
{
    return nesp_arq_write(arq, data, len);
}
size_t host_arq_read(nesp_arq_t *arq, uint8_t *out, size_t max)
{
    return nesp_arq_read(arq, out, max);
}
bool host_arq_due(const nesp_arq_t *arq, uint32_t now) { return nesp_arq_due(arq, now); }
size_t host_arq_packet(nesp_arq_t *arq, uint8_t kind, uint32_t now, uint8_t *out)
{
    return nesp_arq_packet(arq, kind, now, out);
}
int host_arq_take(nesp_arq_t *arq, uint32_t now, const uint8_t *data, size_t len)
{
    return nesp_arq_take(arq, now, data, len);
}
uint32_t host_arq_rtt(const nesp_arq_t *arq) { return arq->rtt; }
uint32_t host_arq_rtt_last(const nesp_arq_t *arq) { return arq->rtt_last; }
uint8_t host_arq_unsaid(const nesp_arq_t *arq) { return arq->out_len; }
uint32_t host_arq_last_at(const nesp_arq_t *arq) { return arq->last_at; }
uint32_t host_arq_rtt_count(const nesp_arq_t *arq) { return arq->rtt_count; }
void host_arq_note(nesp_arq_t *arq, const uint8_t *note) { memcpy(arq->note_out, note, NESP_ARQ_NOTE); }
void host_arq_noted(const nesp_arq_t *arq, uint8_t *out) { memcpy(out, arq->note_in, NESP_ARQ_NOTE); }

uint32_t host_peer_requests(const host_t *host) { return host->stick.peer.requests; }
uint32_t host_peer_repeats(const host_t *host) { return host->stick.peer.repeats; }
uint8_t host_peer_lobby(const host_t *host) { return host->stick.peer.lobby; }

/* --- what happened ---------------------------------------------------------- */

uint32_t host_track_reads(const host_t *host) { return host->track_reads; }
const char *host_shown(const host_t *host, uint8_t row) { return host->shown[row & 1]; }
uint16_t host_juke_index(const host_t *host) { return host->stick.juke.index; }
uint32_t host_juke_resent(const host_t *host) { return host->stick.juke.resent; }
uint32_t host_juke_underruns(const host_t *host) { return host->stick.juke.underruns; }
uint8_t host_raw_state(const host_t *host) { return host->stick.raw.state; }

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
