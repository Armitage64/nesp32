/* SYS: who the console is, and how the Stick is (docs/PROTOCOL.md). */
#include <string.h>

#include "nesp_services.h"

/* A hello's payload: protocol, application id, its version, the longest
 * reply payload the ROM takes, then the services it needs. */
#define HELLO_FIXED (3 + NESP_APP_ID)

static uint8_t put_text(nesp_reply_t *reply, const char *text, size_t length)
{
    if (length > reply->max) {
        length = reply->max;
    }
    memcpy(reply->data, text, length);
    return (uint8_t)length;
}

static void hello(nesp_sys_t *sys, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len < HELLO_FIXED) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    const uint8_t *data = request->data;
    uint8_t wanted = (uint8_t)(request->len - HELLO_FIXED);
    uint8_t missing[NESP_PAYLOAD_MAX];
    uint8_t missed = nesp_link_hello(sys->link, data + HELLO_FIXED, wanted,
                                     data[2 + NESP_APP_ID], missing);
    memcpy(sys->app, data + 1, NESP_APP_ID);
    sys->app_version = data[1 + NESP_APP_ID];
    sys->event_first = sys->event_count = 0;
    nesp_link_set_attention(sys->link, false);
    if (sys->hal->app != NULL) {
        sys->hal->app(sys->hal->ctx, sys->app, sys->app_version);
    }

    /* The reply is made to fit what the ROM took before this hello. */
    uint8_t *out = reply->data;
    out[0] = NESP_PROTOCOL;
    out[1] = NESP_FIRMWARE_MAJOR;
    out[2] = NESP_FIRMWARE_MINOR;
    out[3] = NESP_FIRMWARE_PATCH;
    out[4] = sys->hal->board(sys->hal->ctx);
    out[5] = NESP_PAYLOAD_MAX;          /* the longest request payload taken */
    if (missed > reply->max - 7) {
        missed = (uint8_t)(reply->max - 7);
    }
    out[6] = missed;
    memcpy(out + 7, missing, missed);
    reply->len = (uint8_t)(7 + missed);
    if (data[0] != NESP_PROTOCOL) {
        reply->status = NESP_ST_VERSION;
    } else if (missed != 0) {
        reply->status = NESP_ST_NO_SERVICE;
    }
}

static void status(nesp_sys_t *sys, nesp_reply_t *reply)
{
    nesp_wifi_t wifi;
    memset(&wifi, 0, sizeof(wifi));
    sys->hal->wifi(sys->hal->ctx, &wifi);
    uint8_t *out = reply->data;
    out[0] = wifi.state;
    out[1] = (uint8_t)wifi.rssi;
    memcpy(out + 2, wifi.address, 4);
    out[6] = sys->hal->battery(sys->hal->ctx);
    out[7] = sys->event_count;
    reply->len = 8;
}

static void info(nesp_sys_t *sys, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len != 1) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    switch (request->data[0]) {
    case NESP_INFO_FIRMWARE:
        reply->len = put_text(reply, NESP_FIRMWARE_TEXT, strlen(NESP_FIRMWARE_TEXT));
        break;
    case NESP_INFO_BOARD: {
        const char *name = sys->hal->board_name(sys->hal->ctx);
        reply->len = put_text(reply, name, strlen(name));
        break;
    }
    case NESP_INFO_NETWORK: {
        nesp_wifi_t wifi;
        memset(&wifi, 0, sizeof(wifi));
        sys->hal->wifi(sys->hal->ctx, &wifi);
        reply->len = put_text(reply, wifi.name, wifi.name_len);
        break;
    }
    case NESP_INFO_APP:
        reply->len = put_text(reply, sys->app, NESP_APP_ID);
        break;
    default:
        reply->status = NESP_ST_NOT_FOUND;
        break;
    }
}

static void event(nesp_sys_t *sys, nesp_reply_t *reply)
{
    reply->data[0] = NESP_EVENT_NONE;
    reply->data[1] = 0;
    reply->len = 2;
    if (sys->event_count != 0) {
        reply->data[0] = sys->events[sys->event_first][0];
        reply->data[1] = sys->events[sys->event_first][1];
        sys->event_first = (uint8_t)((sys->event_first + 1) % NESP_EVENT_QUEUE);
        sys->event_count--;
    }
    nesp_link_set_attention(sys->link, sys->event_count != 0);
}

