/* Wi-Fi, and the hardware as the services see it (nesp_hal_t).
 *
 * The services run in the link task and may not wait, so nothing here that
 * they call does any work. Each call either copies out a snapshot kept
 * under a spinlock, or leaves an order for the worker task below, which is
 * the only caller of esp_wifi's slow functions. Wi-Fi's own events keep the
 * snapshot up to date.
 *
 * The network is saved by esp_wifi itself, in NVS, when it is set. It is
 * only ever set by an order from the console (NET JOIN, from the setup
 * ROM): there is no file and no build setting with a password in it. At
 * start a saved network is joined, and joined again whenever it drops.
 *
 * A join the console asked for is tried JOIN_TRIES times and then given up
 * as failed, with the reason for the console to show; the saved network is
 * then tried again every RETRY_MS, as after any drop.
 */
#include "radio.h"

#include <string.h>
#include <time.h>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "nvs_flash.h"

#include "board.h"
#include "conn.h"
#include "esp_heap_caps.h"
#include "fetch.h"
#include "link.h"
#include "store.h"
#include "usb.h"

#define JOIN_TRIES 3
#define RETRY_MS 15000
#define SIGNAL_MS 2000
#define WORKER_STACK 4096
#define WORKER_PRIORITY 5
#define TIME_KNOWN_AFTER 1700000000     /* any clock before late 2023 has not been set */

static const char *TAG = "radio";

typedef enum { ORDER_SCAN, ORDER_JOIN, ORDER_FORGET } order_kind_t;

typedef struct {
    order_kind_t kind;
    uint8_t name_len;
    uint8_t password_len;
    char name[NESP_NAME_MAX];
    char password[NESP_PASSWORD_MAX];
} order_t;

static portMUX_TYPE lock = portMUX_INITIALIZER_UNLOCKED;
static nesp_wifi_t wifi;                    /* under lock */
static uint8_t scan_state = NESP_SCAN_IDLE; /* under lock */
static uint8_t scan_count;                  /* under lock */
static nesp_network_t networks[NESP_SCAN_MAX];  /* under lock */
static uint8_t battery = 0xFF;
static char app_id[NESP_APP_ID] = {' ', ' ', ' ', ' '};
static char shown[2][RADIO_SHOWN_MAX];      /* under lock: the application's lines */
static char watched[RADIO_WATCH_MAX];       /* under lock: its line for the log */
static bool watch_news;
static uint8_t app_version;
static QueueHandle_t orders;
static nesp_hal_t hal;
static uint8_t tries_left;                  /* under lock: of a join the console asked for */
static bool want_joined;                    /* under lock: a network is saved and should be up */
static TickType_t retry_at;

/* --- what the services call: no waiting ------------------------------------- */

static uint8_t hal_board(void *ctx)
{
    (void)ctx;
    return BOARD_ID;
}

static const char *hal_board_name(void *ctx)
{
    (void)ctx;
    return BOARD_NAME;
}

static uint8_t hal_battery(void *ctx)
{
    (void)ctx;
    return battery;
}

static bool hal_time(void *ctx, uint32_t *seconds)
{
    (void)ctx;
    time_t now = time(NULL);
    *seconds = (uint32_t)now;
    return now > TIME_KNOWN_AFTER;
}

static void hal_wifi(void *ctx, nesp_wifi_t *out)
{
    (void)ctx;
    portENTER_CRITICAL(&lock);
    *out = wifi;
    portEXIT_CRITICAL(&lock);
}

static bool hal_scan_start(void *ctx)
{
    (void)ctx;
    order_t order = {.kind = ORDER_SCAN};
    portENTER_CRITICAL(&lock);
    bool running = scan_state == NESP_SCAN_RUNNING;
    if (!running) {
        scan_state = NESP_SCAN_RUNNING;
        scan_count = 0;
    }
    portEXIT_CRITICAL(&lock);
    if (running) {
        return true;                /* already looking */
    }
    if (xQueueSend(orders, &order, 0) != pdTRUE) {
        portENTER_CRITICAL(&lock);
        scan_state = NESP_SCAN_IDLE;
        portEXIT_CRITICAL(&lock);
        return false;
    }
    return true;
}

