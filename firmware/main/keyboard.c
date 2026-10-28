/* A Bluetooth keyboard, for a ROM's text: the hardware under KBD
 * (nesp_hal_t's kbd_*, docs/PROTOCOL.md).
 *
 * A StickS3's chip has Bluetooth LE and no Classic, so a keyboard has to be
 * an LE one. The nesp32 is a central, NimBLE's host runs in a task of its
 * own, and esp_hid's host reads a keyboard's services and sends what comes
 * from it to hid_event. (firmware/components/esp_hid is ESP-IDF's, with a
 * fix its NimBLE host needs.)
 *
 * Bluetooth is on only while a ROM has KBD in use, and a keyboard is paired
 * or one is being looked for: it shares the radio with Wi-Fi, and takes
 * some 75 KB of the chip's own memory. A SCAN with Bluetooth off turns it
 * on, and is BUSY until it is, so a ROM that asks again has its scan a
 * second or so later; it stays on through the pairing, and from then on
 * there is a keyboard paired. It is turned off OFF_MS after KBD was last
 * let go of, so that a hello that asks for KBD again, which lets go of it
 * and takes it again at once, leaves the keyboard connected.
 *
 * Everything that waits is the keyboard's task's, run(). What the console
 * asks only leaves an order for it and wakes it. The one wait it cannot
 * leave by itself is for the paired keyboard to wake (a connection that is
 * made only when a key is pressed on it, or given up after 30 s);
 * keyboard_poll, from the main task, calls that off whenever there is an
 * order to see to.
 *
 * Pairing is "Just Works": the nesp32 says it has no screen and no keys,
 * and asks the keyboard to type nothing. One keyboard is paired at a time.
 * Its bond is NimBLE's, kept in NVS, and its name is kept beside the
 * nesp32's other settings.
 *
 * Keys are kept, as characters, until KBD takes them: printable ASCII with
 * Shift and Caps Lock (a US layout), and NESP_KEY_*. A key held down is
 * typed again after REPEAT_DELAY_MS, and every REPEAT_EVERY_MS from then
 * on, as a computer does: the keyboard says only which keys are down. The
 * last key to go down is the one repeated, and Enter and Escape never are,
 * since each is an order to a ROM. What is typed goes to the log only at
 * the debug level, as it may be a password.
 */
#include "keyboard.h"

#include <string.h>

#include "sdkconfig.h"

#if CONFIG_BT_NIMBLE_ENABLED

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
#include "nvs.h"

#define SETTINGS "nesp32"           /* radio.c's and conn.c's too */
#define SETTING_KEYBOARD "keyboard" /* the paired keyboard's name */

#define OFF_MS 2000
#define SCAN_MS 5000
#define SCANNED_MS 60000            /* what a scan found is offered this long */
#define CLOSE_MS 3000
#define SYNC_MS 3000
#define WAKE_MS 100                 /* the task looks at its orders at least this often */
#define HELD 64                     /* keys typed and not yet taken */
#define TASK_STACK 6144             /* opening a keyboard reads its services in this task */
#define HID_STACK 4096
#define TASK_PRIORITY 2
#define REPEAT_DELAY_MS 500
#define REPEAT_EVERY_MS 40

/* HID's usages (the USB HID usage tables, the keyboard page). */
#define USAGE_A 0x04
#define USAGE_ENTER 0x28
#define USAGE_ESCAPE 0x29
#define USAGE_SLASH 0x38            /* the last with a character */
#define USAGE_CAPS_LOCK 0x39
#define USAGE_PAGE_UP 0x4B
#define USAGE_PAGE_DOWN 0x4E
#define USAGE_RIGHT 0x4F
#define USAGE_UP 0x52
#define USAGE_ROLLOVER 0x01         /* too many keys down: the report means nothing */
#define SHIFT 0x22                  /* the left and right Shift in the modifiers' byte */
#define CHORD 0xDD                  /* Ctrl, Alt and GUI: a key with one is not typed */
#define CTRL 0x11                   /* the left and right Ctrl */

