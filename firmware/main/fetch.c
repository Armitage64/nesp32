/* One https GET at a time, read as it arrives and handed to a service a
 * piece at a time.
 *
 * A service asks from the link's task, which may not wait: fetch_begin only
 * leaves the order where this file's task finds it. The task makes the
 * connection, which with its TLS handshake takes a second or two, and reads
 * the reply; the link goes on answering the console throughout, from its
 * own core.
 *
 * An order replaces whatever fetch is under way: the task sees it between
 * reads, drops the connection and starts on the new one. A sink hears no
 * more of a fetch once it has been replaced or stopped.
 *
 * The server is authenticated against ESP-IDF's bundle of root
 * certificates. An address that sends the fetch on to another (a 301, 302,
 * 303, 307 or 308) is followed, as far as REDIRECTS_MAX of them.
 */
#include "fetch.h"

#include <stdio.h>
#include <string.h>

#include "esp_crt_bundle.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

/* A TLS handshake wants 12 KB, and the MP3 decoder a sink may call from
 * here (nesp_mp3.h) keeps 16 KB of its own while it works. */
#define FETCH_STACK 32768
#define FETCH_PRIORITY 5
#define FETCH_CORE 0                /* with Wi-Fi; the link has core 1 */
#define TIMEOUT_MS 10000
#define CHUNK 1024
#define REDIRECTS_MAX 5

static const char *TAG = "fetch";

typedef struct {
    char url[512];
    char agent[128];
    uint32_t id;
    const nesp_sink_t *sink;
} order_t;

static portMUX_TYPE lock = portMUX_INITIALIZER_UNLOCKED;
static order_t waiting;             /* under lock: the next fetch, if `ordered` */
static bool ordered;                /* under lock */
static uint32_t serial;             /* under lock: counts orders and stops */
static TaskHandle_t task;

bool fetch_begin(void *ctx, const char *url, const char *agent, uint32_t id,
                 const nesp_sink_t *sink)
{
    (void)ctx;
    if (task == NULL || strlen(url) >= sizeof(waiting.url)
        || strlen(agent) >= sizeof(waiting.agent)) {
        return false;
    }
    portENTER_CRITICAL(&lock);
    strcpy(waiting.url, url);
    strcpy(waiting.agent, agent);
    waiting.id = id;
    waiting.sink = sink;
    ordered = true;
    serial++;
    portEXIT_CRITICAL(&lock);
    xTaskNotifyGive(task);
    return true;
}

void fetch_stop(void *ctx)
{
    (void)ctx;
    portENTER_CRITICAL(&lock);
    ordered = false;
    serial++;
    portEXIT_CRITICAL(&lock);
}

/* Is the fetch that began at this count of orders still the one wanted? */
static bool wanted(uint32_t began)
{
    portENTER_CRITICAL(&lock);
    bool same = serial == began;
    portEXIT_CRITICAL(&lock);
    return same;
}

static void failed(const order_t *order, uint32_t began, const char *why)
{
    ESP_LOGW(TAG, "fetch %lu: %s", (unsigned long)order->id, why);
    if (wanted(began)) {
        order->sink->done(order->sink->ctx, order->id, false, why);
    }
}

static void fetch(const order_t *order, uint32_t began)
{
    static uint8_t chunk[CHUNK];
    char why[32];
    esp_http_client_config_t config = {
        .url = order->url,
        .user_agent = order->agent,
        .crt_bundle_attach = esp_crt_bundle_attach,
        .timeout_ms = TIMEOUT_MS,
        .buffer_size = CHUNK,
        .buffer_size_tx = 1024,     /* the request's line is the address, and long */
    };
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (client == NULL) {
        failed(order, began, "THE NESP32 IS OUT OF MEMORY");
        return;
    }
    /* Not compressed: the body is read as it comes. */
    esp_http_client_set_header(client, "Accept-Encoding", "identity");
    int64_t started = esp_timer_get_time();
    size_t total = 0;
    bool answered = false;
    for (int hops = 0;; hops++) {
        if (esp_http_client_open(client, 0) != ESP_OK
            || esp_http_client_fetch_headers(client) < 0) {
            break;
        }
        int code = esp_http_client_get_status_code(client);
        bool moved = code == 301 || code == 302 || code == 303 || code == 307 || code == 308;
        if (!moved || hops == REDIRECTS_MAX || !wanted(began)) {
            answered = true;
            break;
        }
        /* Sent on: the same fetch, from the address it was sent to. */
        if (esp_http_client_set_redirection(client) != ESP_OK) {
            answered = true;        /* with nowhere to go: said as the code it had */
            break;
        }
        esp_http_client_close(client);
        ESP_LOGI(TAG, "fetch %lu: sent on (%d)", (unsigned long)order->id, code);
    }
    if (!answered) {
        failed(order, began, "THE SITE DID NOT ANSWER");
    } else if (esp_http_client_get_status_code(client) != 200) {
        snprintf(why, sizeof(why), "THE SITE SAID %d", esp_http_client_get_status_code(client));
        failed(order, began, why);
    } else {
        /* In longs: this firmware's printf has no long long. */
        ESP_LOGI(TAG, "fetch %lu: answered in %lu ms", (unsigned long)order->id,
                 (unsigned long)((esp_timer_get_time() - started) / 1000));
        for (;;) {
            int count = esp_http_client_read(client, (char *)chunk, sizeof(chunk));
            if (!wanted(began)) {
                break;              /* replaced or stopped: nothing more is said */
            }
            if (count < 0) {
                failed(order, began, "THE CONNECTION DROPPED");
                break;
            }
            if (count == 0) {
                bool whole = esp_http_client_is_complete_data_received(client);
                if (whole) {
                    order->sink->done(order->sink->ctx, order->id, true, "");
                } else {
                    failed(order, began, "THE CONNECTION DROPPED");
                }
                break;
            }
            total += (size_t)count;
            if (!order->sink->body(order->sink->ctx, order->id, chunk, (size_t)count)) {
                if (wanted(began)) {    /* it has what it wants */
                    order->sink->done(order->sink->ctx, order->id, true, "");
                }
                break;
            }
        }
        ESP_LOGI(TAG, "fetch %lu: %u bytes in %lu ms", (unsigned long)order->id,
                 (unsigned)total, (unsigned long)((esp_timer_get_time() - started) / 1000));
    }
    esp_http_client_close(client);
    esp_http_client_cleanup(client);
}

static void fetch_task(void *arg)
{
    (void)arg;
    static order_t order;
    for (;;) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        for (;;) {
            portENTER_CRITICAL(&lock);
            bool have = ordered;
            uint32_t began = serial;
            if (have) {
                order = waiting;
                ordered = false;
            }
            portEXIT_CRITICAL(&lock);
            if (!have) {
                break;
            }
            fetch(&order, began);
        }
    }
}

void fetch_start(void)
{
    xTaskCreatePinnedToCore(fetch_task, "fetch", FETCH_STACK, NULL, FETCH_PRIORITY, &task,
                            FETCH_CORE);
}

uint32_t fetch_stack_left(void)
{
    return task != NULL ? (uint32_t)uxTaskGetStackHighWaterMark(task) : 0;
}
