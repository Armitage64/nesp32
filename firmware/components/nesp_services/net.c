/* NET: the Stick's Wi-Fi, set up from the console (docs/PROTOCOL.md).
 *
 * A name and a password are longer than a request the console can send
 * between two of its frames, so they come in pieces: each SET carries the
 * offset its bytes go at, and JOIN repeats both lengths, so a piece that
 * never came is found out before anything is tried.
 *
 * The password goes one way only. No op gives it back.
 */
#include <string.h>

#include "nesp_services.h"

/* A piece of text at an offset. Offset 0 begins it again; any other must
 * carry on from where the text so far ends. */
static void set_piece(const nesp_request_t *request, nesp_reply_t *reply,
                      char *text, uint8_t *length, uint8_t max)
{
    if (request->len < 1) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    uint8_t offset = request->data[0];
    uint8_t count = (uint8_t)(request->len - 1);
    if (offset == 0) {
        *length = 0;
    }
    if (offset != *length || (unsigned)offset + count > max) {
        reply->status = NESP_ST_BAD_ARG;
    } else {
        memcpy(text + offset, request->data + 1, count);
        *length = (uint8_t)(offset + count);
    }
    reply->data[0] = *length;
    reply->len = 1;
}

static void wifi_status(nesp_net_t *net, nesp_reply_t *reply)
{
    nesp_wifi_t wifi;
    memset(&wifi, 0, sizeof(wifi));
    net->hal->wifi(net->hal->ctx, &wifi);
    uint8_t *out = reply->data;
    out[0] = wifi.state;
    out[1] = wifi.why;
    out[2] = (uint8_t)wifi.rssi;
    memcpy(out + 3, wifi.address, 4);
    uint8_t name_len = wifi.name_len;
    if (name_len > reply->max - 8) {
        name_len = (uint8_t)(reply->max - 8);
    }
    out[7] = name_len;
    memcpy(out + 8, wifi.name, name_len);
    reply->len = (uint8_t)(8 + name_len);
}

static void scan_result(nesp_net_t *net, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len != 1) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    nesp_network_t network;
    memset(&network, 0, sizeof(network));
    if (!net->hal->scan_result(net->hal->ctx, request->data[0], &network)) {
        reply->status = NESP_ST_NOT_FOUND;
        return;
    }
    uint8_t *out = reply->data;
    out[0] = request->data[0];
    out[1] = (uint8_t)network.rssi;
    out[2] = network.auth;
    out[3] = network.channel;
    uint8_t name_len = network.name_len;
    if (name_len > reply->max - 5) {
        name_len = (uint8_t)(reply->max - 5);
    }
    out[4] = name_len;
    memcpy(out + 5, network.name, name_len);
    reply->len = (uint8_t)(5 + name_len);
}

static void join(nesp_net_t *net, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len != 2 || request->data[0] != net->name_len
        || request->data[1] != net->password_len || net->name_len == 0) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    if (!net->hal->join(net->hal->ctx, net->name, net->name_len,
                        net->password, net->password_len)) {
        reply->status = NESP_ST_FAILED;
    }
    memset(net->password, 0, sizeof(net->password));
    net->password_len = 0;
    net->name_len = 0;
}

static void handle(void *ctx, const nesp_request_t *request, nesp_reply_t *reply)
{
    nesp_net_t *net = ctx;
    switch (request->op) {
    case NESP_NET_WIFI_STATUS:
        wifi_status(net, reply);
        break;
    case NESP_NET_SCAN_START:
        if (!net->hal->scan_start(net->hal->ctx)) {
            reply->status = NESP_ST_BUSY;
        }
        break;
    case NESP_NET_SCAN_STATUS: {
        uint8_t count = 0;
        reply->data[0] = net->hal->scan_state(net->hal->ctx, &count);
        reply->data[1] = count;
        reply->len = 2;
        break;
    }
    case NESP_NET_SCAN_RESULT:
        scan_result(net, request, reply);
        break;
    case NESP_NET_SET_NAME:
        set_piece(request, reply, net->name, &net->name_len, NESP_NAME_MAX);
        break;
    case NESP_NET_SET_PASSWORD:
        set_piece(request, reply, net->password, &net->password_len, NESP_PASSWORD_MAX);
        break;
    case NESP_NET_JOIN:
        join(net, request, reply);
        break;
    case NESP_NET_FORGET:
        net->hal->forget(net->hal->ctx);
        break;
    default:
        reply->status = NESP_ST_NO_OP;
        break;
    }
}

/* A hello: the console was reset, and whatever it had typed is gone. */
static void activate(void *ctx)
{
    nesp_net_t *net = ctx;
    memset(net->password, 0, sizeof(net->password));
    net->password_len = 0;
    net->name_len = 0;
}

void nesp_net_service(nesp_service_t *service, nesp_net_t *net, const nesp_hal_t *hal)
{
    memset(net, 0, sizeof(*net));
    net->hal = hal;
    memset(service, 0, sizeof(*service));
    service->id = NESP_SVC_NET;
    service->name = "NET";
    service->activate = activate;
    service->deactivate = activate;
    service->handle = handle;
    service->ctx = net;
}