/* Appearances (Bluetooth's assigned numbers). A scan offers what says it is
 * a keyboard, and what offers HID and says nothing more of itself. */
#define APPEARANCE_HID 0x03C0
#define APPEARANCE_KEYBOARD 0x03C1
#define UUID_HID 0x1812

#define OPENED BIT0
#define CLOSED BIT1
#define SCANNED BIT2
#define ENCRYPTED BIT3

static const char *TAG = "keyboard";

/* Each usage from USAGE_A to USAGE_SLASH, and with Shift. Caps Lock is for
 * the letters alone. */
static const char PLAIN[] = "abcdefghijklmnopqrstuvwxyz1234567890"
                            "\n\x1b\b\t -=[]\\#;'`,./";
static const char SHIFTED[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZ!@#$%^&*()"
                              "\n\x1b\b\t _+{}|~:\"~<>?";
_Static_assert(sizeof(PLAIN) - 1 == USAGE_SLASH - USAGE_A + 1, "a character for every usage");
_Static_assert(sizeof(SHIFTED) == sizeof(PLAIN), "a shifted character for every usage");
_Static_assert('\n' == NESP_KEY_ENTER && '\b' == NESP_KEY_BACKSPACE && '\t' == NESP_KEY_TAB
               && '\x1b' == NESP_KEY_ESCAPE, "the control keys are KBD's");
/* Right, Left, Down and Up, as the usages run. */
static const uint8_t ARROWS[] = {NESP_KEY_RIGHT, NESP_KEY_LEFT, NESP_KEY_DOWN, NESP_KEY_UP};

typedef struct {
    ble_addr_t addr;
    nesp_keyboard_t shown;
} seen_t;

/* What the link's task and this file's both touch, under the lock. */
static portMUX_TYPE lock = portMUX_INITIALIZER_UNLOCKED;
static bool want_on;
static bool looking;                /* a SCAN has asked for Bluetooth with none paired */
static int64_t let_go_at;           /* when KBD was last let go of, in microseconds */
static bool scan_asked;
static int pair_asked = -1;         /* the index of the one to pair with */
static bool forget_asked;
static bool running;                /* Bluetooth is on */
static bool connected;
static bool paired;
static nesp_keyboard_t paired_one;
static uint8_t doing;               /* SCANNING, PAIRING, SCANNED, FAILED, or 0 */
static int64_t scanned_at;
static seen_t found[NESP_KBD_FOUND_MAX];
static uint8_t found_count;
static uint8_t held[HELD];
static uint8_t held_first;
static uint8_t held_count;
static bool opening;                /* run() waits for a connection */
static bool cancelled;              /* keyboard_poll has called this wait off */
static uint8_t repeating;           /* the usage of the key held down that repeats, or 0 */
static uint8_t repeat_modifiers;    /* and the modifiers down with it now */

/* The keyboard's task's own. */
static TaskHandle_t task;
static EventGroupHandle_t happened;
static esp_hidh_dev_t *device;      /* the keyboard connected */
static struct ble_gap_event_listener listener;
static seen_t heard[NESP_KBD_FOUND_MAX];
static uint8_t heard_count;
static uint8_t down[6];             /* the keys of the last report */
static bool caps;
static esp_timer_handle_t repeater; /* the next repeat */

void ble_store_config_init(void);

/* --- what is typed ------------------------------------------------------------ */

static void keep(uint8_t key)
{
    portENTER_CRITICAL(&lock);
    if (held_count < HELD) {
        held[(held_first + held_count) % HELD] = key;
        held_count++;
    }
    portEXIT_CRITICAL(&lock);
    ESP_LOGD(TAG, "typed $%02x", key);
}

/* A key that has gone down. */
static void pressed(uint8_t usage, uint8_t modifiers)
{
    if (usage == USAGE_CAPS_LOCK) {
        caps = !caps;
        return;
    }
    if ((modifiers & CHORD) != 0) {
        /* But Ctrl with Enter or Escape, and nothing else of the chord's,
         * is the controller's Start or Select. */
        if ((modifiers & CHORD & ~CTRL) == 0 && (usage == USAGE_ENTER || usage == USAGE_ESCAPE)) {
            keep(usage == USAGE_ENTER ? NESP_KEY_START : NESP_KEY_SELECT);
        }
        return;
    }
    if (usage >= USAGE_RIGHT && usage <= USAGE_UP) {
        keep(ARROWS[usage - USAGE_RIGHT]);
        return;
    }
    if (usage == USAGE_PAGE_UP || usage == USAGE_PAGE_DOWN) {
        keep(usage == USAGE_PAGE_UP ? NESP_KEY_PAGE_UP : NESP_KEY_PAGE_DOWN);
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

/* Whether a key held down is typed again: one that types something, and
 * is not Enter or Escape. */
static bool repeats(uint8_t usage, uint8_t modifiers)
{
    if ((modifiers & CHORD) != 0) {
        return false;
    }
    if ((usage >= USAGE_RIGHT && usage <= USAGE_UP) || usage == USAGE_PAGE_UP
        || usage == USAGE_PAGE_DOWN) {
        return true;
    }
    if (usage < USAGE_A || usage > USAGE_SLASH) {
        return false;
    }
    char plain = PLAIN[usage - USAGE_A];
    return plain != '\n' && plain != '\x1b';
}

/* The key held down is typed again, if it still is, and again after
 * REPEAT_EVERY_MS. In esp_timer's task. */
static void repeat(void *arg)
{
    (void)arg;
    portENTER_CRITICAL(&lock);
    uint8_t usage = repeating;
    uint8_t modifiers = repeat_modifiers;
    portEXIT_CRITICAL(&lock);
    if (usage != 0) {
        pressed(usage, modifiers);
        esp_timer_start_once(repeater, (uint64_t)REPEAT_EVERY_MS * 1000);
    }
}

/* This key is the one that repeats now, or none (0). */
static void repeat_from(uint8_t usage, uint8_t modifiers)
{
    esp_timer_stop(repeater);       /* an error if it was not waiting, which is nothing */
    portENTER_CRITICAL(&lock);
    repeating = usage;
    repeat_modifiers = modifiers;
    portEXIT_CRITICAL(&lock);
    if (usage != 0) {
        esp_timer_start_once(repeater, (uint64_t)REPEAT_DELAY_MS * 1000);
    }
}

/* A keyboard's input report: its modifiers, and the keys down. The boot
 * report has a byte that is nothing between the two, and is 8 bytes; a
 * report of the keyboard's own may leave the byte out (an MX Keys S's is
 * 7). A key is typed when it is in a report and was not in the one
 * before, and the last of those that repeats is the key that does. */
static void report(const uint8_t *data, size_t length)
{
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
    uint8_t newest = 0;
    for (size_t at = 0; at < count; at++) {
        if (keys[at] != 0 && memchr(down, keys[at], sizeof(down)) == NULL) {
            pressed(keys[at], modifiers);
            newest = keys[at];
        }
    }
    memset(down, 0, sizeof(down));
    memcpy(down, keys, count);

    portENTER_CRITICAL(&lock);
    uint8_t held_down = repeating;
    portEXIT_CRITICAL(&lock);
    if (newest != 0) {
        repeat_from(repeats(newest, modifiers) ? newest : 0, modifiers);
    } else if (held_down != 0 && memchr(keys, held_down, count) == NULL) {
        repeat_from(0, 0);          /* let go of */
    } else if (held_down != 0 && !repeats(held_down, modifiers)) {
        repeat_from(0, 0);          /* Ctrl or the like went down with it */
    } else {
        portENTER_CRITICAL(&lock);
        repeat_modifiers = modifiers;   /* Shift, say, let go of or pressed */
        portEXIT_CRITICAL(&lock);
    }
}

/* --- Bluetooth's events ---------------------------------------------------------- */

static void hid_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    (void)base;
    esp_hidh_event_data_t *param = data;
    switch ((esp_hidh_event_t)id) {
    case ESP_HIDH_OPEN_EVENT:
        if (param->open.status == ESP_OK) {
            memset(down, 0, sizeof(down));
            repeat_from(0, 0);
            xEventGroupSetBits(happened, OPENED);
        }
        break;
    case ESP_HIDH_INPUT_EVENT:
        if (param->input.usage == ESP_HID_USAGE_KEYBOARD) {
            report(param->input.data, param->input.length);
        }
        break;
    case ESP_HIDH_CLOSE_EVENT:
        ESP_LOGI(TAG, "disconnected (reason %d)", param->close.reason);
        repeat_from(0, 0);
        xEventGroupSetBits(happened, CLOSED);
        break;
    default:
        break;
    }
}

/* Whether the pairing worked, which esp_hid's host does not say, and the
 * connection's interval once it is agreed, for the log: a listener hears
 * them besides the connection's own handler. */
static int gap_watch(struct ble_gap_event *event, void *arg)
{
    (void)arg;
    if (event->type == BLE_GAP_EVENT_CONN_UPDATE && event->conn_update.status == 0) {
        struct ble_gap_conn_desc desc;
        if (ble_gap_conn_find(event->conn_update.conn_handle, &desc) == 0) {
            ESP_LOGI(TAG, "connection interval %u ms, latency %u", desc.conn_itvl * 5 / 4,
                     desc.conn_latency);
        }
    }
    if (event->type == BLE_GAP_EVENT_ENC_CHANGE) {
        ESP_LOGI(TAG, "encryption: status %d", event->enc_change.status);
        if (event->enc_change.status == 0) {
            xEventGroupSetBits(happened, ENCRYPTED);
        }
    }
    return 0;
}

/* What a scan heard, by address. An advertisement and the answer to a scan
 * come apart, and either may have the name. */
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
    bool hid = false;
    for (int index = 0; index < fields.num_uuids16; index++) {
        hid |= ble_uuid_u16(&fields.uuids16[index].u) == UUID_HID;
    }
    bool keyboard = fields.appearance_is_present
                        ? fields.appearance == APPEARANCE_KEYBOARD
                              || (hid && fields.appearance == APPEARANCE_HID)
                        : hid;
    seen_t *one = NULL;
    for (uint8_t index = 0; index < heard_count; index++) {
        if (ble_addr_cmp(&heard[index].addr, &disc->addr) == 0) {
            one = &heard[index];
        }
    }
    if (one == NULL) {
        if (!keyboard || heard_count == NESP_KBD_FOUND_MAX) {
            return 0;
        }
        one = &heard[heard_count++];
        memset(one, 0, sizeof(*one));
        one->addr = disc->addr;
    }
    one->shown.rssi = disc->rssi;
    if (fields.name != NULL) {
        uint8_t length = fields.name_len < NESP_KBD_NAME_MAX ? fields.name_len
                                                              : NESP_KBD_NAME_MAX;
        memcpy(one->shown.name, fields.name, length);
        one->shown.name_len = length;
    }
    return 0;
}

static void host(void *arg)
{
    (void)arg;
    nimble_port_run();              /* until nimble_port_stop */
    nimble_port_freertos_deinit();
}

/* --- the keyboard's task ------------------------------------------------------------ */

static void keep_name(const nesp_keyboard_t *keyboard)
{
    nvs_handle_t settings;
    if (nvs_open(SETTINGS, NVS_READWRITE, &settings) == ESP_OK) {
        nvs_set_blob(settings, SETTING_KEYBOARD, keyboard->name, keyboard->name_len);
        nvs_commit(settings);
        nvs_close(settings);
    }
}

static void kept_name(nesp_keyboard_t *keyboard)
{
    nvs_handle_t settings;
    memset(keyboard, 0, sizeof(*keyboard));
    if (nvs_open(SETTINGS, NVS_READONLY, &settings) == ESP_OK) {
        size_t length = sizeof(keyboard->name);
        if (nvs_get_blob(settings, SETTING_KEYBOARD, keyboard->name, &length) == ESP_OK) {
            keyboard->name_len = (uint8_t)length;
        }
        nvs_close(settings);
    }
}

/* The bond NimBLE keeps, if it has one. */
static bool bonded(ble_addr_t *addr)
{
    int count = 0;
    return ble_store_util_bonded_peers(addr, &count, 1) == 0 && count != 0;
}

static void set_doing(uint8_t now)
{
    portENTER_CRITICAL(&lock);
    doing = now;
    if (now == NESP_KEYBOARD_SCANNED) {
        scanned_at = esp_timer_get_time();
    }
    portEXIT_CRITICAL(&lock);
}

static void set_connected(bool now)
{
    portENTER_CRITICAL(&lock);
    connected = now;
    portEXIT_CRITICAL(&lock);
}

static bool start(void)
{
    if (nimble_port_init() != ESP_OK) {
        ESP_LOGE(TAG, "Bluetooth did not start");
        return false;
    }
    esp_hidh_config_t config = {
        .callback = hid_event,
        .event_stack_size = HID_STACK,
        .callback_arg = NULL,
    };
    if (esp_hidh_init(&config) != ESP_OK) {
        nimble_port_deinit();
        return false;
    }
    /* After esp_hidh_init, which sets a keyboard's way of pairing. */
    ble_hs_cfg.sm_io_cap = BLE_HS_IO_NO_INPUT_OUTPUT;
    ble_hs_cfg.sm_bonding = 1;
    ble_hs_cfg.sm_mitm = 0;
    ble_hs_cfg.sm_our_key_dist = BLE_SM_PAIR_KEY_DIST_ENC | BLE_SM_PAIR_KEY_DIST_ID;
    ble_hs_cfg.sm_their_key_dist = BLE_SM_PAIR_KEY_DIST_ENC | BLE_SM_PAIR_KEY_DIST_ID;
    ble_hs_cfg.store_status_cb = ble_store_util_status_rr;
    ble_store_config_init();
    nimble_port_freertos_init(host);
    for (int waited = 0; !ble_hs_synced() && waited < SYNC_MS; waited += 10) {
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    ble_gap_event_listener_register(&listener, gap_watch, NULL);
    ble_addr_t addr;
    bool have = bonded(&addr);
    portENTER_CRITICAL(&lock);
    running = true;
    paired = have;
    held_count = 0;                 /* typed while nothing listened */
    doing = 0;
    portEXIT_CRITICAL(&lock);
    caps = false;
    ESP_LOGI(TAG, "Bluetooth on; %s", have ? "a keyboard is paired" : "no keyboard is paired");
    return true;
}

/* Let go of the keyboard connected, if one is. */
static void disconnect(void)
{
    if (device == NULL) {
        return;
    }
    if ((xEventGroupGetBits(happened) & CLOSED) == 0) {
        esp_hidh_dev_close(device);
        xEventGroupWaitBits(happened, CLOSED, pdFALSE, pdFALSE, pdMS_TO_TICKS(CLOSE_MS));
    }
    device = NULL;
    set_connected(false);
}

static void stop(void)
{
    disconnect();
    repeat_from(0, 0);
    ble_gap_event_listener_unregister(&listener);
    esp_hidh_deinit();
    nimble_port_stop();
    nimble_port_deinit();
    portENTER_CRITICAL(&lock);
    running = false;
    doing = 0;
    portEXIT_CRITICAL(&lock);
    ESP_LOGI(TAG, "Bluetooth off");
}

/* Connect to a keyboard and read its services. Waits for it, which
 * keyboard_poll may call off. */
static esp_hidh_dev_t *open(ble_addr_t addr)
{
    xEventGroupClearBits(happened, OPENED | CLOSED | ENCRYPTED);
    portENTER_CRITICAL(&lock);
    cancelled = false;
    opening = true;
    portEXIT_CRITICAL(&lock);
    esp_hidh_dev_t *opened = esp_hidh_dev_open(addr.val, ESP_HID_TRANSPORT_BLE, addr.type);
    portENTER_CRITICAL(&lock);
    opening = false;
    portEXIT_CRITICAL(&lock);
    return opened;
}

static void scan(void)
{
    uint8_t own;
    heard_count = 0;
    xEventGroupClearBits(happened, SCANNED);
    struct ble_gap_disc_params params = {.filter_duplicates = 1};   /* active: names too */
    if (ble_hs_id_infer_auto(0, &own) == 0
        && ble_gap_disc(own, SCAN_MS, &params, scan_event, NULL) == 0) {
        xEventGroupWaitBits(happened, SCANNED, pdTRUE, pdFALSE, pdMS_TO_TICKS(SCAN_MS * 2));
    }
    /* Strongest first. */
    for (uint8_t at = 1; at < heard_count; at++) {
        for (uint8_t back = at; back > 0 && heard[back].shown.rssi > heard[back - 1].shown.rssi;
             back--) {
            seen_t swap = heard[back];
            heard[back] = heard[back - 1];
            heard[back - 1] = swap;
        }
    }
    portENTER_CRITICAL(&lock);
    memcpy(found, heard, sizeof(found));
    found_count = heard_count;
    portEXIT_CRITICAL(&lock);
    set_doing(NESP_KEYBOARD_SCANNED);
    ESP_LOGI(TAG, "a scan found %u keyboards", heard_count);
}

static void forget(void)
{
    disconnect();
    ble_store_clear();
    nesp_keyboard_t none;
    memset(&none, 0, sizeof(none));
    keep_name(&none);
    portENTER_CRITICAL(&lock);
    paired = false;
    paired_one = none;
    portEXIT_CRITICAL(&lock);
}

static void pair(int index)
{
    seen_t one;
    portENTER_CRITICAL(&lock);
    bool there = index < found_count;
    if (there) {
        one = found[index];
    }
    portEXIT_CRITICAL(&lock);
    if (!there) {
        set_doing(NESP_KEYBOARD_FAILED);
        return;
    }
    forget();
    ESP_LOGI(TAG, "pairing with %.*s", one.shown.name_len, one.shown.name);
    esp_hidh_dev_t *opened = open(one.addr);
    if (opened == NULL || (xEventGroupGetBits(happened) & ENCRYPTED) == 0) {
        ESP_LOGW(TAG, "the pairing failed");
        device = opened;
        disconnect();
        ble_store_clear();
        set_doing(NESP_KEYBOARD_FAILED);
        return;
    }
    /* esp_hid's host turned the reports on before the pairing had made the
     * link encrypted, and the keyboard took no notice: it would type nothing
     * until it connected again. So it is let go of, and run() connects to it
     * again as the keyboard paired, which is encrypted at once. */
    device = opened;
    disconnect();
    one.shown.rssi = 0;
    keep_name(&one.shown);
    portENTER_CRITICAL(&lock);
    paired = true;
    paired_one = one.shown;
    doing = 0;
    portEXIT_CRITICAL(&lock);
    ESP_LOGI(TAG, "paired; connecting to it again");
}

/* True while Bluetooth is to stay on: a ROM has KBD in use, or let go of
 * it less than OFF_MS ago, and a keyboard is paired or being looked for.
 * Under the lock. */
static bool wanted(int64_t now)
{
    return (want_on || now - let_go_at < (int64_t)OFF_MS * 1000) && (paired || looking);
}

static void run(void *arg)
{
    (void)arg;
    for (;;) {
        ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(WAKE_MS));
        int64_t now = esp_timer_get_time();
        portENTER_CRITICAL(&lock);
        bool on = wanted(now);
        bool scanning = scan_asked;
        int pairing = pair_asked;
        bool forgetting = forget_asked;
        scan_asked = false;
        pair_asked = -1;
        forget_asked = false;
        if (doing == NESP_KEYBOARD_SCANNED && now - scanned_at > (int64_t)SCANNED_MS * 1000) {
            doing = 0;
        }
        uint8_t now_doing = doing;
        bool was_running = running;
        portEXIT_CRITICAL(&lock);

        if (!was_running) {
            if (on && !start()) {
                vTaskDelay(pdMS_TO_TICKS(1000));
            }
            continue;
        }
        if (forgetting) {
            forget();               /* first: with none paired, Bluetooth may now go */
        }
        if (!on) {
            stop();
            continue;
        }
        if (device != NULL && (xEventGroupGetBits(happened) & CLOSED) != 0) {
            device = NULL;          /* it went: esp_hid's host has let go of it */
            set_connected(false);
        }
        if (scanning) {
            scan();
            continue;
        }
        if (pairing >= 0) {
            pair(pairing);
            continue;
        }
        ble_addr_t addr;
        if (device == NULL && now_doing != NESP_KEYBOARD_FAILED && !forgetting && bonded(&addr)) {
            /* Until a key wakes it, or keyboard_poll calls the wait off. */
            esp_hidh_dev_t *opened = open(addr);
            if (opened != NULL) {
                device = opened;
                set_connected(true);
                ESP_LOGI(TAG, "the paired keyboard is connected");
            }
        }
    }
}

/* --- what the rest of the firmware calls ------------------------------------------- */

void keyboard_start(void)
{
    happened = xEventGroupCreate();
    esp_timer_create_args_t repeat_timer = {.callback = repeat, .name = "key repeat"};
    ESP_ERROR_CHECK(esp_timer_create(&repeat_timer, &repeater));
    nesp_keyboard_t kept;
    kept_name(&kept);
    portENTER_CRITICAL(&lock);
    paired_one = kept;
    paired = kept.name_len != 0;
    portEXIT_CRITICAL(&lock);
    xTaskCreate(run, "keyboard", TASK_STACK, NULL, TASK_PRIORITY, &task);
}

void keyboard_poll(void)
{
    int64_t now = esp_timer_get_time();
    portENTER_CRITICAL(&lock);
    bool asked = !wanted(now) || scan_asked || pair_asked >= 0 || forget_asked;
    bool call_off = opening && asked && doing != NESP_KEYBOARD_PAIRING && !cancelled;
    if (call_off) {
        cancelled = true;
    }
    portEXIT_CRITICAL(&lock);
    if (call_off) {
        ble_gap_conn_cancel();      /* esp_hid's host then gives up on it */
    }
}

bool keyboard_built(void)
{
    return true;
}

static void wake(void)
{
    if (task != NULL) {
        xTaskNotifyGive(task);
    }
}

void keyboard_enable(void *ctx, bool on)
{
    (void)ctx;
    portENTER_CRITICAL(&lock);
    want_on = on;
    if (!on) {
        let_go_at = esp_timer_get_time();
        looking = false;            /* the ROM that looked has gone, or said hello again */
    }
    portEXIT_CRITICAL(&lock);
    wake();
}

uint8_t keyboard_state(void *ctx, nesp_keyboard_t *out, uint8_t *count)
{
    (void)ctx;
    uint8_t state;
    portENTER_CRITICAL(&lock);
    if (paired) {
        *out = paired_one;
    } else {
        memset(out, 0, sizeof(*out));
    }
    *count = doing == NESP_KEYBOARD_SCANNED ? found_count : 0;
    if (!running) {
        state = paired ? NESP_KEYBOARD_OFF : NESP_KEYBOARD_UNPAIRED;
    } else if (doing != 0) {
        state = doing;
    } else if (connected) {
        state = NESP_KEYBOARD_CONNECTED;
    } else if (paired) {
        state = NESP_KEYBOARD_WAITING;
    } else {
        state = NESP_KEYBOARD_UNPAIRED;
    }
    portEXIT_CRITICAL(&lock);
    return state;
}

bool keyboard_scan(void *ctx)
{
    (void)ctx;
    portENTER_CRITICAL(&lock);
    looking = true;                 /* with Bluetooth off, it is turned on for this */
    bool can = running && doing != NESP_KEYBOARD_PAIRING;
    if (can && doing != NESP_KEYBOARD_SCANNING) {
        scan_asked = true;
        doing = NESP_KEYBOARD_SCANNING;
    }
    portEXIT_CRITICAL(&lock);
    wake();
    return can;
}

bool keyboard_found(void *ctx, uint8_t index, nesp_keyboard_t *out)
{
    (void)ctx;
    portENTER_CRITICAL(&lock);
    bool there = doing == NESP_KEYBOARD_SCANNED && index < found_count;
    if (there) {
        *out = found[index].shown;
    }
    portEXIT_CRITICAL(&lock);
    return there;
}

bool keyboard_pair(void *ctx, uint8_t index)
{
    (void)ctx;
    portENTER_CRITICAL(&lock);
    bool there = running && doing == NESP_KEYBOARD_SCANNED && index < found_count;
    if (there) {
        pair_asked = index;
        doing = NESP_KEYBOARD_PAIRING;
    }
    portEXIT_CRITICAL(&lock);
    wake();
    return there;
}

void keyboard_forget(void *ctx)
{
    (void)ctx;
    portENTER_CRITICAL(&lock);
    if (running) {
        forget_asked = true;
        paired = false;             /* as STATE says it from now on */
        if (doing == NESP_KEYBOARD_FAILED || doing == NESP_KEYBOARD_SCANNED) {
            doing = 0;
        }
    }
    portEXIT_CRITICAL(&lock);
    wake();
}

size_t keyboard_read(void *ctx, uint8_t *out, size_t max)
{
    (void)ctx;
    size_t count = 0;
    portENTER_CRITICAL(&lock);
    while (count < max && held_count != 0) {
        out[count++] = held[held_first];
        held_first = (uint8_t)((held_first + 1) % HELD);
        held_count--;
    }
    portEXIT_CRITICAL(&lock);
    return count;
}

const char *keyboard_said(void)
{
    static const char *const SAID[] = {"none", "off", "unpaired", "waiting", "connected",
                                       "scanning", "scanned", "pairing", "failed"};
    nesp_keyboard_t ignored;
    uint8_t count;
    uint8_t state = keyboard_state(NULL, &ignored, &count);
    return state < sizeof(SAID) / sizeof(SAID[0]) ? SAID[state] : "?";
}

#else

void keyboard_start(void)
{
}

void keyboard_poll(void)
{
}

bool keyboard_built(void)
{
    return false;
}

void keyboard_enable(void *ctx, bool on)
{
    (void)ctx;
    (void)on;
}

uint8_t keyboard_state(void *ctx, nesp_keyboard_t *paired, uint8_t *found)
{
    (void)ctx;
    memset(paired, 0, sizeof(*paired));
    *found = 0;
    return NESP_KEYBOARD_NONE;
}

bool keyboard_scan(void *ctx)
{
    (void)ctx;
    return false;
}

bool keyboard_found(void *ctx, uint8_t index, nesp_keyboard_t *out)
{
    (void)ctx;
    (void)index;
    (void)out;
    return false;
}

bool keyboard_pair(void *ctx, uint8_t index)
{
    (void)ctx;
    (void)index;
    return false;
}

void keyboard_forget(void *ctx)
{
    (void)ctx;
}

size_t keyboard_read(void *ctx, uint8_t *out, size_t max)
{
    (void)ctx;
    (void)out;
    (void)max;
    return 0;
}

const char *keyboard_said(void)
{
    return "none";
}

#endif
