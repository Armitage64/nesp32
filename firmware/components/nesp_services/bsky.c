/* BSKY: a Bluesky account's posts, a line at a time, and the favorites the
 * console chooses them from (docs/PROTOCOL.md). Bluesky's service.
 *
 * The console names an account by its handle, and the nesp32 asks
 * Bluesky's public API for its latest posts: no account and no password
 * are needed to read them. Each post is laid out as NESP_BSKY_ROWS lines of
 * NESP_BSKY_COLUMNS characters, the same number for every post, so that the
 * console asks for a line by the post's number and the line's, and draws a
 * post as a card, as ConnectedNES drew a tweet.
 *
 * FEED is both "this handle" and "how does it stand", as WIKI's SEARCH is.
 * The console gives each choice an id and may send the same request as
 * often as it likes: an id or a handle that is new starts a fetch, and the
 * same again only answers. Posts are offered as they are laid out, the
 * newest first, so the first can be read while the rest arrive.
 *
 * The favorites are handles, NESP_BSKY_FAVORITES at most, kept over
 * power-off where the board can (nesp_hal_t's favorites_keep), as RADAR
 * keeps its airport. A nesp32 that keeps none begins with `defaults`.
 *
 * The reply is a few dozen kilobytes of JSON, most of it what the console
 * has no use for: pictures, links, the posts that a post replies to or
 * quotes. It is read as it arrives, and never held. A small parser follows
 * where in it each value is, and only these are kept, of each item of
 * "feed":
 *
 *   post.author.handle, post.author.displayName
 *   post.record.text
 *   post.indexedAt
 *   post.replyCount, post.repostCount, post.likeCount
 *   reason.by.handle            who reposted it, if it is a repost
 *
 * A post's text, quoted in a reply or a quote, has the same keys deeper
 * down, which is why the parser goes by where a key is and not only by its
 * name.
 *
 * Two tasks meet here, as in wiki.c. The link's task runs handle(), which
 * only reads and sets what is held. The fetch's task runs body() and done()
 * as the reply arrives, and does all the work on it. What both touch is
 * the posts and their state, under the hal's lock for a few instructions at
 * a time; `generation` is which fetch the posts belong to.
 */
#include <stdio.h>
#include <string.h>

#include "nesp_services.h"

#define COLUMNS NESP_BSKY_COLUMNS
#define ROWS NESP_BSKY_ROWS
#define POST_SIZE (ROWS * COLUMNS)
#define NAME_ROW 0
#define HANDLE_ROW 1
#define REPOST_ROW 2
#define TEXT_ROW 3
#define TEXT_ROWS (ROWS - TEXT_ROW - 1)
#define WHEN_ROW (ROWS - 1)
#define AGENT "nesp32-bluesky/0.1 (Bluesky on a NES, from an M5Stack Stick; nesp32)"
#define FEED_URL "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed" \
                 "?filter=posts_no_replies&limit=%d&actor=%.*s"
/* How fetch.c says the site answered 400, which is what Bluesky says to a
 * handle it has no one by. */
#define NO_SUCH "THE SITE SAID 400"
#define HEADING 0x80
#define NO_CODE 0xFFFFFFFFu

/* The favorites a nesp32 begins with. */
static const char *const defaults[] = {
    "levimaaia.com",
    "andyreitano.com",
    "adriansdigitalbasement.com",
    "jeriellsworth.bsky.social",
};

/* What a string or a number in the reply is, by where it is. */
enum {
    FIELD_NONE,
    FIELD_HANDLE,
    FIELD_NAME,
    FIELD_TEXT,
    FIELD_WHEN,
    FIELD_REPOSTER,
    FIELD_REPLIES,
    FIELD_REPOSTS,
    FIELD_LIKES,
};

