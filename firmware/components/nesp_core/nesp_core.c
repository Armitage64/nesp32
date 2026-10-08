#include "nesp_core.h"

#include <string.h>

/* CRC-16/CCITT-FALSE, four bits at a time: the register after each of the
 * 16 values of its top four bits has been through four rounds. */
static const uint16_t crc_nibble[16] = {
    0x0000, 0x1021, 0x2042, 0x3063, 0x4084, 0x50A5, 0x60C6, 0x70E7,
    0x8108, 0x9129, 0xA14A, 0xB16B, 0xC18C, 0xD1AD, 0xE1CE, 0xF1EF,
};

uint16_t nesp_crc(const uint8_t *data, size_t len)
{
    uint16_t crc = NESP_CRC_INIT;
    for (size_t index = 0; index < len; index++) {
        uint8_t byte = data[index];
        crc = (uint16_t)(crc << 4) ^ crc_nibble[(crc >> 12) ^ (byte >> 4)];
        crc = (uint16_t)(crc << 4) ^ crc_nibble[(crc >> 12) ^ (byte & 0x0F)];
    }
    return crc;
}

void nesp_checks(const uint8_t *data, size_t len, uint8_t *a, uint8_t *b)
{
    uint16_t crc = nesp_crc(data, len);
    *a = (uint8_t)(crc >> 8);
    *b = (uint8_t)crc;
}

uint16_t nesp_pattern(uint16_t seed, uint8_t *out, size_t count)
{
    uint8_t hi = (uint8_t)(seed >> 8);
    uint8_t lo = (uint8_t)seed;
    for (size_t index = 0; index < count; index++) {
        /* The console's code, a step at a time: lsr hi (to carry), ror lo. */
        uint8_t a = (uint8_t)((lo >> 1) | ((hi & 1) << 7));
        uint8_t carry = lo & 1;
        hi ^= a;
        a = (uint8_t)((hi >> 1) | (carry << 7));
        lo ^= a;
        hi ^= lo;
        out[index] = hi;
    }
    return (uint16_t)(hi << 8 | lo);
}

void nesp_link_init(nesp_link_t *link)
{
    memset(link, 0, sizeof(*link));
    link->reply_max = NESP_REPLY_BEFORE_HELLO;
}

static nesp_slot_t *find_slot(nesp_link_t *link, uint8_t id)
{
    for (uint8_t index = 0; index < link->count; index++) {
        if (link->slots[index].service->id == id) {
            return &link->slots[index];
        }
    }
    return NULL;
}

bool nesp_link_register(nesp_link_t *link, const nesp_service_t *service)
{
    if (link->count == NESP_SERVICES_MAX || find_slot(link, service->id) != NULL) {
        return false;
    }
    nesp_slot_t *slot = &link->slots[link->count++];
    memset(slot, 0, sizeof(*slot));
    slot->service = service;
    slot->active = service->always;
    return true;
}

bool nesp_link_active(const nesp_link_t *link, uint8_t id)
{
    for (uint8_t index = 0; index < link->count; index++) {
        if (link->slots[index].service->id == id) {
            return link->slots[index].active;
        }
    }
    return false;
}

bool nesp_link_tick(nesp_link_t *link, uint32_t now_ms)
{
    bool soon = false;
    for (uint8_t index = 0; index < link->count; index++) {
        const nesp_service_t *service = link->slots[index].service;
        if (link->slots[index].active && service->tick != NULL
            && service->tick(service->ctx, now_ms)) {
            soon = true;
        }
    }
    return soon;
}

bool nesp_link_event(nesp_link_t *link, uint8_t code, uint8_t arg)
{
    for (uint8_t index = 0; index < link->count; index++) {
        const nesp_service_t *service = link->slots[index].service;
        if (link->slots[index].active && service->event != NULL
            && service->event(service->ctx, code, arg)) {
            return true;
        }
    }
    return false;
}

void nesp_link_set_attention(nesp_link_t *link, bool attention)
{
    link->attention = attention;
}

void nesp_link_note_turnaround(nesp_link_t *link, uint32_t microseconds)
{
    link->counters.turnaround_us = microseconds;
    if (microseconds > link->counters.turnaround_max_us) {
        link->counters.turnaround_max_us = microseconds;
    }
}

