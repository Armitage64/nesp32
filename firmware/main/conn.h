/* One connection to another nesp32, for the services (nesp_hal_t's peer_*). */
#ifndef CONN_H
#define CONN_H

#include "nesp_services.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Start the task that makes the connection and carries its bytes. After
 * the flash's settings are up (radio.c): the address last joined is there. */
void conn_start(void);

/* nesp_hal_t's peer_*: none of them waits. */
uint8_t conn_state(void *ctx);
bool conn_listen(void *ctx, uint16_t port);
bool conn_call(void *ctx, const uint8_t *address, uint16_t port);
void conn_close(void *ctx);
size_t conn_send(void *ctx, const uint8_t *data, size_t len);
size_t conn_recv(void *ctx, uint8_t *out, size_t max);
bool conn_last(void *ctx, uint8_t *address);
void conn_keep(void *ctx, const uint8_t *address);
uint32_t conn_rtt(void *ctx);
void conn_note(void *ctx, const uint8_t *note);
void conn_noted(void *ctx, uint8_t *note);
void conn_spread(void *ctx, uint32_t *counts);
bool conn_meet(void *ctx, uint16_t port);
uint8_t conn_candidates(void *ctx, nesp_peer_candidate_t *out);
bool conn_punch(void *ctx, bool listen, uint32_t session, const nesp_peer_candidate_t *other,
                uint8_t count);

/* How long the network has taken between the two nesp32s, there and back,
 * since they connected: every one of the connection's packets measures it.
 * A figure includes up to a millisecond at each end, which is how often the
 * task looks. For the log. */
typedef struct {
    uint32_t count;         /* measurements; 0 until the first */
    uint32_t last_us;
    uint32_t least_us;
    uint32_t most_us;
    uint32_t over_14ms;     /* those that took longer: a delay of 1 does not cover them */
    uint32_t over_40ms;     /* nor a delay of 2 these */
} conn_ping_t;

void conn_ping(conn_ping_t *out);

/* The least the task's stack has ever had free, in bytes. */
uint32_t conn_stack_left(void);

#ifdef __cplusplus
}
#endif

#endif