static const char *const months[] = {"Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};

static void lock(nesp_bsky_t *bsky)
{
    bsky->hal->lock(bsky->hal->ctx);
}

static void unlock(nesp_bsky_t *bsky)
{
    bsky->hal->unlock(bsky->hal->ctx);
}

/* --- handles --------------------------------------------------------------------- */

/* A handle as the console typed it, as Bluesky has it: no "@" before it,
 * small letters, and ".bsky.social" after a name with no dot in it, which
 * is where most are. Returns its length, or 0 if it cannot be one. */
static size_t normal_handle(const uint8_t *text, size_t len, char *out)
{
    static const char home[] = ".bsky.social";
    if (len > 0 && text[0] == '@') {
        text++;
        len--;
    }
    if (len == 0 || len > NESP_BSKY_HANDLE_MAX) {
        return 0;
    }
    bool dotted = false;
    for (size_t index = 0; index < len; index++) {
        char letter = (char)text[index];
        if (letter >= 'A' && letter <= 'Z') {
            letter = (char)(letter - 'A' + 'a');
        }
        bool fits = (letter >= 'a' && letter <= 'z') || (letter >= '0' && letter <= '9')
                    || letter == '-' || letter == '.';
        if (!fits) {
            return 0;
        }
        dotted |= letter == '.';
        out[index] = letter;
    }
    if (out[0] == '.' || out[len - 1] == '.') {
        return 0;
    }
    if (!dotted) {
        if (len + sizeof(home) - 1 > NESP_BSKY_HANDLE_MAX) {
            return 0;
        }
        memcpy(out + len, home, sizeof(home) - 1);
        len += sizeof(home) - 1;
    }
    return len;
}

static size_t favorite_len(const nesp_bsky_favorites_t *favorites, uint8_t number)
{
    size_t len = 0;
    while (len < NESP_BSKY_HANDLE_MAX && favorites->handles[number][len] != 0) {
        len++;
    }
    return len;
}

static void keep(nesp_bsky_t *bsky)
{
    if (bsky->hal->favorites_keep != NULL) {
        bsky->hal->favorites_keep(bsky->hal->ctx, &bsky->favorites);
    }
}

/* --- a post, as lines ------------------------------------------------------------ */

/* A line of the post being laid out: text, cut at the width, padded with
 * spaces, every character with `flags`. */
static void put_line(uint8_t *post, unsigned row, const char *text, size_t len, uint8_t flags)
{
    uint8_t *line = post + row * COLUMNS;
    for (size_t index = 0; index < COLUMNS; index++) {
        line[index] = index < len ? (uint8_t)((uint8_t)text[index] | flags) : ' ';
    }
}

/* Days from 1970-01-01 to a date (Howard Hinnant's days_from_civil). */
static int32_t days_from_civil(int32_t year, int32_t month, int32_t day)
{
    year -= month <= 2;
    int32_t era = (year >= 0 ? year : year - 399) / 400;
    int32_t of_era = year - era * 400;
    int32_t of_year = (153 * (month + (month > 2 ? -3 : 9)) + 2) / 5 + day - 1;
    int32_t of_cycle = of_era * 365 + of_era / 4 - of_era / 100 + of_year;
    return era * 146097 + of_cycle - 719468;
}

static bool digits(const char *text, size_t count, int32_t *out)
{
    int32_t value = 0;
    for (size_t index = 0; index < count; index++) {
        if (text[index] < '0' || text[index] > '9') {
            return false;
        }
        value = value * 10 + (text[index] - '0');
    }
    *out = value;
    return true;
}

/* When a post was posted, from "2026-10-18T13:18:21.731Z": seconds since
 * 1970, and the month and day. */
static bool parse_when(const char *text, size_t len, uint32_t *seconds, int32_t *month,
                       int32_t *day)
{
    int32_t year, hour, minute, second;
    if (len < 19 || text[4] != '-' || text[7] != '-' || text[10] != 'T'
        || !digits(text, 4, &year) || !digits(text + 5, 2, month) || !digits(text + 8, 2, day)
        || !digits(text + 11, 2, &hour) || !digits(text + 14, 2, &minute)
        || !digits(text + 17, 2, &second) || *month < 1 || *month > 12) {
        return false;
    }
    int32_t days = days_from_civil(year, *month, *day);
    if (days < 0) {
        return false;
    }
    *seconds = (uint32_t)days * 86400u + (uint32_t)(hour * 3600 + minute * 60 + second);
    return true;
}

/* How long ago it was posted, if the nesp32 knows the time, or its date:
 * "5m", "3h", "2d", "Oct 18". */
static size_t age(const nesp_bsky_t *bsky, char *out, size_t max)
{
    uint32_t then;
    int32_t month, day;
    if (!parse_when(bsky->when, bsky->when_len, &then, &month, &day)) {
        return 0;
    }
    int written;
    if (bsky->clock_known && bsky->clock >= then && bsky->clock - then < 7 * 86400u) {
        uint32_t ago = bsky->clock - then;
        if (ago < 60) {
            written = snprintf(out, max, "now");
        } else if (ago < 3600) {
            written = snprintf(out, max, "%um", (unsigned)(ago / 60));
        } else if (ago < 86400) {
            written = snprintf(out, max, "%uh", (unsigned)(ago / 3600));
        } else {
            written = snprintf(out, max, "%ud", (unsigned)(ago / 86400));
        }
    } else {
        written = snprintf(out, max, "%s %d", months[month - 1], (int)day);
    }
    return written > 0 ? (size_t)written : 0;
}

/* A count as the console shows it: 999 at most as it is, then 1k, 12k. */
static size_t count_text(uint32_t count, char *out, size_t max)
{
    uint32_t thousands = count / 1000 > 999 ? 999 : count / 1000;
    int written = count < 1000 ? snprintf(out, max, "%u", (unsigned)count)
                               : snprintf(out, max, "%uk", (unsigned)thousands);
    return written > 0 ? (size_t)written : 0;
}

/* The last line: when it was posted at the left, and at the right its
 * replies, reposts and likes, each after its sign. */
static void when_line(const nesp_bsky_t *bsky, uint8_t *post)
{
    char line[COLUMNS + 1];
    char counts[COLUMNS + 1];
    memset(line, ' ', sizeof(line));
    size_t len = age(bsky, line, sizeof(line));
    if (len < COLUMNS) {
        line[len] = ' ';
    }
    size_t at = 0;
    const uint32_t values[] = {bsky->replies, bsky->reposts, bsky->likes};
    const char signs[] = {NESP_BSKY_REPLY, NESP_BSKY_REPOST, NESP_BSKY_LIKE};
    for (size_t index = 0; index < 3; index++) {
        if (at > 0) {
            counts[at++] = ' ';
        }
        counts[at++] = signs[index];
        at += count_text(values[index], counts + at, sizeof(counts) - at);
    }
    if (at <= COLUMNS && len + 1 + at <= COLUMNS) {
        memcpy(line + COLUMNS - at, counts, at);
    }
    put_line(post, WHEN_ROW, line, COLUMNS, 0);
}

/* The text, wrapped at spaces into TEXT_ROWS lines. Spaces in a row are
 * one, as are the spaces either side of a picture that was left out. A
 * newline ends a line, and lines left blank by newlines in a row are one
 * blank line. A word
 * longer than a line is broken where the line ends. Text that does not
 * fit ends with "...". */
static void text_lines(const nesp_bsky_t *bsky, uint8_t *post)
{
    char lines[TEXT_ROWS][COLUMNS];
    size_t lens[TEXT_ROWS];
    memset(lens, 0, sizeof(lens));
    size_t row = 0;
    size_t at = 0;
    bool cut = false;
    const char *text = bsky->text;
    size_t len = bsky->text_len;
    while (at < len && !cut) {
        if (text[at] == '\n') {
            at++;
            if (lens[row] == 0 && (row == 0 || lens[row - 1] == 0)) {
                continue;           /* blank already, or nothing yet */
            }
            if (++row == TEXT_ROWS) {
                cut = at < len;
                break;
            }
            continue;
        }
        if (text[at] == ' ') {
            if (lens[row] > 0 && lens[row] < COLUMNS && lines[row][lens[row] - 1] != ' ') {
                lines[row][lens[row]++] = ' ';
            }
            at++;
            continue;
        }
        size_t word = 0;
        while (at + word < len && text[at + word] != ' ' && text[at + word] != '\n') {
            word++;
        }
        if (lens[row] > 0 && lens[row] + word > COLUMNS) {
            while (lens[row] > 0 && lines[row][lens[row] - 1] == ' ') {
                lens[row]--;
            }
            if (++row == TEXT_ROWS) {
                cut = true;
                break;
            }
        }
        while (word > 0) {
            size_t take = COLUMNS - lens[row];
            if (take > word) {
                take = word;
            }
            memcpy(lines[row] + lens[row], text + at, take);
            lens[row] += take;
            at += take;
            word -= take;
            if (word > 0) {
                if (++row == TEXT_ROWS) {
                    cut = true;
                    break;
                }
            }
        }
    }
    if (cut) {
        size_t last = TEXT_ROWS - 1;
        while (lens[last] > 0 && lines[last][lens[last] - 1] == ' ') {
            lens[last]--;
        }
        if (lens[last] > COLUMNS - 3) {
            lens[last] = COLUMNS - 3;
        }
        memcpy(lines[last] + lens[last], "...", 3);
        lens[last] += 3;
    }
    for (size_t index = 0; index < TEXT_ROWS; index++) {
        put_line(post, (unsigned)(TEXT_ROW + index), lines[index], lens[index], 0);
    }
}

/* A post has ended in the reply: lay it out after the others, if it is
 * still this fetch's and there is room. */
static void lay_out(nesp_bsky_t *bsky)
{
    uint8_t post[POST_SIZE];
    char line[COLUMNS + 1];
    if (bsky->handle_field_len == 0) {
        return;                     /* not a post at all */
    }
    if (bsky->name_len > 0) {
        put_line(post, NAME_ROW, bsky->name, bsky->name_len, HEADING);
    } else {
        put_line(post, NAME_ROW, bsky->handle_field, bsky->handle_field_len, HEADING);
    }
    size_t take = bsky->handle_field_len < COLUMNS - 1 ? bsky->handle_field_len : COLUMNS - 1;
    line[0] = '@';
    memcpy(line + 1, bsky->handle_field, take);
    put_line(post, HANDLE_ROW, line, 1 + take, 0);
    if (bsky->reposter_len > 0) {
        static const char by[] = "Reposted by @";
        size_t len = sizeof(by) - 1;
        memcpy(line, by, len);
        take = bsky->reposter_len;
        if (len + take > COLUMNS) {
            take = COLUMNS - len;
        }
        memcpy(line + len, bsky->reposter, take);
        put_line(post, REPOST_ROW, line, len + take, 0);
    } else {
        put_line(post, REPOST_ROW, NULL, 0, 0);
    }
    text_lines(bsky, post);
    when_line(bsky, post);

    lock(bsky);
    if (bsky->generation == bsky->parsing && bsky->posts != NULL
        && bsky->count < NESP_BSKY_POSTS) {
        memcpy(bsky->posts + (size_t)bsky->count * POST_SIZE, post, POST_SIZE);
        bsky->count++;              /* last: a post is whole before it is offered */
    }
    unlock(bsky);
}

/* --- the reply, as it arrives ---------------------------------------------------- */

static bool key_is(const nesp_bsky_t *bsky, uint8_t depth, const char *name)
{
    size_t len = strlen(name);
    return bsky->key_lens[depth] == len && memcmp(bsky->keys[depth], name, len) == 0;
}

/* What the value about to begin is, by where it is: the keys of the
 * containers round it. The root is an object (1), "feed" in it a list (2),
 * an item of that an object (3), and so on. */
static uint8_t field_here(const nesp_bsky_t *bsky)
{
    uint8_t depth = bsky->depth;
    if (depth < 4 || !key_is(bsky, 1, "feed") || !bsky->listed) {
        return FIELD_NONE;
    }
    if (key_is(bsky, 3, "post")) {
        if (depth == 4) {
            if (key_is(bsky, 4, "indexedAt")) {
                return FIELD_WHEN;
            }
            if (key_is(bsky, 4, "replyCount")) {
                return FIELD_REPLIES;
            }
            if (key_is(bsky, 4, "repostCount")) {
                return FIELD_REPOSTS;
            }
            if (key_is(bsky, 4, "likeCount")) {
                return FIELD_LIKES;
            }
        } else if (depth == 5 && key_is(bsky, 4, "author")) {
            if (key_is(bsky, 5, "handle")) {
                return FIELD_HANDLE;
            }
            if (key_is(bsky, 5, "displayName")) {
                return FIELD_NAME;
            }
        } else if (depth == 5 && key_is(bsky, 4, "record") && key_is(bsky, 5, "text")) {
            return FIELD_TEXT;
        }
    } else if (key_is(bsky, 3, "reason") && depth == 5 && key_is(bsky, 4, "by")
               && key_is(bsky, 5, "handle")) {
        return FIELD_REPOSTER;
    }
    return FIELD_NONE;
}

/* Where the characters of the string being read go, and how much room. */
static char *field_room(nesp_bsky_t *bsky, size_t **len, size_t *max)
{
    switch (bsky->field) {
    case FIELD_HANDLE:
        *len = &bsky->handle_field_len;
        *max = sizeof(bsky->handle_field);
        return bsky->handle_field;
    case FIELD_NAME:
        *len = &bsky->name_len;
        *max = sizeof(bsky->name);
        return bsky->name;
    case FIELD_TEXT:
        *len = &bsky->text_len;
        *max = sizeof(bsky->text);
        return bsky->text;
    case FIELD_WHEN:
        *len = &bsky->when_len;
        *max = sizeof(bsky->when);
        return bsky->when;
    case FIELD_REPOSTER:
        *len = &bsky->reposter_len;
        *max = sizeof(bsky->reposter);
        return bsky->reposter;
    default:
        return NULL;
    }
}

static void put_chars(nesp_bsky_t *bsky, const char *text, size_t count)
{
    size_t *len;
    size_t max;
    char *room = field_room(bsky, &len, &max);
    if (room == NULL) {
        return;
    }
    for (size_t index = 0; index < count && *len < max; index++) {
        char letter = text[index];
        if (letter == '\n' && bsky->field != FIELD_TEXT) {
            letter = ' ';
        }
        room[(*len)++] = letter;
    }
}

/* A character of a string, by its code: as ASCII, or for one with no
 * likeness a "?", one for a run of them. Pictures (emoji) and what joins
 * or varies them are left out: a post has many, and a "?" for each says
 * nothing. */
static void put_code(nesp_bsky_t *bsky, uint32_t code)
{
    if (bsky->field == FIELD_NONE) {
        return;
    }
    if ((code >= 0x1F000 && code <= 0x1FAFF) || (code >= 0x2600 && code <= 0x27BF)
        || (code >= 0xFE00 && code <= 0xFE0F) || code == 0x200D || code == 0x20E3
        || (code >= 0xE0000 && code <= 0xE007F)) {
        return;
    }
    char text[4];
    int count = code == NO_CODE ? -1 : nesp_to_ascii(code, text);
    if (count < 0) {
        if (!bsky->unknown) {
            put_chars(bsky, "?", 1);
            bsky->unknown = true;
        }
    } else if (count > 0) {
        put_chars(bsky, text, (size_t)count);
        bsky->unknown = false;
    }
}

static int hex_value(uint8_t byte)
{
    if (byte >= '0' && byte <= '9') {
        return byte - '0';
    }
    if (byte >= 'a' && byte <= 'f') {
        return byte - 'a' + 10;
    }
    if (byte >= 'A' && byte <= 'F') {
        return byte - 'A' + 10;
    }
    return -1;
}

/* A \uXXXX has been read: a character, or half of one. */
static void put_unit(nesp_bsky_t *bsky, uint16_t unit)
{
    if (unit >= 0xD800 && unit <= 0xDBFF) {
        bsky->high = unit;
        return;
    }
    if (unit >= 0xDC00 && unit <= 0xDFFF) {
        if (bsky->high != 0) {
            put_code(bsky, 0x10000u + ((uint32_t)(bsky->high - 0xD800) << 10) + (unit - 0xDC00u));
        } else {
            put_code(bsky, NO_CODE);
        }
        bsky->high = 0;
        return;
    }
    if (bsky->high != 0) {
        put_code(bsky, NO_CODE);
        bsky->high = 0;
    }
    put_code(bsky, unit);
}

/* A byte of a string that is not part of an escape: UTF-8. */
static void put_byte(nesp_bsky_t *bsky, uint8_t byte)
{
    if (bsky->need != 0) {
        if ((byte & 0xC0) == 0x80) {
            bsky->code = bsky->code << 6 | (byte & 0x3F);
            if (--bsky->need == 0) {
                put_code(bsky, bsky->code);
            }
            return;
        }
        bsky->need = 0;             /* cut short: not UTF-8 */
        put_code(bsky, NO_CODE);
    }
    if (byte < 0x80) {
        put_code(bsky, byte);
    } else if (byte >= 0xF0) {
        bsky->need = 3;
        bsky->code = byte & 0x07;
    } else if (byte >= 0xE0) {
        bsky->need = 2;
        bsky->code = byte & 0x0F;
    } else if (byte >= 0xC0) {
        bsky->need = 1;
        bsky->code = byte & 0x1F;
    } else {
        put_code(bsky, NO_CODE);
    }
}

/* A byte inside a string: a key's, kept if it is short, or a value's. */
static void string_byte(nesp_bsky_t *bsky, uint8_t byte)
{
    if (bsky->escape == 1) {
        bsky->escape = 0;
        if (byte == 'u') {
            bsky->escape = 2;
            bsky->unit = 0;
            return;
        }
        static const char from[] = "\"\\/bfnrt";
        static const char to[] = "\"\\/  \n  ";
        const char *found = memchr(from, byte, sizeof(from) - 1);
        byte = found != NULL ? (uint8_t)to[found - from] : byte;
    } else if (bsky->escape >= 2) {
        int value = hex_value(byte);
        bsky->unit = (uint16_t)(bsky->unit << 4 | (value < 0 ? 0 : value));
        bsky->bad_hex |= value < 0;
        if (++bsky->escape == 6) {
            bsky->escape = 0;
            if (bsky->is_key) {
                /* a key's escapes are not kept: none of the ones looked for has one */
            } else if (bsky->bad_hex) {
                put_code(bsky, NO_CODE);
            } else {
                put_unit(bsky, bsky->unit);
            }
            bsky->bad_hex = false;
        }
        return;
    } else if (byte == '\\') {
        bsky->escape = 1;
        return;
    } else if (byte == '"') {
        bsky->in_string = false;
        bsky->high = 0;
        bsky->need = 0;
        if (!bsky->is_key) {
            bsky->field = FIELD_NONE;
        }
        return;
    }
    if (bsky->is_key) {
        uint8_t depth = bsky->depth;
        if (bsky->key_lens[depth] < NESP_BSKY_KEY) {
            bsky->keys[depth][bsky->key_lens[depth]] = (char)byte;
        }
        if (bsky->key_lens[depth] < 0xFF) {
            bsky->key_lens[depth]++;
        }
    } else {
        put_byte(bsky, byte);
    }
}

static void number_byte(nesp_bsky_t *bsky, uint8_t byte)
{
    uint32_t *value = bsky->field == FIELD_REPLIES   ? &bsky->replies
                      : bsky->field == FIELD_REPOSTS ? &bsky->reposts
                      : bsky->field == FIELD_LIKES   ? &bsky->likes
                                                     : NULL;
    if (value != NULL && byte >= '0' && byte <= '9' && *value < 100000000u) {
        *value = *value * 10 + (uint32_t)(byte - '0');
    }
}

static void begin_item(nesp_bsky_t *bsky)
{
    bsky->handle_field_len = 0;
    bsky->name_len = 0;
    bsky->text_len = 0;
    bsky->when_len = 0;
    bsky->reposter_len = 0;
    bsky->replies = bsky->reposts = bsky->likes = 0;
}

static void parse(nesp_bsky_t *bsky, const uint8_t *data, size_t len)
{
    for (size_t index = 0; index < len && !bsky->whole; index++) {
        uint8_t byte = data[index];
        if (bsky->in_string) {
            string_byte(bsky, byte);
            continue;
        }
        switch (byte) {
        case '"':
            bsky->in_string = true;
            bsky->escape = 0;
            bsky->unknown = false;
            bsky->is_key = bsky->deep == 0 && bsky->depth > 0 && bsky->want_key;
            if (bsky->is_key) {
                bsky->key_lens[bsky->depth] = 0;
            } else {
                bsky->field = bsky->deep == 0 ? field_here(bsky) : FIELD_NONE;
            }
            break;
        case '{':
        case '[':
            if (bsky->deep > 0 || bsky->depth + 1 >= NESP_BSKY_DEPTH) {
                bsky->deep++;       /* too deep to matter: counted, not followed */
                break;
            }
            bsky->depth++;
            bsky->lists = (uint16_t)(byte == '['
                                     ? bsky->lists | 1u << bsky->depth
                                     : bsky->lists & ~(1u << bsky->depth));
            bsky->key_lens[bsky->depth] = 0;
            bsky->want_key = byte == '{';
            if (bsky->depth == 2) {
                bsky->listed = byte == '[' && key_is(bsky, 1, "feed");
            }
            if (bsky->depth == 3 && bsky->listed && byte == '{') {
                begin_item(bsky);
            }
            break;
        case '}':
        case ']':
            if (bsky->deep > 0) {
                bsky->deep--;
                break;
            }
            if (bsky->depth == 0) {
                break;
            }
            if (bsky->depth == 3 && bsky->listed && byte == '}') {
                lay_out(bsky);
            }
            if (bsky->depth == 2) {
                bsky->listed = false;
            }
            bsky->depth--;
            bsky->want_key = false;
            if (bsky->depth == 0) {
                bsky->whole = true;
            }
            break;
        case ',':
            if (bsky->deep == 0 && bsky->depth > 0 && !(bsky->lists & 1u << bsky->depth)) {
                bsky->want_key = true;
            }
            bsky->field = FIELD_NONE;
            break;
        case ':':
            if (bsky->deep == 0) {
                bsky->want_key = false;
                bsky->field = field_here(bsky);
            }
            break;
        default:
            if (bsky->deep == 0) {
                number_byte(bsky, byte);
            }
            break;
        }
    }
}

/* --- the fetch's task ------------------------------------------------------------ */

static bool current(nesp_bsky_t *bsky, uint32_t id)
{
    lock(bsky);
    bool same = bsky->generation == id;
    unlock(bsky);
    return same;
}

/* Words for the console's screen, a line's width, centered. */
static void set_why(nesp_bsky_t *bsky, const char *text)
{
    size_t len = strlen(text);
    if (len > COLUMNS) {
        len = COLUMNS;
    }
    memset(bsky->why, ' ', COLUMNS);
    memcpy(bsky->why + (COLUMNS - len) / 2, text, len);
}

static bool body(void *ctx, uint32_t id, const uint8_t *data, size_t len)
{
    nesp_bsky_t *bsky = ctx;
    if (!current(bsky, id)) {
        return false;
    }
    if (bsky->parsing != id) {      /* the first of a new reply */
        bsky->parsing = id;
        bsky->depth = 0;
        bsky->deep = 0;
        bsky->lists = 0;
        bsky->listed = false;
        bsky->whole = false;
        bsky->in_string = false;
        bsky->want_key = false;
        bsky->field = FIELD_NONE;
        bsky->need = 0;
        bsky->high = 0;
        bsky->bad_hex = false;
        memset(bsky->key_lens, 0, sizeof(bsky->key_lens));
    }
    parse(bsky, data, len);
    lock(bsky);
    bool full = bsky->count >= NESP_BSKY_POSTS;
    unlock(bsky);
    return !bsky->whole && !full && current(bsky, id);
}

static void done(void *ctx, uint32_t id, bool ok, const char *why)
{
    nesp_bsky_t *bsky = ctx;
    lock(bsky);
    if (bsky->generation == id) {
        bool began = bsky->parsing == id;
        if (ok || (began && bsky->count > 0)) {
            /* A reply cut short still has the posts that came whole. */
            bsky->state = NESP_FEED_READY;
        } else if (why != NULL && strcmp(why, NO_SUCH) == 0) {
            bsky->count = 0;
            bsky->state = NESP_FEED_NOT_FOUND;
        } else {
            bsky->count = 0;
            set_why(bsky, why != NULL && why[0] != 0 ? why : "THE FETCH FAILED");
            bsky->state = NESP_FEED_FAILED;
        }
    }
    unlock(bsky);
}

/* --- the link's task ------------------------------------------------------------- */

static void begin(nesp_bsky_t *bsky)
{
    char url[256];
    nesp_wifi_t wifi;
    memset(&wifi, 0, sizeof(wifi));
    bsky->hal->wifi(bsky->hal->ctx, &wifi);
    bool online = wifi.state == NESP_WIFI_JOINED;
    uint32_t clock = 0;
    bool known = bsky->hal->time != NULL && bsky->hal->time(bsky->hal->ctx, &clock);

    lock(bsky);
    bsky->generation++;             /* whatever was being fetched is no longer wanted */
    bsky->count = 0;
    bsky->state = online ? NESP_FEED_FETCHING : NESP_FEED_NO_WIFI;
    bsky->clock = clock;            /* the fetch's task reads them once it begins */
    bsky->clock_known = known;
    uint32_t id = bsky->generation;
    unlock(bsky);
    if (!online) {
        bsky->hal->fetch_stop(bsky->hal->ctx);
        return;
    }
    snprintf(url, sizeof(url), FEED_URL, NESP_BSKY_POSTS, (int)bsky->handle_len, bsky->handle);
    if (bsky->posts == NULL || !bsky->hal->fetch(bsky->hal->ctx, url, AGENT, id, &bsky->sink)) {
        lock(bsky);
        set_why(bsky, bsky->posts == NULL ? "THE NESP32 IS OUT OF MEMORY" : "THE NESP32 IS BUSY");
        bsky->state = NESP_FEED_FAILED;
        unlock(bsky);
    }
}

/* FAVORITE: how many there are, and the one asked for, if there is one. */
static void favorite(nesp_bsky_t *bsky, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len != 1 || reply->max < 2 + NESP_BSKY_HANDLE_MAX) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    uint8_t number = request->data[0];
    reply->data[0] = bsky->favorites.count;
    reply->data[1] = number;
    reply->len = 2;
    if (number < bsky->favorites.count) {
        size_t len = favorite_len(&bsky->favorites, number);
        memcpy(reply->data + 2, bsky->favorites.handles[number], len);
        reply->len = (uint8_t)(2 + len);
    }
    reply->once = true;             /* the list may have changed by the next time */
}

