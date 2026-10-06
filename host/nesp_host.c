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
    host->battery = 0xFF;
    nesp_stick_init(&host->stick, &host->hal);
    return host;
}

void host_free(host_t *host)
{
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