static uint8_t hal_scan_state(void *ctx, uint8_t *count)
{
    (void)ctx;
    portENTER_CRITICAL(&lock);
    uint8_t state = scan_state;
    *count = state == NESP_SCAN_DONE ? scan_count : 0;
    portEXIT_CRITICAL(&lock);
    return state;
}

static bool hal_scan_result(void *ctx, uint8_t index, nesp_network_t *out)
{
    (void)ctx;
    bool found = false;
    portENTER_CRITICAL(&lock);
    if (scan_state == NESP_SCAN_DONE && index < scan_count) {
        *out = networks[index];
        found = true;
    }
    portEXIT_CRITICAL(&lock);
    return found;
}

static bool hal_join(void *ctx, const char *name, uint8_t name_len,
                     const char *password, uint8_t password_len)
{
    (void)ctx;
    static order_t order;           /* only the link task calls this */
    memset(&order, 0, sizeof(order));
    order.kind = ORDER_JOIN;
    order.name_len = name_len;
    order.password_len = password_len;
    memcpy(order.name, name, name_len);
    memcpy(order.password, password, password_len);
    bool sent = xQueueSend(orders, &order, 0) == pdTRUE;
    memset(&order, 0, sizeof(order));
    if (sent) {
        /* So that the console's next question is answered "joining", not
         * with whatever the last network came to. */
        portENTER_CRITICAL(&lock);
        memset(&wifi, 0, sizeof(wifi));
        wifi.state = NESP_WIFI_JOINING;
        wifi.name_len = name_len;
        memcpy(wifi.name, name, name_len);
        portEXIT_CRITICAL(&lock);
    }
    return sent;
}

static void hal_forget(void *ctx)
{
    (void)ctx;
    order_t order = {.kind = ORDER_FORGET};
    xQueueSend(orders, &order, 0);
    portENTER_CRITICAL(&lock);
    memset(&wifi, 0, sizeof(wifi));
    wifi.state = NESP_WIFI_NONE;
    portEXIT_CRITICAL(&lock);
}

static void hal_app(void *ctx, const char *id, uint8_t version)
{
    (void)ctx;
    portENTER_CRITICAL(&lock);
    memcpy(app_id, id, NESP_APP_ID);
    app_version = version;
    portEXIT_CRITICAL(&lock);
}

/* Memory for something big. From the PSRAM if the board has it; a piece
 * small enough not to starve Wi-Fi and TLS may come from the chip's own. */
#define INTERNAL_MOST (64 * 1024)

static void hal_watch(void *ctx, const char *text)
{
    (void)ctx;
    portENTER_CRITICAL(&lock);
    strncpy(watched, text, RADIO_WATCH_MAX - 1);
    watched[RADIO_WATCH_MAX - 1] = 0;
    watch_news = true;
    portEXIT_CRITICAL(&lock);
}

static void hal_show(void *ctx, uint8_t row, const char *text)
{
    (void)ctx;
    if (row >= 2) {
        return;
    }
    portENTER_CRITICAL(&lock);
    strncpy(shown[row], text, RADIO_SHOWN_MAX - 1);
    shown[row][RADIO_SHOWN_MAX - 1] = 0;
    portEXIT_CRITICAL(&lock);
}

static void *hal_alloc(void *ctx, size_t bytes)
{
    (void)ctx;
    void *memory = heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM);
    if (memory == NULL && bytes <= INTERNAL_MOST) {
        memory = heap_caps_malloc(bytes, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    }
    /* Nothing is logged here: this is the link's task, between a request
     * and its reply. main.cpp's report says what memory is left. */
    return memory;
}

static void hal_release(void *ctx, void *memory)
{
    (void)ctx;
    heap_caps_free(memory);
}

/* What a service's handler, in the link's task, and its sink, in the
 * fetch's, both touch. */
