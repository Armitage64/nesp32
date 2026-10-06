/* Fetching from the Internet, for the services (nesp_hal_t's fetch). */
#ifndef FETCH_H
#define FETCH_H

#include "nesp_services.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Start the task that does the fetching. */
void fetch_start(void);

/* nesp_hal_t's fetch and fetch_stop: neither waits. */
bool fetch_begin(void *ctx, const char *url, const char *agent, uint32_t id,
                 const nesp_sink_t *sink);
void fetch_stop(void *ctx);

/* The least the fetch task's stack has ever had free, in bytes. */
uint32_t fetch_stack_left(void);

#ifdef __cplusplus
}
#endif

#endif
