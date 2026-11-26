/* The last DUMP kept over power-off, and said to the log again.
 *
 * A console whose digest differed sends its RAM (PEER's DUMP), and its
 * lines go to the log at once (peer.c). Most players have no log open
 * then: so the whole of it is also handed to the hal to keep (in the flash,
 * once a dump, not a piece), and said again from the start, a second after
 * the nesp32 starts or a ROM says hello (the cartridge's menu, a game), and
 * every minute after for some minutes. A page that has connected to the
 * serial port hears it when the console is next switched on or reset, or
 * when the page resets the nesp32. The lines are the live dump's
 * (peer.c), but for the heading (docs/PROTOCOL.md, "A kept dump"):
 *
 *     dump of the console's RAM, kept 3, as it stood at tick 767: 2048 bytes; app TSBO version 2; firmware 0.9.2
 *     dump 0000: <64 bytes in hex>
 *     ... 32 in all ...
 *     dump 07c0: <64 bytes in hex>
 *     dump end
 */
#include <stdio.h>
#include <string.h>

#include "nesp_services.h"
#include "nesp_version.h"

#define KEPT_LINES (NESP_PEER_DUMP_BYTES / NESP_PEER_DUMP_LINE)
#define KEPT_TEXT 256
_Static_assert(KEPT_LINES + 2 < 255, "a telling's lines are counted in a byte");
_Static_assert(sizeof(NESP_FIRMWARE_TEXT) <= sizeof(((nesp_dump_head_t *)0)->firmware),
               "the firmware's version fits the kept dump's head");

void nesp_kept_init(nesp_kept_t *kept, const nesp_hal_t *hal, const nesp_sys_t *sys)
{
    memset(kept, 0, sizeof(*kept));
    kept->hal = hal;
    kept->sys = sys;
}

void nesp_kept_dump(nesp_kept_t *kept, uint32_t tick, const char *app, uint8_t app_version,
                    const uint8_t *ram)
{
    uint32_t count = kept->have ? kept->head.count : 0;
    memset(&kept->head, 0, sizeof(kept->head));
    kept->head.count = count + 1;
    kept->head.tick = tick;
    memcpy(kept->head.app, app, sizeof(kept->head.app));
    kept->head.app_version = app_version;
    snprintf(kept->head.firmware, sizeof(kept->head.firmware), "%s", NESP_FIRMWARE_TEXT);
    memcpy(kept->ram, ram, sizeof(kept->ram));
    kept->have = true;
    kept->loaded = true;
    if (kept->hal->dump_keep != NULL) {
        kept->hal->dump_keep(kept->hal->ctx, &kept->head, kept->ram);
    }
    /* Said again from a minute on, as at the start: the log had it at once. */
    if (kept->line == 0) {
        kept->rounds = NESP_KEPT_TELLINGS;
        kept->at = kept->now + NESP_KEPT_AGAIN_MS;
    }
}

static void say_begin(const nesp_kept_t *kept, char *text, size_t size)
{
    char app[NESP_APP_ID + 1];
    for (size_t index = 0; index < NESP_APP_ID; index++) {
        char letter = kept->head.app[index];
        app[index] = letter > ' ' && letter < 0x7F ? letter : '-';
    }
    app[NESP_APP_ID] = 0;
    char firmware[sizeof(kept->head.firmware)];
    memcpy(firmware, kept->head.firmware, sizeof(firmware));
    firmware[sizeof(firmware) - 1] = 0;
    for (char *letter = firmware; *letter != 0; letter++) {
        if (*letter <= ' ' || *letter >= 0x7F) {
            *letter = '?';
        }
    }
    size_t length = (size_t)snprintf(text, size, "dump of the console's RAM, kept %lu",
                                     (unsigned long)kept->head.count);
    if (kept->head.tick != 0 && length < size) {
        length += (size_t)snprintf(text + length, size - length, ", as it stood at tick %lu",
                                   (unsigned long)kept->head.tick);
    }
    if (length < size) {
        snprintf(text + length, size - length, ": %u bytes; app %s version %u; firmware %s",
                 (unsigned)NESP_PEER_DUMP_BYTES, app, (unsigned)kept->head.app_version,
                 firmware[0] != 0 ? firmware : "-");
    }
}

bool nesp_kept_tick(nesp_kept_t *kept, uint32_t now)
{
    kept->now = now;
    if (!kept->loaded) {
        kept->loaded = true;
        kept->have = kept->hal->dump_last != NULL
                     && kept->hal->dump_last(kept->hal->ctx, &kept->head, kept->ram);
        kept->rounds = kept->have ? NESP_KEPT_TELLINGS : 0;
        kept->at = now + NESP_KEPT_FIRST_MS;
        kept->hellos = kept->sys != NULL ? kept->sys->hellos : 0;
    }
    if (kept->sys != NULL && kept->sys->hellos != kept->hellos) {
        /* A ROM said hello: from its start again, but no sooner than a
         * new dump's own lines leave room for. */
        kept->hellos = kept->sys->hellos;
        kept->rounds = NESP_KEPT_TELLINGS;
        if (kept->line == 0 && (int32_t)(kept->at - (now + NESP_KEPT_FIRST_MS)) < 0) {
            kept->at = now + NESP_KEPT_FIRST_MS;
        }
    }
    if (!kept->have || kept->hal->watch == NULL || (int32_t)(now - kept->at) < 0) {
        return false;
    }
    if (kept->line == 0) {
        if (kept->rounds == 0) {
            return false;
        }
        kept->rounds--;
    }
    char text[KEPT_TEXT];
    if (kept->line == 0) {
        say_begin(kept, text, sizeof(text));
    } else if (kept->line <= KEPT_LINES) {
        size_t from = (size_t)(kept->line - 1) * NESP_PEER_DUMP_LINE;
        size_t length = (size_t)snprintf(text, sizeof(text), "dump %04x:", (unsigned)from);
        for (size_t index = 0; index < NESP_PEER_DUMP_LINE && length + 3 < sizeof(text); index++) {
            length += (size_t)snprintf(text + length, sizeof(text) - length, "%s%02x",
                                       index == 0 ? " " : "", kept->ram[from + index]);
        }
    } else {
        snprintf(text, sizeof(text), "dump end");
    }
    kept->hal->watch(kept->hal->ctx, text);
    if (kept->line <= KEPT_LINES) {
        kept->line++;
        kept->at = now + NESP_PEER_DUMP_EVERY_MS;
    } else {
        kept->line = 0;
        kept->at = now + NESP_KEPT_AGAIN_MS;
    }
    return false;
}