static portMUX_TYPE service_lock = portMUX_INITIALIZER_UNLOCKED;

static void hal_lock(void *ctx)
{
    (void)ctx;
    portENTER_CRITICAL(&service_lock);
}

static void hal_unlock(void *ctx)
{
    (void)ctx;
    portEXIT_CRITICAL(&service_lock);
}

/* --- Wi-Fi's events ---------------------------------------------------------- */

static uint8_t why_from(uint8_t reason)
{
    switch (reason) {
    case WIFI_REASON_AUTH_FAIL:
    case WIFI_REASON_AUTH_EXPIRE:
    case WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT:
    case WIFI_REASON_HANDSHAKE_TIMEOUT:
    case WIFI_REASON_MIC_FAILURE:
        return NESP_WHY_PASSWORD;
    case WIFI_REASON_NO_AP_FOUND:
        return NESP_WHY_NO_NETWORK;
    default:
        return NESP_WHY_OTHER;
    }
}

static uint8_t auth_from(wifi_auth_mode_t mode)
{
    switch (mode) {
    case WIFI_AUTH_OPEN:
        return NESP_AUTH_OPEN;
    case WIFI_AUTH_WEP:
    case WIFI_AUTH_WPA_PSK:
    case WIFI_AUTH_WPA2_PSK:
    case WIFI_AUTH_WPA_WPA2_PSK:
    case WIFI_AUTH_WPA3_PSK:
    case WIFI_AUTH_WPA2_WPA3_PSK:
        return NESP_AUTH_PASSWORD;
    default:
        return NESP_AUTH_OTHER;     /* enterprise, and whatever comes later */
    }
}

/* A scan is over: keep the strongest networks, one line for each name. The
 * list is made apart and copied in, so that the lock is held only for the
 * copy. */
static void take_scan(void)
{
    static wifi_ap_record_t records[NESP_SCAN_MAX];
    static nesp_network_t found[NESP_SCAN_MAX];
    uint16_t count = NESP_SCAN_MAX;
    uint8_t kept = 0;
    esp_err_t err = esp_wifi_scan_get_ap_records(&count, records);   /* strongest first */
    for (uint16_t index = 0; err == ESP_OK && index < count; index++) {
        const wifi_ap_record_t *record = &records[index];
        size_t length = strnlen((const char *)record->ssid, NESP_NAME_MAX);
        bool seen = length == 0;        /* one that hides its name */
        for (uint8_t at = 0; at < kept && !seen; at++) {
            seen = found[at].name_len == length
                   && memcmp(found[at].name, record->ssid, length) == 0;
        }
        if (seen) {
            continue;
        }
        nesp_network_t *network = &found[kept++];
        memset(network, 0, sizeof(*network));
        network->rssi = record->rssi;
        network->auth = auth_from(record->authmode);
        network->channel = record->primary;
        network->name_len = (uint8_t)length;
        memcpy(network->name, record->ssid, length);
    }
    portENTER_CRITICAL(&lock);
    memcpy(networks, found, sizeof(networks));
    scan_count = kept;
    scan_state = err == ESP_OK ? NESP_SCAN_DONE : NESP_SCAN_FAILED;
    portEXIT_CRITICAL(&lock);
}

static void on_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    if (base == WIFI_EVENT && id == WIFI_EVENT_SCAN_DONE) {
        take_scan();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        const wifi_event_sta_disconnected_t *event = data;
        bool again = false;
        portENTER_CRITICAL(&lock);
        wifi.rssi = 0;
        memset(wifi.address, 0, sizeof(wifi.address));
        if (!want_joined) {
            /* forgotten: hal_forget has set the state */
        } else if (tries_left > 1) {
            tries_left--;
            again = true;           /* a join the console asked for: once more */
        } else if (tries_left == 1) {
            tries_left = 0;
            wifi.state = NESP_WIFI_FAILED;
            wifi.why = why_from(event->reason);
        } else if (wifi.state != NESP_WIFI_FAILED) {
            /* It dropped, or the saved network was not there at start: the
             * worker tries again. A failure the console was told of stays
             * for it to see until a try gets somewhere. */
            wifi.state = NESP_WIFI_IDLE;
        }
        portEXIT_CRITICAL(&lock);
        if (again) {
            esp_wifi_connect();
        }
        retry_at = xTaskGetTickCount() + pdMS_TO_TICKS(RETRY_MS);
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        const ip_event_got_ip_t *event = data;
        uint32_t address = event->ip_info.ip.addr;      /* network byte order */
        portENTER_CRITICAL(&lock);
        tries_left = 0;
        wifi.state = NESP_WIFI_JOINED;
        wifi.why = NESP_WHY_NONE;
        memcpy(wifi.address, &address, 4);
        portEXIT_CRITICAL(&lock);
    }
}

