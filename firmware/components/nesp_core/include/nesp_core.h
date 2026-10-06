/* The link, less the hardware: frames, checks, the services and who is
 * asked what (docs/PROTOCOL.md).
 *
 * Nothing here touches a UART, a clock or the heap, so the same code runs in
 * the Stick's link task and, built for a computer, under the tests.
 *
 * The console is always the one that asks. Bytes from it go to
 * nesp_link_feed, which finds the requests in them and returns the one
 * reply to send, if any. A request goes to the service it names; a service
 * answers from what it holds and never waits for anything. What a service
 * has to do between requests it does when the port calls nesp_link_tick.
 */
#ifndef NESP_CORE_H
#define NESP_CORE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "nesp_proto.h"

#ifdef __cplusplus
extern "C" {
#endif

#define NESP_SERVICES_MAX 16
/* What the decoder keeps: room for a frame that has not all come, behind
 * the noise or the older frame that was ahead of it. */
#define NESP_RX_BUFFER (2 * NESP_FRAME_MAX)

typedef struct {
    uint8_t svc;
    uint8_t op;
    uint8_t seq;
    uint8_t len;
    const uint8_t *data;
} nesp_request_t;

/* A handler is given status NESP_ST_OK and len 0, and room for max bytes
 * at data. */
typedef struct {
    uint8_t status;
    uint8_t len;
    uint8_t max;
    bool once;              /* true: never send this reply again for a repeat */
    uint8_t *data;
} nesp_reply_t;

typedef struct {
    uint8_t id;
    const char *name;
    /* Either may be NULL. activate is called when a hello asks for the
     * service, deactivate when a later hello does not. */
    void (*activate)(void *ctx);
    void (*deactivate)(void *ctx);
    void (*handle)(void *ctx, const nesp_request_t *request, nesp_reply_t *reply);
    /* Either may be NULL, and neither is called unless the service is
     * active. tick is where a service does what takes time or goes by the
     * clock: it is called after every reply has gone and every few
     * milliseconds besides, and returns true to be called again soon. event
     * is something that happened on the nesp32 (NESP_EVENT_*); true means
     * the service has dealt with it, and the console is not told. */
    bool (*tick)(void *ctx, uint32_t now_ms);
    bool (*event)(void *ctx, uint8_t code, uint8_t arg);
    void *ctx;
    bool always;            /* active without being asked for: SYS */
} nesp_service_t;

typedef struct {
    const nesp_service_t *service;
    bool active;
    /* The last reply, and the request it answered: the same request again
     * gets the same bytes again. */
    bool held;
    uint8_t key[5];         /* op, seq, len and the request's CRC */
    uint8_t reply_len;
    uint8_t reply[NESP_FRAME_MAX];
} nesp_slot_t;

typedef struct {
    uint32_t requests;      /* good requests found */
    uint32_t repeats;       /* of those, answered again with a held reply */
    uint32_t dropped;       /* of those, not answered: a newer one was behind */
    uint32_t noise;         /* bytes that were part of no request */
    uint32_t turnaround_us; /* the port's time to answer the last request */
    uint32_t turnaround_max_us;
} nesp_counters_t;

typedef struct {
    nesp_slot_t slots[NESP_SERVICES_MAX];
    uint8_t count;
    uint8_t reply_max;      /* the longest payload the console takes */
    bool attention;         /* sets NESP_ST_ATTENTION on every reply */
    uint8_t rx[NESP_RX_BUFFER];
    size_t rx_len;
    nesp_counters_t counters;
} nesp_link_t;

void nesp_link_init(nesp_link_t *link);

/* Add a service. False if there is no room or the id is taken. */
bool nesp_link_register(nesp_link_t *link, const nesp_service_t *service);

/* Bytes from the console. Returns the length of the reply written to out,
 * 0 for none. out must hold NESP_FRAME_MAX bytes. Of several requests in
 * what has come, only the last is acted on: the console has stopped
 * listening for the others, and asks again for what it still wants. */
size_t nesp_link_feed(nesp_link_t *link, const uint8_t *data, size_t len, uint8_t *out);

/* A hello's doing. Makes active the services named in ids, and only those
 * (and the ones that always are); forgets every held reply; sets the
 * longest reply payload. Ids this firmware does not have are written to
 * missing, which must hold count bytes. Returns how many. */
uint8_t nesp_link_hello(nesp_link_t *link, const uint8_t *ids, uint8_t count,
                        uint8_t reply_max, uint8_t *missing);

/* Give every active service its tick. now_ms is any clock in milliseconds;
 * it may wrap. True if one of them wants another within a couple of
 * milliseconds. */
bool nesp_link_tick(nesp_link_t *link, uint32_t now_ms);

/* Something happened on the nesp32. True if an active service took it. */
bool nesp_link_event(nesp_link_t *link, uint8_t code, uint8_t arg);

bool nesp_link_active(const nesp_link_t *link, uint8_t id);
void nesp_link_set_attention(nesp_link_t *link, bool attention);
void nesp_link_note_turnaround(nesp_link_t *link, uint32_t microseconds);

/* CRC-16/CCITT-FALSE of some bytes. */
uint16_t nesp_crc(const uint8_t *data, size_t len);

/* The two check bytes of a frame, from its bytes after the marker to the
 * end of its payload: their CRC, high byte first. */
void nesp_checks(const uint8_t *data, size_t len, uint8_t *a, uint8_t *b);

/* Count bytes of the test pattern for a seed: a 16-bit xorshift (7, 9, 8),
 * a byte a step, as the console's nesp_pattern makes it. Returns the seed
 * to go on from. The seed must not be 0. */
uint16_t nesp_pattern(uint16_t seed, uint8_t *out, size_t count);

#ifdef __cplusplus
}
#endif

#endif
