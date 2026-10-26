/* A Bluetooth keyboard, for a console's text (issue #9).
 *
 * For now this is the spike: a measurement of what Bluetooth costs a
 * StickS3 before anything is built on it. Built only when asked for:
 *
 *   idf.py -B build-kbd -D SDKCONFIG=build-kbd/sdkconfig -D IDF_TARGET=esp32s3 \
 *          -D "SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.defaults.kbd" \
 *          -D NESP_KBD_SPIKE=1 build
 *   idf.py -B build-kbd -p /dev/cu.usbmodemXXXX flash monitor
 *
 * Bluetooth is on from the start, and stays on. With no keyboard paired,
 * the nesp32 looks for one for SCAN_MS, and pairs with the keyboard it
 * hears best: the keyboard is to be put in its pairing mode first. Once
 * paired, the keyboard is kept over power-off, and connected again
 * whenever it is heard from (a key pressed wakes most). What is typed goes
 * to the log, a key at a time, with the reports it came in.
 *
 * The chip has Bluetooth LE and no Classic, so a keyboard has to be an LE
 * one. Pairing is "Just Works": the nesp32 says it has no display and no
 * keys, and asks the keyboard to type nothing. The nesp32 is a central,
 * NimBLE's host runs in a task of its own, and esp_hid's host reads the
 * keyboard's services and sends what comes from it to hid_event.
 *
 * Keys are kept, as characters, until keyboard_read takes them: printable
 * ASCII with Shift and Caps Lock (a US layout), and the control codes
 * below. A key held down is one key: there is no repeat.
 */
#include "keyboard.h"

#include "sdkconfig.h"

#if CONFIG_BT_NIMBLE_ENABLED

#include <string.h>

#include "esp_hidh.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"

#define SCAN_MS 5000
#define SEEN_MAX 8                  /* keyboards a scan keeps */
#define SEEN_NAME_MAX 24
#define HELD 32                     /* keys typed and not yet read */
#define TASK_STACK 6144             /* opening a keyboard reads its services in this task */
#define HID_STACK 4096
#define TASK_PRIORITY 2
#define OPENING_US 5000000          /* how often the log hears that it is still opening */

/* What is not a character. */
#define KEY_BACKSPACE 0x08
#define KEY_TAB 0x09
#define KEY_ENTER 0x0A
#define KEY_UP 0x11
#define KEY_DOWN 0x12
#define KEY_LEFT 0x13
#define KEY_RIGHT 0x14
#define KEY_ESCAPE 0x1B

/* HID's usages (the USB HID usage tables, the keyboard page). */
#define USAGE_A 0x04
#define USAGE_SLASH 0x38            /* the last with a character */
#define USAGE_CAPS_LOCK 0x39
#define USAGE_RIGHT 0x4F
#define USAGE_UP 0x52
#define USAGE_ROLLOVER 0x01         /* too many keys down: the report means nothing */
#define SHIFT 0x22                  /* the left and right Shift in the modifiers' byte */
#define CHORD 0xDD                  /* Ctrl, Alt and GUI: a key with one is not typed */

/* Appearances (Bluetooth's assigned numbers): the HID ones, and among them
 * a keyboard. */
#define APPEARANCE_HID 0x03C0
#define APPEARANCE_HID_LAST 0x03CF
#define APPEARANCE_KEYBOARD 0x03C1
#define UUID_HID 0x1812

#define OPENED BIT0
#define CLOSED BIT1
#define SCANNED BIT2

static const char *TAG = "keyboard";

/* Each usage from USAGE_A to USAGE_SLASH, and with Shift. Caps Lock is for
 * the letters alone. */
static const char PLAIN[] = "abcdefghijklmnopqrstuvwxyz1234567890"
                            "\n\x1b\b\t -=[]\\#;'`,./";