/* ADD: the handle onto the end of the favorites, unless it is there
 * already. Its number, or $FF if there was no room. */
static void add(nesp_bsky_t *bsky, const nesp_request_t *request, nesp_reply_t *reply)
{
    char handle[NESP_BSKY_HANDLE_MAX];
    size_t len = normal_handle(request->data, request->len, handle);
    if (len == 0) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    nesp_bsky_favorites_t *favorites = &bsky->favorites;
    uint8_t number = 0;
    while (number < favorites->count
           && !(favorite_len(favorites, number) == len
                && memcmp(favorites->handles[number], handle, len) == 0)) {
        number++;
    }
    if (number == favorites->count) {
        if (number == NESP_BSKY_FAVORITES) {
            number = 0xFF;
        } else {
            memset(favorites->handles[number], 0, NESP_BSKY_HANDLE_MAX);
            memcpy(favorites->handles[number], handle, len);
            favorites->count++;
            keep(bsky);
        }
    }
    reply->data[0] = favorites->count;
    reply->data[1] = number;
    reply->len = 2;
}

/* REMOVE: a favorite, by its number; the ones after it move up. */
static void remove_one(nesp_bsky_t *bsky, const nesp_request_t *request, nesp_reply_t *reply)
{
    nesp_bsky_favorites_t *favorites = &bsky->favorites;
    if (request->len != 1) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    uint8_t number = request->data[0];
    if (number < favorites->count) {
        memmove(favorites->handles[number], favorites->handles[number + 1],
                (size_t)(favorites->count - number - 1) * NESP_BSKY_HANDLE_MAX);
        favorites->count--;
        memset(favorites->handles[favorites->count], 0, NESP_BSKY_HANDLE_MAX);
        keep(bsky);
    }
    reply->data[0] = favorites->count;
    reply->len = 1;
}

