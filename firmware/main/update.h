/* Whether the web site has newer firmware than this, for the Stick's screen. */
#ifndef UPDATE_H
#define UPDATE_H

#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Called often by the task that owns the screen: `free` when the nesp32 is
 * on Wi-Fi and no console is talking to it, the only time a check is begun.
 * Never waits: a check runs in a task of its own. */
void update_poll(bool free);

/* The site's firmware is newer than this. */
bool update_available(void);

#ifdef __cplusplus
}
#endif

#endif