static const char SHIFTED[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZ!@#$%^&*()"
                              "\n\x1b\b\t _+{}|~:\"~<>?";
_Static_assert(sizeof(PLAIN) - 1 == USAGE_SLASH - USAGE_A + 1, "a character for every usage");
_Static_assert(sizeof(SHIFTED) == sizeof(PLAIN), "a shifted character for every usage");
/* Right, Left, Down and Up, as the usages run. */
static const uint8_t ARROWS[] = {KEY_RIGHT, KEY_LEFT, KEY_DOWN, KEY_UP};

typedef struct {
    ble_addr_t addr;
    int8_t rssi;
    uint16_t appearance;
    char name[SEEN_NAME_MAX + 1];
} seen_t;

static portMUX_TYPE held_lock = portMUX_INITIALIZER_UNLOCKED;
static uint8_t held[HELD];
static uint8_t held_first;
static uint8_t held_count;

static EventGroupHandle_t happened;
static seen_t seen[SEEN_MAX];
static int seen_count;
static uint8_t down[6];             /* the keys of the last report */
static bool caps;

void ble_store_config_init(void);

static void keep(uint8_t key)
{
    portENTER_CRITICAL(&held_lock);
    if (held_count < HELD) {
        held[(held_first + held_count) % HELD] = key;
        held_count++;
    }
    portEXIT_CRITICAL(&held_lock);
    if (key >= 0x20 && key < 0x7F) {
        ESP_LOGI(TAG, "typed '%c'", key);
    } else {
        ESP_LOGI(TAG, "typed $%02x", key);
    }
}

size_t keyboard_read(uint8_t *out, size_t max)
{
    size_t count = 0;
    portENTER_CRITICAL(&held_lock);
    while (count < max && held_count != 0) {
        out[count++] = held[held_first];
        held_first = (uint8_t)((held_first + 1) % HELD);
        held_count--;
    }
    portEXIT_CRITICAL(&held_lock);
    return count;
}

/* A key that has gone down. */
static void pressed(uint8_t usage, uint8_t modifiers)
{
    if (usage == USAGE_CAPS_LOCK) {
        caps = !caps;
        return;
    }
    if ((modifiers & CHORD) != 0) {
        return;
    }
    if (usage >= USAGE_RIGHT && usage <= USAGE_UP) {
        keep(ARROWS[usage - USAGE_RIGHT]);
        return;
    }
    if (usage < USAGE_A || usage > USAGE_SLASH) {
        return;
    }
    char plain = PLAIN[usage - USAGE_A];
    bool shift = (modifiers & SHIFT) != 0;
    if (caps && plain >= 'a' && plain <= 'z') {
        shift = !shift;
    }
    keep((uint8_t)(shift ? SHIFTED[usage - USAGE_A] : plain));
}

/* A keyboard's input report: its modifiers, and the keys down. The boot
 * report has a byte that is nothing between the two, and is 8 bytes; a
 * report of the keyboard's own may leave the byte out (an MX Keys S's is
 * 7). A key is typed when it is in a report and was not in the one
 * before. */
static void report(const uint8_t *data, size_t length)
{
    ESP_LOG_BUFFER_HEX_LEVEL(TAG, data, length, ESP_LOG_DEBUG);
    size_t first = length >= 8 ? 2 : 1;
    if (length <= first) {
        return;
    }
    uint8_t modifiers = data[0];
    const uint8_t *keys = data + first;
    size_t count = length - first < sizeof(down) ? length - first : sizeof(down);
    for (size_t at = 0; at < count; at++) {
        if (keys[at] == USAGE_ROLLOVER) {
            return;
        }
    }
    for (size_t at = 0; at < count; at++) {
        if (keys[at] != 0 && memchr(down, keys[at], sizeof(down)) == NULL) {
            pressed(keys[at], modifiers);
        }
    }
    memset(down, 0, sizeof(down));
    memcpy(down, keys, count);
}

static void hid_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    (void)base;
    esp_hidh_event_data_t *param = data;
    switch ((esp_hidh_event_t)id) {
    case ESP_HIDH_OPEN_EVENT:
        if (param->open.status == ESP_OK) {
            ESP_LOGI(TAG, "connected: %s", esp_hidh_dev_name_get(param->open.dev));
            memset(down, 0, sizeof(down));
            xEventGroupSetBits(happened, OPENED);
        } else {
            ESP_LOGW(TAG, "could not connect");
        }
        break;
    case ESP_HIDH_INPUT_EVENT:
        ESP_LOGI(TAG, "report: %s, map %u, id %u, %u bytes", esp_hid_usage_str(param->input.usage),
                 param->input.map_index, param->input.report_id, param->input.length);
        ESP_LOG_BUFFER_HEX(TAG, param->input.data, param->input.length);
        if (param->input.usage == ESP_HID_USAGE_KEYBOARD) {
            report(param->input.data, param->input.length);
        }
        break;
    case ESP_HIDH_BATTERY_EVENT:
        ESP_LOGI(TAG, "keyboard's battery: %d%%", param->battery.level);
        break;
    case ESP_HIDH_CLOSE_EVENT:
        ESP_LOGI(TAG, "disconnected (reason %d)", param->close.reason);
        xEventGroupSetBits(happened, CLOSED);
        break;
    default:
        break;
    }
}

/* What a scan heard: the HID ones, by their address. An advertisement and
 * the answer to a scan come apart, and either may have the name. */
