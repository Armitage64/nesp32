/* Is there newer firmware than this? The same question Setup asks
 * (apps/setup/nes/update.inc), for the Stick's own screen: the flash page's
 * manifest (tools/gen_web.py writes it) has the latest release's "version"
 * near its start, and that is compared with this build's numbers.
 *
 * A check is begun only when the nesp32 is on Wi-Fi and no console is
 * talking to it, so that nothing is fetched under a game, and it has a task
 * of its own, which ends with it: fetch.c's is the services', and an order
 * there would replace theirs. Once the answer is known it is asked again
 * after RECHECK_MS, for a nesp32 left on; a check that fails (no answer, a
 * status but 200, no version near the start) is tried again after
 * RETRY_MS, and until then the screen says nothing rather than something
 * wrong.
 */
#include "update.h"

#include <stdint.h>
#include <string.h>

#include "esp_crt_bundle.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "nesp_version.h"

#define URL "https://nesp32.retrobits.tv/flash/manifest.json"
#define LOOK 200                    /* how far into the body "version" may be */
#define TIMEOUT_MS 10000
#define RETRY_MS (10 * 60 * 1000)
#define RECHECK_MS (24 * 60 * 60 * 1000)
#define STACK 8192                  /* a TLS handshake, with its certificate bundle */
#define PRIORITY 4
#define CORE 0                      /* with Wi-Fi; the link has core 1 */

static const char *TAG = "update";

static volatile bool checking;      /* a check's task is running */
static volatile bool newer;         /* the last check's answer */
static volatile int64_t next_at;    /* no check begun before this (us) */

/* The major, minor and patch of a "version" in the first `length` bytes of
 * `body`, or false if it has none. */
static bool version_of(const char *body, int length, unsigned out[3])
{
    static const char key[] = "\"version\"";
    const char *at = NULL;
    for (int i = 0; i + (int)sizeof(key) - 1 <= length; i++) {
        if (memcmp(body + i, key, sizeof(key) - 1) == 0) {
            at = body + i + sizeof(key) - 1;
            break;
        }
    }
    if (at == NULL) {
        return false;
    }
    const char *end = body + length;
    while (at < end && (*at == ' ' || *at == ':' || *at == '\t')) {
        at++;
    }
    if (at >= end || *at++ != '"') {
        return false;
    }
    for (int part = 0; part < 3; part++) {
        if (at >= end || *at < '0' || *at > '9') {
            return false;
        }
        unsigned value = 0;
        while (at < end && *at >= '0' && *at <= '9' && value < 1000) {
            value = value * 10 + (unsigned)(*at++ - '0');
        }
        out[part] = value;
        if (part < 2 && (at >= end || *at++ != '.')) {
            return false;
        }
    }
    return true;
}

/* GET the manifest and read the start of it. True if a version was there. */
static bool ask(unsigned latest[3])
{
    esp_http_client_config_t config = {
        .url = URL,
        .timeout_ms = TIMEOUT_MS,
        .crt_bundle_attach = esp_crt_bundle_attach,
        .user_agent = "nesp32/" NESP_FIRMWARE_TEXT,
    };
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (client == NULL) {
        return false;
    }
    bool found = false;
    char body[LOOK];
    if (esp_http_client_open(client, 0) == ESP_OK
        && esp_http_client_fetch_headers(client) >= 0
        && esp_http_client_get_status_code(client) == 200) {
        int length = 0;
        while (length < LOOK) {
            int got = esp_http_client_read(client, body + length, LOOK - length);
            if (got <= 0) {
                break;
            }
            length += got;
        }
        found = version_of(body, length, latest);
    }
    esp_http_client_cleanup(client);
    return found;
}

static void check(void *arg)
{
    (void)arg;
    unsigned latest[3];
    if (ask(latest)) {
        const unsigned mine[3] = {NESP_FIRMWARE_MAJOR, NESP_FIRMWARE_MINOR, NESP_FIRMWARE_PATCH};
        bool is_newer = false;
        for (int part = 0; part < 3; part++) {
            if (latest[part] != mine[part]) {
                is_newer = latest[part] > mine[part];
                break;
            }
        }
        newer = is_newer;
        ESP_LOGI(TAG, "the site's firmware is %u.%u.%u: %s", latest[0], latest[1], latest[2],
                 is_newer ? "newer" : "not newer");
        next_at = esp_timer_get_time() + (int64_t)RECHECK_MS * 1000;
    } else {
        ESP_LOGW(TAG, "could not read the site's firmware version");
        next_at = esp_timer_get_time() + (int64_t)RETRY_MS * 1000;
    }
    checking = false;
    vTaskDelete(NULL);
}

void update_poll(bool free)
{
    if (!free || checking || esp_timer_get_time() < next_at) {
        return;
    }
    checking = true;
    if (xTaskCreatePinnedToCore(check, "update", STACK, NULL, PRIORITY, NULL, CORE) != pdPASS) {
        checking = false;
        next_at = esp_timer_get_time() + (int64_t)RETRY_MS * 1000;
    }
}

bool update_available(void)
{
    return newer;
}
