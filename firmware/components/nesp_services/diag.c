/* DIAG: how well the link is doing (docs/PROTOCOL.md). */
#include <string.h>

#include "nesp_services.h"

static void put16(uint8_t *out, uint32_t value)
{
    if (value > 0xFFFF) {
        value = 0xFFFF;
    }
    out[0] = (uint8_t)value;
    out[1] = (uint8_t)(value >> 8);
}

static void handle(void *ctx, const nesp_request_t *request, nesp_reply_t *reply)
{
    nesp_diag_t *diag = ctx;
    const nesp_counters_t *counters = &diag->link->counters;
    switch (request->op) {
    case NESP_DIAG_STATS:
        put16(reply->data, counters->requests);
        put16(reply->data + 2, counters->repeats);
        put16(reply->data + 4, counters->dropped);
        put16(reply->data + 6, counters->noise);
        put16(reply->data + 8, counters->turnaround_us);
        put16(reply->data + 10, counters->turnaround_max_us);
        reply->len = 12;
        break;
    case NESP_DIAG_PATTERN: {
        if (request->len != 3 || request->data[2] > reply->max
            || (request->data[0] | request->data[1]) == 0) {
            reply->status = NESP_ST_BAD_ARG;
            break;
        }
        uint16_t seed = (uint16_t)(request->data[0] | request->data[1] << 8);
        nesp_pattern(seed, reply->data, request->data[2]);
        reply->len = request->data[2];
        break;
    }
    case NESP_DIAG_SINK: {
        if (request->len < 2 || (request->data[0] | request->data[1]) == 0) {
            reply->status = NESP_ST_BAD_ARG;
            break;
        }
        uint8_t expected[NESP_PAYLOAD_MAX];
        uint8_t count = (uint8_t)(request->len - 2);
        uint16_t seed = (uint16_t)(request->data[0] | request->data[1] << 8);
        uint8_t bad = 0;
        nesp_pattern(seed, expected, count);
        for (uint8_t index = 0; index < count; index++) {
            if (expected[index] != request->data[2 + index]) {
                bad++;
            }
        }
        reply->data[0] = bad;
        reply->data[1] = count;
        reply->len = 2;
        break;
    }
    default:
        reply->status = NESP_ST_NO_OP;
        break;
    }
}

void nesp_diag_service(nesp_service_t *service, nesp_diag_t *diag, nesp_link_t *link)
{
    diag->link = link;
    memset(service, 0, sizeof(*service));
    service->id = NESP_SVC_DIAG;
    service->name = "DIAG";
    service->handle = handle;
    service->ctx = diag;
}