/* FEED: this handle, and how it stands with its posts. */
static void feed(nesp_bsky_t *bsky, const nesp_request_t *request, nesp_reply_t *reply)
{
    char handle[NESP_BSKY_HANDLE_MAX];
    size_t len = request->len < 2 ? 0 : normal_handle(request->data + 1, request->len - 1u, handle);
    if (len == 0 || reply->max < 3 + COLUMNS) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    uint8_t id = request->data[0];
    if (!bsky->chosen || id != bsky->feed_id || len != bsky->handle_len
        || memcmp(handle, bsky->handle, len) != 0) {
        bsky->chosen = true;
        bsky->feed_id = id;
        bsky->handle_len = (uint8_t)len;
        memcpy(bsky->handle, handle, len);
        begin(bsky);
    }
    lock(bsky);
    uint8_t state = bsky->state;
    reply->data[0] = state;
    reply->data[1] = id;
    reply->data[2] = bsky->count;
    reply->len = 3;
    if (state == NESP_FEED_FAILED) {
        memcpy(reply->data + 3, bsky->why, COLUMNS);
        reply->len = 3 + COLUMNS;
    }
    unlock(bsky);
    reply->once = true;             /* the same request again asks how it stands now */
}

/* LINE: a line of a post, if the post is held. */
static void line(nesp_bsky_t *bsky, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len != 2 || reply->max < 4 + COLUMNS) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    uint8_t post = request->data[0];
    uint8_t row = request->data[1];
    lock(bsky);
    uint8_t state = bsky->state;
    uint8_t count = bsky->count;
    if (post < count && row < ROWS && bsky->posts != NULL) {
        memcpy(reply->data + 4, bsky->posts + (size_t)post * POST_SIZE + (size_t)row * COLUMNS,
               COLUMNS);
        reply->len = 4 + COLUMNS;
    } else {
        state |= NESP_FEED_NO_LINE;
        reply->len = 4;
    }
    unlock(bsky);
    reply->data[0] = state;
    reply->data[1] = post;
    reply->data[2] = row;
    reply->data[3] = count;
    reply->once = true;             /* a post not held yet may be by the next time */
}