static int scan_event(struct ble_gap_event *event, void *arg)
{
    (void)arg;
    if (event->type == BLE_GAP_EVENT_DISC_COMPLETE) {
        xEventGroupSetBits(happened, SCANNED);
        return 0;
    }
    if (event->type != BLE_GAP_EVENT_DISC) {
        return 0;
    }
    const struct ble_gap_disc_desc *disc = &event->disc;
    struct ble_hs_adv_fields fields;
    if (ble_hs_adv_parse_fields(&fields, disc->data, disc->length_data) != 0) {
        return 0;
    }
    bool hid = fields.appearance_is_present && fields.appearance >= APPEARANCE_HID
               && fields.appearance <= APPEARANCE_HID_LAST;
    for (int index = 0; index < fields.num_uuids16; index++) {
        hid |= ble_uuid_u16(&fields.uuids16[index].u) == UUID_HID;
    }
    seen_t *one = NULL;
    for (int index = 0; index < seen_count; index++) {
        if (ble_addr_cmp(&seen[index].addr, &disc->addr) == 0) {
            one = &seen[index];
        }
    }
    if (one == NULL) {
        if (!hid || seen_count == SEEN_MAX) {
            return 0;
        }
        one = &seen[seen_count++];
        memset(one, 0, sizeof(*one));
        one->addr = disc->addr;
    }
    one->rssi = disc->rssi;
    if (fields.appearance_is_present) {
        one->appearance = fields.appearance;
    }
    if (fields.name != NULL) {
        size_t length = fields.name_len < SEEN_NAME_MAX ? fields.name_len : SEEN_NAME_MAX;
        memcpy(one->name, fields.name, length);
        one->name[length] = 0;
    }
    return 0;
}

/* Look for keyboards in their pairing mode. Returns the one to pair with,
 * or NULL: a keyboard first, and the one heard best. */
static const seen_t *scan(void)
{
    uint8_t own;
    if (ble_hs_id_infer_auto(0, &own) != 0) {
        return NULL;
    }
    struct ble_gap_disc_params params = {.filter_duplicates = 1};   /* active: names too */
    seen_count = 0;
    xEventGroupClearBits(happened, SCANNED);
    ESP_LOGI(TAG, "looking for a keyboard for %d s: put it in its pairing mode",
             SCAN_MS / 1000);
    if (ble_gap_disc(own, SCAN_MS, &params, scan_event, NULL) != 0) {
        return NULL;
    }
    xEventGroupWaitBits(happened, SCANNED, pdTRUE, pdFALSE, portMAX_DELAY);
    const seen_t *best = NULL;
    for (int index = 0; index < seen_count; index++) {
        const seen_t *one = &seen[index];
        ESP_LOGI(TAG, "heard %s, appearance $%04x, %d dBm", one->name[0] ? one->name : "(no name)",
                 one->appearance, one->rssi);
        bool keyboard = one->appearance == APPEARANCE_KEYBOARD;
        bool best_keyboard = best != NULL && best->appearance == APPEARANCE_KEYBOARD;
        if (best == NULL || keyboard > best_keyboard
            || (keyboard == best_keyboard && one->rssi > best->rssi)) {
            best = one;
        }
    }
    return best;
}

/* For the log: what happens to the connection, which esp_hid's host says
 * little of. A listener hears these besides the connection's own handler. */
static int gap_watch(struct ble_gap_event *event, void *arg)
{
    (void)arg;
    switch (event->type) {
    case BLE_GAP_EVENT_CONNECT:
        ESP_LOGI(TAG, "gap: connect, status %d", event->connect.status);
        break;
    case BLE_GAP_EVENT_DISCONNECT:
        ESP_LOGI(TAG, "gap: disconnect, reason $%x", event->disconnect.reason);
        break;
    case BLE_GAP_EVENT_ENC_CHANGE: {
        struct ble_gap_conn_desc desc;
        if (ble_gap_conn_find(event->enc_change.conn_handle, &desc) == 0) {
            ESP_LOGI(TAG, "gap: encryption, status $%x: encrypted %d, authenticated %d, bonded %d",
                     event->enc_change.status, desc.sec_state.encrypted,
                     desc.sec_state.authenticated, desc.sec_state.bonded);
        } else {
            ESP_LOGI(TAG, "gap: encryption, status $%x", event->enc_change.status);
        }
        break;
    }
    case BLE_GAP_EVENT_CONN_UPDATE:
        ESP_LOGI(TAG, "gap: connection updated, status %d", event->conn_update.status);
        break;
    case BLE_GAP_EVENT_REPEAT_PAIRING:
        ESP_LOGI(TAG, "gap: the keyboard pairs again");
        break;
    case BLE_GAP_EVENT_IDENTITY_RESOLVED:
        ESP_LOGI(TAG, "gap: identity resolved");
        break;
    default:
        break;
    }
    return 0;
}