uint8_t nesp_link_hello(nesp_link_t *link, const uint8_t *ids, uint8_t count,
                        uint8_t reply_max, uint8_t *missing)
{
    uint8_t missed = 0;
    for (uint8_t index = 0; index < link->count; index++) {
        nesp_slot_t *slot = &link->slots[index];
        const nesp_service_t *service = slot->service;
        bool wanted = service->always;
        for (uint8_t at = 0; at < count && !wanted; at++) {
            wanted = ids[at] == service->id;
        }
        /* A service that stays is started afresh: the console was reset,
         * and holds nothing of what it was doing. */
        if (slot->active && service->deactivate != NULL) {
            service->deactivate(service->ctx);
        }
        if (wanted && service->activate != NULL) {
            service->activate(service->ctx);
        }
        slot->active = wanted;
        slot->held = false;
    }
    for (uint8_t at = 0; at < count; at++) {
        if (find_slot(link, ids[at]) == NULL) {
            missing[missed++] = ids[at];
        }
    }
    if (reply_max > NESP_PAYLOAD_MAX) {
        reply_max = NESP_PAYLOAD_MAX;
    }
    if (reply_max < NESP_REPLY_MIN) {
        reply_max = NESP_REPLY_MIN;
    }
    link->reply_max = reply_max;
    return missed;
}

/* The reply to one request, written to out. Returns its length. */
static size_t answer(nesp_link_t *link, const uint8_t *frame, uint8_t *out)
{
    nesp_request_t request = {
        .svc = frame[1], .op = frame[2], .seq = frame[3], .len = frame[4],
        .data = frame + NESP_HEADER,
    };
    const uint8_t *checks = frame + NESP_HEADER + request.len;
    nesp_slot_t *slot = find_slot(link, request.svc);
    bool hello = request.svc == NESP_SVC_SYS && request.op == NESP_SYS_HELLO;

    if (slot != NULL && slot->held && !hello && slot->key[0] == request.op
        && slot->key[1] == request.seq && slot->key[2] == request.len
        && slot->key[3] == checks[0] && slot->key[4] == checks[1]) {
        link->counters.repeats++;
        memcpy(out, slot->reply, slot->reply_len);
        return slot->reply_len;
    }

    nesp_reply_t reply = {
        .status = NESP_ST_OK, .len = 0, .max = link->reply_max, .once = false,
        .data = out + NESP_HEADER,
    };
    if (slot == NULL) {
        reply.status = NESP_ST_NO_SERVICE;
    } else if (!slot->active) {
        reply.status = NESP_ST_INACTIVE;
    } else {
        slot->service->handle(slot->service->ctx, &request, &reply);
        if (reply.len > reply.max) {    /* a handler's mistake, not the console's */
            reply.status = NESP_ST_FAILED;
            reply.len = 0;
        }
    }
    if (link->attention) {
        reply.status |= NESP_ST_ATTENTION;
    }
    out[0] = NESP_REPLY_MARKER;
    out[1] = request.svc;
    out[2] = reply.status;
    out[3] = request.seq;
    out[4] = reply.len;
    nesp_checks(out + 1, (size_t)(NESP_HEADER - 1) + reply.len,
                out + NESP_HEADER + reply.len, out + NESP_HEADER + reply.len + 1);
    size_t total = (size_t)NESP_OVERHEAD + reply.len;

    /* A hello's reply is never held: the next hello is a new one, whatever
     * its bytes. Nor is "busy": asking again must be able to get more. The
     * slot is looked up again, since a hello may have changed them all. */
    slot = find_slot(link, request.svc);
    if (slot != NULL) {
        uint8_t plain = reply.status & (uint8_t)~NESP_ST_ATTENTION;
        slot->held = slot->active && !hello && !reply.once && plain != NESP_ST_BUSY;
        if (slot->held) {
            slot->key[0] = request.op;
            slot->key[1] = request.seq;
            slot->key[2] = request.len;
            slot->key[3] = checks[0];
            slot->key[4] = checks[1];
            slot->reply_len = (uint8_t)total;
            memcpy(slot->reply, out, total);
        }
    }
    return total;
}

