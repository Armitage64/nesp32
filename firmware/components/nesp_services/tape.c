/* TAPE: Family BASIC's data recorder, as files on the nesp32
 * (docs/PROTOCOL.md).
 *
 * The game writes to tape in pairs of blocks: a header of 128 bytes, with
 * the file's type, its name and the length of what follows, and then the
 * data block, a program or a screen. Here a pair comes over the link in
 * pieces (PUT) and is kept (SAVE) as a file named for what its header
 * says, and a pair is found again (FIND) by the type and the name the
 * console asks for, and read back in pieces (GET). A file is its pairs one
 * after the other, as they were sent: a program is one, a BG GRAPHIC
 * screen four. The files are the nesp32's own (nesp_hal_t's file_*), and a
 * computer sees them on its drive: NAME.fbp for a program, NAME.fbg for a
 * screen.
 *
 * SAVE and FIND are each both "do this" and "how is it going", by an id,
 * as WIKI's SEARCH is: the console sends the same request again until it
 * has ended, and the nesp32 starts on one only when its id is new. The
 * writing and the reading are done in tick, once the reply has gone.
 */
#include <stdio.h>
#include <string.h>
#include <strings.h>

#include "nesp_services.h"

#define TYPE_PROGRAM 2
#define TYPE_SCREEN 3

static bool has_files(const nesp_tape_t *tape)
{
    const nesp_hal_t *hal = tape->hal;
    return hal->file_read != NULL && hal->file_write != NULL && hal->file_name != NULL;
}

/* A file's ending, by its type. out holds 6 bytes. */
static void ending(uint8_t type, char *out)
{
    if (type == TYPE_PROGRAM) {
        snprintf(out, 6, ".fbp");
    } else if (type == TYPE_SCREEN) {
        snprintf(out, 6, ".fbg");
    } else {
        snprintf(out, 6, ".t%03u", type);
    }
}

/* A name as the game has it, as a file's. The game ends a name shorter
 * than 16 characters with a 0, and has spaces after that; the name is what
 * comes before the 0, less any spaces at its end, and with anything a
 * filing system may not take, or would take for another character (small
 * letters, which FAT takes for capitals), as % and its two hex digits. A
 * name of nothing, or of spaces, is "%20". */
static void file_name(uint8_t type, const uint8_t *name, char *out)
{
    static const char kept[] = "!#$&'()+,-;=@[]^_`{}~";
    size_t len = 0;
    while (len < NESP_TAPE_NAME && name[len] != 0) {
        len++;
    }
    while (len > 0 && name[len - 1] == ' ') {
        len--;
    }
    size_t at = 0;
    for (size_t index = 0; index < len; index++) {
        uint8_t c = name[index];
        if ((c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || (c == ' ' && index != 0)
            || strchr(kept, c) != NULL) {
            out[at++] = (char)c;
        } else {
            at += (size_t)snprintf(out + at, 4, "%%%02X", c);
        }
    }
    if (len == 0) {
        at += (size_t)snprintf(out, 4, "%%20");
    }
    ending(type, out + at);
}

static bool ends_with(const char *name, const char *suffix)
{
    size_t len = strlen(name);
    size_t suffix_len = strlen(suffix);
    return len > suffix_len && strcasecmp(name + len - suffix_len, suffix) == 0;
}

/* FIND with no name: the first file of the type, in the order the nesp32
 * lists them. */
static bool first_of_type(nesp_tape_t *tape, uint8_t type, char *out)
{
    char suffix[6];
    ending(type, suffix);
    for (uint16_t index = 0;
         tape->hal->file_name(tape->hal->ctx, index, out, NESP_TAPE_FILE_NAME); index++) {
        if (out[0] != '.' && ends_with(out, suffix)) {
            return true;
        }
    }
    return false;
}

static uint16_t data_length(const uint8_t *header)
{
    return (uint16_t)(header[NESP_TAPE_LENGTH_AT] | header[NESP_TAPE_LENGTH_AT + 1] << 8);
}

static void save(nesp_tape_t *tape)
{
    char name[NESP_TAPE_FILE_NAME];
    file_name(tape->pair[NESP_TAPE_TYPE_AT], tape->pair + NESP_TAPE_NAME_AT, name);
    bool written = tape->hal->file_write(tape->hal->ctx, name, tape->pair, tape->length,
                                         tape->pair_index != 0);
    tape->state = written ? NESP_DECK_DONE : NESP_DECK_FAILED;
}

static void find(nesp_tape_t *tape)
{
    char name[NESP_TAPE_FILE_NAME];
    if (tape->named) {
        file_name(tape->type, tape->name, name);
    } else if (!first_of_type(tape, tape->type, name)) {
        tape->state = NESP_DECK_NOT_FOUND;
        return;
    }
    const nesp_hal_t *hal = tape->hal;
    uint32_t at = 0;
    for (uint8_t index = 0;; index++) {
        uint8_t *header = tape->pair;
        if (hal->file_read(hal->ctx, name, at, header, NESP_TAPE_HEADER) != NESP_TAPE_HEADER) {
            tape->state = NESP_DECK_NOT_FOUND;
            return;
        }
        uint16_t data = data_length(header);
        if (data > NESP_TAPE_DATA_MAX) {
            tape->state = NESP_DECK_FAILED;
            return;
        }
        if (index == tape->pair_index) {
            if (hal->file_read(hal->ctx, name, at + NESP_TAPE_HEADER,
                               tape->pair + NESP_TAPE_HEADER, data) != data) {
                tape->state = NESP_DECK_FAILED;
                return;
            }
            tape->length = (uint16_t)(NESP_TAPE_HEADER + data);
            break;
        }
        at += NESP_TAPE_HEADER + (uint32_t)data;
    }
    /* The file's name is the one that counts: a file renamed on a computer
     * is found by its new one, and the game, which checks the header,
     * takes it. */
    tape->pair[NESP_TAPE_TYPE_AT] = tape->type;
    if (tape->named) {
        memcpy(tape->pair + NESP_TAPE_NAME_AT, tape->name, NESP_TAPE_NAME);
    }
    tape->state = NESP_DECK_DONE;
}

static void report(const nesp_tape_t *tape, nesp_reply_t *reply)
{
    reply->data[0] = tape->state;
    reply->data[1] = tape->id;
    reply->len = 2;
}

/* A new job, or the one asked for already: true if it is new. */
static bool begin(nesp_tape_t *tape, uint8_t op, uint8_t id)
{
    if (tape->asked && tape->op == op && tape->id == id) {
        return false;
    }
    tape->asked = true;
    tape->op = op;
    tape->id = id;
    tape->state = NESP_DECK_BUSY;
    tape->due = true;
    return true;
}

static bool busy(const nesp_tape_t *tape)
{
    return tape->asked && tape->state == NESP_DECK_BUSY;
}

static void put(nesp_tape_t *tape, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len < 2) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    uint16_t at = (uint16_t)(request->data[0] | request->data[1] << 8);
    size_t len = request->len - 2u;
    if (at + len > sizeof(tape->pair)) {
        reply->status = NESP_ST_BAD_ARG;
    } else if (busy(tape)) {
        reply->status = NESP_ST_BUSY;   /* the last pair is being kept */
    } else {
        memcpy(tape->pair + at, request->data + 2, len);
        if (tape->op == NESP_TAPE_FIND) {
            tape->asked = false;        /* what was found is gone */
        }
    }
}