static void still_opening(void *arg)
{
    int64_t *began = arg;
    ESP_LOGW(TAG, "still opening the keyboard, %ld s", (long)((esp_timer_get_time() - *began) / 1000000));
}

/* esp_hid's host connects, reads the keyboard's services and listens to
 * its reports, and waits for each step with no end: the log says so while
 * it waits. */
static esp_hidh_dev_t *open(ble_addr_t addr)
{
    static int64_t began;
    static esp_timer_handle_t timer;
    if (timer == NULL) {
        esp_timer_create_args_t args = {.callback = still_opening, .arg = &began, .name = "opening"};
        esp_timer_create(&args, &timer);
    }
    began = esp_timer_get_time();
    esp_timer_start_periodic(timer, OPENING_US);
    esp_hidh_dev_t *device = esp_hidh_dev_open(addr.val, ESP_HID_TRANSPORT_BLE, addr.type);
    esp_timer_stop(timer);
    ESP_LOGI(TAG, "open %s after %ld ms", device != NULL ? "done" : "failed",
             (long)((esp_timer_get_time() - began) / 1000));
    return device;
}

static void host(void *arg)
{
    (void)arg;
    nimble_port_run();              /* until nimble_port_stop */
    nimble_port_freertos_deinit();
}

/* Connect to the keyboard that was paired, or find one to pair, and stay
 * connected; again whenever it goes. */
static void run(void *arg)
{
    (void)arg;
    while (!ble_hs_synced()) {
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    static struct ble_gap_event_listener listener;
    ble_gap_event_listener_register(&listener, gap_watch, NULL);
    for (;;) {
        ble_addr_t paired;
        int count = 0;
        esp_hidh_dev_t *device = NULL;
        xEventGroupClearBits(happened, OPENED | CLOSED);
        if (ble_store_util_bonded_peers(&paired, &count, 1) == 0 && count != 0) {
            ESP_LOGI(TAG, "waiting for the paired keyboard: press a key");
            device = open(paired);
        } else {
            const seen_t *found = scan();
            if (found != NULL) {
                ESP_LOGI(TAG, "pairing with %s", found->name[0] ? found->name : "(no name)");
                device = open(found->addr);
            }
        }
        if (device != NULL) {
            xEventGroupWaitBits(happened, CLOSED, pdTRUE, pdFALSE, portMAX_DELAY);
        } else {
            vTaskDelay(pdMS_TO_TICKS(1000));
        }
    }
}

void keyboard_start(void)
{
#ifdef NESP_KBD_SPIKE
    happened = xEventGroupCreate();
    /* What esp_hid's host does as it opens a keyboard. */
    esp_log_level_set("NIMBLE_HIDH", ESP_LOG_DEBUG);
    esp_log_level_set("ESP_HIDH", ESP_LOG_DEBUG);
    ESP_ERROR_CHECK(nimble_port_init());
    esp_hidh_config_t config = {
        .callback = hid_event,
        .event_stack_size = HID_STACK,
        .callback_arg = NULL,
    };
    ESP_ERROR_CHECK(esp_hidh_init(&config));
    /* After esp_hidh_init, which sets a keyboard's way of pairing. */
    ble_hs_cfg.sm_io_cap = BLE_HS_IO_NO_INPUT_OUTPUT;
    ble_hs_cfg.sm_bonding = 1;
    ble_hs_cfg.sm_mitm = 0;
    ble_hs_cfg.sm_our_key_dist = BLE_SM_PAIR_KEY_DIST_ENC | BLE_SM_PAIR_KEY_DIST_ID;
    ble_hs_cfg.sm_their_key_dist = BLE_SM_PAIR_KEY_DIST_ENC | BLE_SM_PAIR_KEY_DIST_ID;
    ble_hs_cfg.store_status_cb = ble_store_util_status_rr;
    ble_store_config_init();
    nimble_port_freertos_init(host);
    xTaskCreate(run, "keyboard", TASK_STACK, NULL, TASK_PRIORITY, NULL);
    ESP_LOGI(TAG, "Bluetooth on");
#endif
}

#else

void keyboard_start(void)
{
}

size_t keyboard_read(uint8_t *out, size_t max)
{
    (void)out;
    (void)max;
    return 0;
}

#endif