/* --- the worker: everything that takes time ---------------------------------- */

static void begin_join(void)
{
    portENTER_CRITICAL(&lock);
    wifi.state = NESP_WIFI_JOINING;
    wifi.why = NESP_WHY_NONE;
    portEXIT_CRITICAL(&lock);
    esp_wifi_connect();
}

static void do_order(order_t *order)
{
    switch (order->kind) {
    case ORDER_SCAN:
        if (esp_wifi_scan_start(NULL, false) != ESP_OK) {
            portENTER_CRITICAL(&lock);
            scan_state = NESP_SCAN_FAILED;
            portEXIT_CRITICAL(&lock);
        }
        break;
    case ORDER_JOIN: {
        wifi_config_t config;
        memset(&config, 0, sizeof(config));
        memcpy(config.sta.ssid, order->name, order->name_len);
        memcpy(config.sta.password, order->password, order->password_len);
        config.sta.threshold.authmode =
            order->password_len == 0 ? WIFI_AUTH_OPEN : WIFI_AUTH_WEP;
        /* Leaving the old network raises a disconnect, which is not this
         * network's failure. If it comes late it costs one of the tries. */
        portENTER_CRITICAL(&lock);
        want_joined = false;
        portEXIT_CRITICAL(&lock);
        esp_wifi_disconnect();
        esp_wifi_set_config(WIFI_IF_STA, &config);  /* and saves it */
        memset(&config, 0, sizeof(config));
        portENTER_CRITICAL(&lock);
        tries_left = JOIN_TRIES;
        want_joined = true;
        portEXIT_CRITICAL(&lock);
        begin_join();
        break;
    }
    case ORDER_FORGET: {
        wifi_config_t config;
        memset(&config, 0, sizeof(config));
        portENTER_CRITICAL(&lock);
        want_joined = false;
        tries_left = 0;
        portEXIT_CRITICAL(&lock);
        esp_wifi_disconnect();
        esp_wifi_set_config(WIFI_IF_STA, &config);
        break;
    }
    }
    memset(order, 0, sizeof(*order));
}

static void worker(void *arg)
{
    (void)arg;
    static order_t order;
    for (;;) {
        if (xQueueReceive(orders, &order, pdMS_TO_TICKS(SIGNAL_MS)) == pdTRUE) {
            do_order(&order);
            continue;
        }
        portENTER_CRITICAL(&lock);
        uint8_t state = wifi.state;
        bool retry = want_joined && tries_left == 0
                     && (state == NESP_WIFI_IDLE || state == NESP_WIFI_FAILED);
        portEXIT_CRITICAL(&lock);
        if (state == NESP_WIFI_JOINED) {
            wifi_ap_record_t record;
            if (esp_wifi_sta_get_ap_info(&record) == ESP_OK) {
                portENTER_CRITICAL(&lock);
                wifi.rssi = record.rssi;
                portEXIT_CRITICAL(&lock);
            }
        } else if (retry && (int32_t)(xTaskGetTickCount() - retry_at) >= 0) {
            /* The saved network, again. */
            retry_at = xTaskGetTickCount() + pdMS_TO_TICKS(RETRY_MS);
            esp_wifi_connect();
        }
    }
}