static void save_asked(nesp_tape_t *tape, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len != 4) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    uint8_t id = request->data[0];
    if (!busy(tape) && begin(tape, NESP_TAPE_SAVE, id)) {
        uint16_t data = (uint16_t)(request->data[2] | request->data[3] << 8);
        tape->pair_index = request->data[1];
        if (!has_files(tape) || data > NESP_TAPE_DATA_MAX || data != data_length(tape->pair)
            || tape->pair_index >= NESP_TAPE_PAIRS_MAX) {
            tape->state = NESP_DECK_FAILED;
            tape->due = false;
        } else {
            tape->length = (uint16_t)(NESP_TAPE_HEADER + data);
        }
    } else if (tape->op != NESP_TAPE_SAVE || tape->id != id) {
        reply->status = NESP_ST_BUSY;   /* another job is under way */
        return;
    }
    report(tape, reply);
}

static void find_asked(nesp_tape_t *tape, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len != 3 && request->len != 3 + NESP_TAPE_NAME) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    uint8_t id = request->data[0];
    if (!busy(tape) && begin(tape, NESP_TAPE_FIND, id)) {
        tape->type = request->data[1];
        tape->pair_index = request->data[2];
        tape->named = request->len != 3;
        if (tape->named) {
            memcpy(tape->name, request->data + 3, NESP_TAPE_NAME);
        }
        tape->length = 0;
        if (!has_files(tape)) {
            tape->state = NESP_DECK_FAILED;
            tape->due = false;
        }
    } else if (tape->op != NESP_TAPE_FIND || tape->id != id) {
        reply->status = NESP_ST_BUSY;
        return;
    }
    report(tape, reply);
}

static void get(nesp_tape_t *tape, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len != 3) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    if (!tape->asked || tape->op != NESP_TAPE_FIND || tape->state != NESP_DECK_DONE) {
        reply->status = NESP_ST_NOT_FOUND;
        return;
    }
    uint16_t at = (uint16_t)(request->data[0] | request->data[1] << 8);
    size_t count = request->data[2];
    if (count > reply->max) {
        count = reply->max;
    }
    if (at >= tape->length) {
        count = 0;
    } else if (count > tape->length - at) {
        count = tape->length - at;
    }
    memcpy(reply->data, tape->pair + at, count);
    reply->len = (uint8_t)count;
}

static void handle(void *ctx, const nesp_request_t *request, nesp_reply_t *reply)
{
    nesp_tape_t *tape = ctx;
    switch (request->op) {
    case NESP_TAPE_PUT:
        put(tape, request, reply);
        break;
    case NESP_TAPE_SAVE:
        save_asked(tape, request, reply);
        break;
    case NESP_TAPE_FIND:
        find_asked(tape, request, reply);
        break;
    case NESP_TAPE_GET:
        get(tape, request, reply);
        break;
    default:
        reply->status = NESP_ST_NO_OP;
        break;
    }
}

static bool tick(void *ctx, uint32_t now_ms)
{
    nesp_tape_t *tape = ctx;
    (void)now_ms;
    if (!tape->due) {
        return false;
    }
    tape->due = false;
    if (tape->op == NESP_TAPE_SAVE) {
        save(tape);
    } else {
        find(tape);
    }
    return false;
}

static void activate(void *ctx)
{
    nesp_tape_t *tape = ctx;
    tape->asked = false;
    tape->due = false;
    tape->state = NESP_DECK_IDLE;
}

void nesp_tape_service(nesp_service_t *service, nesp_tape_t *tape, const nesp_hal_t *hal)
{
    memset(tape, 0, sizeof(*tape));
    tape->hal = hal;
    memset(service, 0, sizeof(*service));
    service->id = NESP_SVC_TAPE;
    service->name = "TAPE";
    service->activate = activate;
    service->handle = handle;
    service->tick = tick;
    service->ctx = tape;
}
