/* A measurement of decoding a radio station, built only with NESP_SPIKE
 * (spike.c). */
#ifndef SPIKE_H
#define SPIKE_H

#ifdef __cplusplus
extern "C" {
#endif

/* From the main task's loop: start the fetch once there is a network, and
 * log what it costs. */
void spike_poll(void);

#ifdef __cplusplus
}
#endif

#endif