void radio_start(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_event, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_FLASH));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    /* Power saving holds received packets for the next beacon, up to
     * 100 ms: several of the console's frames (nes-drmario). */
    esp_wifi_set_ps(WIFI_PS_NONE);

    wifi_config_t saved;
    memset(&saved, 0, sizeof(saved));
    esp_wifi_get_config(WIFI_IF_STA, &saved);
    size_t length = strnlen((const char *)saved.sta.ssid, NESP_NAME_MAX);
    memset(&wifi, 0, sizeof(wifi));
    wifi.state = length == 0 ? NESP_WIFI_NONE : NESP_WIFI_IDLE;
    wifi.name_len = (uint8_t)length;
    memcpy(wifi.name, saved.sta.ssid, length);
    memset(&saved, 0, sizeof(saved));
    want_joined = length != 0;

    ESP_ERROR_CHECK(esp_wifi_start());
    if (want_joined) {
        begin_join();
    }
    /* The time of day, once there is a network to ask. */
    esp_sntp_config_t sntp = ESP_NETIF_SNTP_DEFAULT_CONFIG("pool.ntp.org");
    esp_netif_sntp_init(&sntp);
    xTaskCreate(worker, "radio", WORKER_STACK, NULL, WORKER_PRIORITY, NULL);
    fetch_start();
    conn_start();
    ESP_LOGI(TAG, "Wi-Fi started; %s", want_joined ? "joining the saved network"
                                                    : "no network saved");
}

const nesp_hal_t *radio_hal(void)
{
    /* Orders wait here until radio_start has a worker to take them. */
    orders = xQueueCreate(4, sizeof(order_t));
    hal.ctx = NULL;
    hal.board = hal_board;
    hal.board_name = hal_board_name;
    hal.battery = hal_battery;
    hal.drive = usb_drive;
    hal.time = hal_time;
    hal.wifi = hal_wifi;
    hal.scan_start = hal_scan_start;
    hal.scan_state = hal_scan_state;
    hal.scan_result = hal_scan_result;
    hal.join = hal_join;
    hal.forget = hal_forget;
    hal.app = hal_app;
    hal.fetch = fetch_begin;
    hal.fetch_stop = fetch_stop;
    hal.alloc = hal_alloc;
    hal.release = hal_release;
    hal.lock = hal_lock;
    hal.unlock = hal_unlock;
    hal.line_rate = link_line_rate;
    hal.line_write = link_line_write;
    hal.line_idle = link_line_idle;
    hal.line_hear = link_line_hear;
    hal.tracks = store_tracks;
    hal.track_size = store_track_size;
    hal.track_read = store_track_read;
    hal.show = hal_show;
    hal.watch = hal_watch;
    hal.peer_state = conn_state;
    hal.peer_listen = conn_listen;
    hal.peer_call = conn_call;
    hal.peer_close = conn_close;
    hal.peer_send = conn_send;
    hal.peer_recv = conn_recv;
    hal.peer_last = conn_last;
    hal.peer_keep = conn_keep;
    hal.peer_rtt = conn_rtt;
    hal.peer_note = conn_note;
    hal.peer_noted = conn_noted;
    hal.peer_spread = conn_spread;
    return &hal;
}

void radio_set_battery(uint8_t percent)
{
    battery = percent;
}

void radio_wifi(nesp_wifi_t *out)
{
    hal_wifi(NULL, out);
}

void radio_app(char *id, uint8_t *version)
{
    portENTER_CRITICAL(&lock);
    memcpy(id, app_id, NESP_APP_ID);
    *version = app_version;
    portEXIT_CRITICAL(&lock);
}

bool radio_watch(char *out)
{
    portENTER_CRITICAL(&lock);
    bool news = watch_news;
    watch_news = false;
    memcpy(out, watched, RADIO_WATCH_MAX);
    portEXIT_CRITICAL(&lock);
    return news;
}

void radio_shown(uint8_t row, char *out)
{
    portENTER_CRITICAL(&lock);
    memcpy(out, shown[row & 1], RADIO_SHOWN_MAX);
    portEXIT_CRITICAL(&lock);
}
