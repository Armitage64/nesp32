/* KBD: a Bluetooth keyboard, for a ROM's text (docs/PROTOCOL.md).
 *
 * The keyboard is the nesp32's hardware's (nesp_hal_t's kbd_*): this only
 * says how it stands, hands on what was typed, and passes on what the
 * console asks. Bluetooth is on while a ROM has KBD in use, and off once
 * none has: it shares the radio with Wi-Fi, and a game should not have it
 * there.
 *
 * KEYS takes what it hands on off the nesp32. A KEYS that is asked again,
 * its reply lost, is answered by the link with the reply it had (the same
 * request again), so nothing typed is lost or comes twice.
 *
 * KEYS_ALL hands on everything the keyboard keeps. KEYS leaves out the keys
 * only Family BASIC takes (F1 to F8, F12, Home, Insert, Delete), and a key
 * typed with Ctrl or Alt (WITH_CTRL or WITH_ALT, and the key after it), so
 * that the ROMs that ask for KEYS have what they had before there were
 * any.
 */
#include <string.h>

#include "nesp_services.h"

static bool has_keyboard(const nesp_kbd_t *kbd)
{
    return kbd->hal->kbd_state != NULL;
}

static void state(nesp_kbd_t *kbd, nesp_reply_t *reply)
{
    nesp_keyboard_t paired;
    uint8_t found = 0;
    memset(&paired, 0, sizeof(paired));
    uint8_t *out = reply->data;
    out[0] = has_keyboard(kbd) ? kbd->hal->kbd_state(kbd->hal->ctx, &paired, &found)
                               : NESP_KEYBOARD_NONE;
    out[1] = found;
    uint8_t name_len = paired.name_len;
    if (name_len > reply->max - 3) {
        name_len = (uint8_t)(reply->max - 3);
    }
    out[2] = name_len;
    memcpy(out + 3, paired.name, name_len);
    reply->len = (uint8_t)(3 + name_len);
}

/* Whether KEYS leaves this out: a key KEYS_ALL alone hands on. */
static bool all_only(uint8_t key)
{
    switch (key) {
    case NESP_KEY_F1:
    case NESP_KEY_F2:
    case NESP_KEY_F3:
    case NESP_KEY_F4:
    case NESP_KEY_F5:
    case NESP_KEY_F6:
    case NESP_KEY_F7:
    case NESP_KEY_F8:
    case NESP_KEY_F12:
    case NESP_KEY_HOME:
    case NESP_KEY_SHIFT_HOME:
    case NESP_KEY_INSERT:
    case NESP_KEY_DELETE:
        return true;
    default:
        return false;
    }
}

static void keys(nesp_kbd_t *kbd, nesp_reply_t *reply, bool all)
{
    size_t max = NESP_KBD_KEYS_MAX;
    if (max > (size_t)reply->max - 1) {
        max = (size_t)reply->max - 1;
    }
    uint8_t *out = reply->data + 1;
    size_t count = has_keyboard(kbd) ? kbd->hal->kbd_read(kbd->hal->ctx, out, max) : 0;
    if (!all) {
        size_t kept = 0;
        for (size_t at = 0; at < count; at++) {
            uint8_t key = out[at];
            if (key == NESP_KEY_WITH_CTRL || key == NESP_KEY_WITH_ALT) {
                kbd->chord = true;
            } else if (kbd->chord) {
                kbd->chord = false;     /* the key typed with Ctrl or Alt */
            } else if (!all_only(key)) {
                out[kept++] = key;
            }
        }
        count = kept;
    } else {
        kbd->chord = false;
    }
    reply->data[0] = (uint8_t)count;
    reply->len = (uint8_t)(1 + count);
}

static void found(nesp_kbd_t *kbd, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len != 1) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    nesp_keyboard_t keyboard;
    memset(&keyboard, 0, sizeof(keyboard));
    if (!has_keyboard(kbd)
        || !kbd->hal->kbd_found(kbd->hal->ctx, request->data[0], &keyboard)) {
        reply->status = NESP_ST_NOT_FOUND;
        return;
    }
    uint8_t *out = reply->data;
    out[0] = request->data[0];
    out[1] = (uint8_t)keyboard.rssi;
    uint8_t name_len = keyboard.name_len;
    if (name_len > reply->max - 3) {
        name_len = (uint8_t)(reply->max - 3);
    }
    out[2] = name_len;
    memcpy(out + 3, keyboard.name, name_len);
    reply->len = (uint8_t)(3 + name_len);
}

static void handle(void *ctx, const nesp_request_t *request, nesp_reply_t *reply)
{
    nesp_kbd_t *kbd = ctx;
    switch (request->op) {
    case NESP_KBD_STATE:
        state(kbd, reply);
        break;
    case NESP_KBD_KEYS:
        keys(kbd, reply, false);
        break;
    case NESP_KBD_KEYS_ALL:
        keys(kbd, reply, true);
        break;
    case NESP_KBD_SCAN:
        if (!has_keyboard(kbd)) {
            reply->status = NESP_ST_FAILED;
        } else if (!kbd->hal->kbd_scan(kbd->hal->ctx)) {
            reply->status = NESP_ST_BUSY;
        }
        break;
    case NESP_KBD_FOUND:
        found(kbd, request, reply);
        break;
    case NESP_KBD_PAIR:
        if (request->len != 1) {
            reply->status = NESP_ST_BAD_ARG;
        } else if (!has_keyboard(kbd) || !kbd->hal->kbd_pair(kbd->hal->ctx, request->data[0])) {
            reply->status = NESP_ST_FAILED;
        }
        break;
    case NESP_KBD_FORGET:
        if (!has_keyboard(kbd)) {
            reply->status = NESP_ST_FAILED;
        } else {
            kbd->hal->kbd_forget(kbd->hal->ctx);
        }
        break;
    default:
        reply->status = NESP_ST_NO_OP;
        break;
    }
}

static void activate(void *ctx)
{
    nesp_kbd_t *kbd = ctx;
    kbd->chord = false;
    if (has_keyboard(kbd)) {
        kbd->hal->kbd_enable(kbd->hal->ctx, true);
    }
}

static void deactivate(void *ctx)
{
    nesp_kbd_t *kbd = ctx;
    if (has_keyboard(kbd)) {
        kbd->hal->kbd_enable(kbd->hal->ctx, false);
    }
}

void nesp_kbd_service(nesp_service_t *service, nesp_kbd_t *kbd, const nesp_hal_t *hal)
{
    kbd->hal = hal;
    kbd->chord = false;
    memset(service, 0, sizeof(*service));
    service->id = NESP_SVC_KBD;
    service->name = "KBD";
    service->activate = activate;
    service->deactivate = deactivate;
    service->handle = handle;
    service->ctx = kbd;
}
