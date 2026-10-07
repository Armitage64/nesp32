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

/* The least the task's stack has ever had free, in bytes. */
uint32_t conn_stack_left(void);

#ifdef __cplusplus
}
#endif

#endif