static void handle(void *ctx, const nesp_request_t *request, nesp_reply_t *reply)
{
    nesp_sys_t *sys = ctx;
    switch (request->op) {
    case NESP_SYS_HELLO:
        hello(sys, request, reply);
        break;
    case NESP_SYS_STATUS:
        status(sys, reply);
        break;
    case NESP_SYS_ECHO:
        reply->len = put_text(reply, (const char *)request->data, request->len);
        break;
    case NESP_SYS_INFO:
        info(sys, request, reply);
        break;
    case NESP_SYS_TIME: {
        uint32_t seconds = 0;
        bool known = sys->hal->time(sys->hal->ctx, &seconds);
        reply->data[0] = known ? 1 : 0;
        reply->data[1] = (uint8_t)seconds;
        reply->data[2] = (uint8_t)(seconds >> 8);
        reply->data[3] = (uint8_t)(seconds >> 16);
        reply->data[4] = (uint8_t)(seconds >> 24);
        reply->len = 5;
        break;
    }
    case NESP_SYS_EVENT:
        event(sys, reply);
        break;
    default:
        reply->status = NESP_ST_NO_OP;
        break;
    }
}

void nesp_sys_service(nesp_service_t *service, nesp_sys_t *sys, nesp_link_t *link,
                      const nesp_hal_t *hal)
{
    memset(sys, 0, sizeof(*sys));
    sys->link = link;
    sys->hal = hal;
    memset(sys->app, ' ', NESP_APP_ID);
    memset(service, 0, sizeof(*service));
    service->id = NESP_SVC_SYS;
    service->name = "SYS";
    service->handle = handle;
    service->ctx = sys;
    service->always = true;
}

void nesp_stick_event(nesp_stick_t *stick, uint8_t code, uint8_t arg)
{
    nesp_sys_t *sys = &stick->sys;
    if (nesp_link_event(&stick->link, code, arg)) {
        return;                     /* a service in use had a use for it */
    }
    if (sys->event_count == NESP_EVENT_QUEUE) {
        return;
    }
    uint8_t at = (uint8_t)((sys->event_first + sys->event_count) % NESP_EVENT_QUEUE);
    sys->events[at][0] = code;
    sys->events[at][1] = arg;
    sys->event_count++;
    nesp_link_set_attention(sys->link, true);
}

size_t nesp_stick_feed(nesp_stick_t *stick, const uint8_t *data, size_t len, uint8_t *out)
{
    if (nesp_raw_owns_line(&stick->raw)) {
        nesp_raw_heard(&stick->raw, data, len);
        return 0;
    }
    return nesp_link_feed(&stick->link, data, len, out);
}

bool nesp_stick_tick(nesp_stick_t *stick, uint32_t now_ms)
{
    return nesp_link_tick(&stick->link, now_ms);
}

void nesp_stick_init(nesp_stick_t *stick, const nesp_hal_t *hal)
{
    nesp_link_init(&stick->link);
    nesp_sys_service(&stick->services[0], &stick->sys, &stick->link, hal);
    nesp_net_service(&stick->services[1], &stick->net, hal);
    nesp_diag_service(&stick->services[2], &stick->diag, &stick->link);
    nesp_wiki_service(&stick->services[3], &stick->wiki, hal);
    /* RAW before JUKE: a run that ends frees the line before the jukebox
     * is asked what comes next. */
    nesp_raw_service(&stick->services[4], &stick->raw, &stick->link, hal);
    nesp_juke_service(&stick->services[5], &stick->juke, &stick->link, &stick->raw, hal);
    nesp_peer_service(&stick->services[6], &stick->peer, &stick->sys, hal);
    for (size_t index = 0; index < sizeof(stick->services) / sizeof(stick->services[0]);
         index++) {
        nesp_link_register(&stick->link, &stick->services[index]);
    }
}