static void handle(void *ctx, const nesp_request_t *request, nesp_reply_t *reply)
{
    nesp_bsky_t *bsky = ctx;
    switch (request->op) {
    case NESP_BSKY_FAVORITE:
        favorite(bsky, request, reply);
        break;
    case NESP_BSKY_ADD:
        add(bsky, request, reply);
        break;
    case NESP_BSKY_REMOVE:
        remove_one(bsky, request, reply);
        break;
    case NESP_BSKY_FEED:
        feed(bsky, request, reply);
        break;
    case NESP_BSKY_LINE:
        line(bsky, request, reply);
        break;
    default:
        reply->status = NESP_ST_NO_OP;
        break;
    }
}

/* The favorites the board keeps, or the defaults. A kept list that makes
 * no sense is taken for none. */
static void load_favorites(nesp_bsky_t *bsky)
{
    nesp_bsky_favorites_t *favorites = &bsky->favorites;
    memset(favorites, 0, sizeof(*favorites));
    if (bsky->hal->favorites_last != NULL && bsky->hal->favorites_last(bsky->hal->ctx, favorites)
        && favorites->count <= NESP_BSKY_FAVORITES) {
        return;
    }
    memset(favorites, 0, sizeof(*favorites));
    for (size_t index = 0; index < sizeof(defaults) / sizeof(defaults[0]); index++) {
        strncpy(favorites->handles[index], defaults[index], NESP_BSKY_HANDLE_MAX);
    }
    favorites->count = sizeof(defaults) / sizeof(defaults[0]);
}