/* The reply to a short request, written to out. Returns its length. */
static size_t answer_short(nesp_link_t *link, const uint8_t *frame, uint8_t *out)
{
    uint8_t count = NESP_SHORT_NONE;
    memset(out, 0, NESP_SHORT);
    for (uint8_t index = 0; index < link->count; index++) {
        const nesp_service_t *service = link->slots[index].service;
        if (link->slots[index].active && service->quick != NULL) {
            count = service->quick(service->ctx, frame[0] & (uint8_t)~NESP_SHORT_MARK,
                                   frame + 1, out + 1);
            break;
        }
    }
    out[0] = (uint8_t)(NESP_SHORT_REPLY | (count & (uint8_t)~NESP_SHORT_MARK));
    nesp_checks(out, 1 + NESP_SHORT_DATA, out + 1 + NESP_SHORT_DATA,
                out + 2 + NESP_SHORT_DATA);
    return NESP_SHORT;
}

size_t nesp_link_feed(nesp_link_t *link, const uint8_t *data, size_t len, uint8_t *out)
{
    /* Keep the newest bytes if more come than there is room for. */
    if (len >= NESP_RX_BUFFER) {
        link->counters.noise += (uint32_t)(link->rx_len + len - NESP_RX_BUFFER);
        data += len - NESP_RX_BUFFER;
        len = NESP_RX_BUFFER;
        link->rx_len = 0;
    } else if (link->rx_len + len > NESP_RX_BUFFER) {
        size_t over = link->rx_len + len - NESP_RX_BUFFER;
        memmove(link->rx, link->rx + over, link->rx_len - over);
        link->rx_len -= over;
        link->counters.noise += (uint32_t)over;
    }
    memcpy(link->rx + link->rx_len, data, len);
    link->rx_len += len;

    /* Find every whole request. A byte that begins none is passed over:
     * the console's controller read is on this line too, and comes through
     * as noise. `pending` is the first place a request may have begun and
     * not yet ended. */
    const uint8_t *rx = link->rx;
    size_t count = link->rx_len;
    size_t at = 0;
    size_t pending = count;
    size_t newest = count;
    size_t framed = 0;          /* bytes that were part of good requests */
    bool found = false;
    while (at < count) {
        if ((rx[at] & NESP_SHORT_MARK) == NESP_SHORT_REQUEST) {
            /* A short request: its length is known, and its CRC takes in
             * the marker. */
            uint8_t a, b;
            if (at + NESP_SHORT > count) {
                if (pending == count) {
                    pending = at;
                }
                at++;
                continue;
            }
            nesp_checks(rx + at, 1 + NESP_SHORT_DATA, &a, &b);
            if (a != rx[at + NESP_SHORT - 2] || b != rx[at + NESP_SHORT - 1]) {
                at++;
                continue;
            }
            if (found) {
                link->counters.dropped++;
            }
            found = true;
            newest = at;
            link->counters.requests++;
            framed += NESP_SHORT;
            at += NESP_SHORT;
            pending = count;
            continue;
        }
        if (rx[at] != NESP_REQUEST_MARKER) {
            at++;
            continue;
        }
        if (at + NESP_HEADER > count) {
            if (pending == count) {
                pending = at;
            }
            at++;
            continue;
        }
        uint8_t length = rx[at + 4];
        if (length > NESP_PAYLOAD_MAX) {
            at++;
            continue;
        }
        size_t total = (size_t)NESP_OVERHEAD + length;
        if (at + total > count) {
            if (pending == count) {
                pending = at;
            }
            at++;
            continue;
        }
        uint8_t a, b;
        nesp_checks(rx + at + 1, (size_t)(NESP_HEADER - 1) + length, &a, &b);
        if (a != rx[at + total - 2] || b != rx[at + total - 1]) {
            at++;
            continue;
        }
        if (found) {
            link->counters.dropped++;
        }
        found = true;
        newest = at;
        link->counters.requests++;
        framed += total;
        at += total;
        pending = count;        /* whatever seemed to begin before this did not */
    }

    size_t sent = 0;
    if (found) {
        sent = (rx[newest] & NESP_SHORT_MARK) == NESP_SHORT_REQUEST
                   ? answer_short(link, rx + newest, out) : answer(link, rx + newest, out);
    }
    /* Everything before an unfinished request has been dealt with, and
     * what of it was not a request was noise. */
    size_t kept = count - pending;
    link->counters.noise += (uint32_t)(pending - framed);
    memmove(link->rx, link->rx + pending, kept);
    link->rx_len = kept;
    return sent;
}
