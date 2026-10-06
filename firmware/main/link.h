/* The link task: the UART to the console, and the one task that answers it. */
#ifndef LINK_H
#define LINK_H

#include <stdint.h>

#include "nesp_services.h"

#ifdef __cplusplus
extern "C" {
#endif

/* What the link has done, for the Stick's screen. */
typedef struct {
    uint32_t requests;
    uint32_t repeats;
    uint32_t noise;
    uint32_t turnaround_us;
    uint32_t turnaround_max_us;
    uint32_t last_request_ms;       /* when the console was last heard; 0 if never */
} link_stats_t;

/* Open the UART, so that TX rests at mark, and start answering. */
void link_start(const nesp_hal_t *hal);

/* Tell the console of something (NESP_EVENT_*). From any task. */
void link_event(uint8_t code, uint8_t arg);

void link_stats(link_stats_t *out);

/* The least the link task's stack has ever had free, in bytes. */
uint32_t link_stack_left(void);

#ifdef __cplusplus
}
#endif

#endif