/* A hello has asked for the service: room for the posts. */
static void activate(void *ctx)
{
    nesp_bsky_t *bsky = ctx;
    uint8_t *posts = bsky->hal->alloc(bsky->hal->ctx, (size_t)NESP_BSKY_POSTS * POST_SIZE);
    lock(bsky);
    bsky->posts = posts;
    bsky->count = 0;
    bsky->state = NESP_FEED_IDLE;
    bsky->generation++;
    unlock(bsky);
    bsky->chosen = false;
    load_favorites(bsky);
}

/* Another ROM is on the console, or this one was reset. */
static void deactivate(void *ctx)
{
    nesp_bsky_t *bsky = ctx;
    bsky->hal->fetch_stop(bsky->hal->ctx);
    lock(bsky);
    uint8_t *posts = bsky->posts;
    bsky->posts = NULL;
    bsky->count = 0;
    bsky->state = NESP_FEED_IDLE;
    bsky->generation++;             /* a fetch still on its way adds nothing */
    unlock(bsky);
    if (posts != NULL) {
        bsky->hal->release(bsky->hal->ctx, posts);
    }
}

void nesp_bsky_service(nesp_service_t *service, nesp_bsky_t *bsky, const nesp_hal_t *hal)
{
    memset(bsky, 0, sizeof(*bsky));
    bsky->hal = hal;
    bsky->sink.ctx = bsky;
    bsky->sink.body = body;
    bsky->sink.done = done;
    memset(service, 0, sizeof(*service));
    service->id = NESP_SVC_BSKY;
    service->name = "BSKY";
    service->activate = activate;
    service->deactivate = deactivate;
    service->handle = handle;
    service->ctx = bsky;
}
