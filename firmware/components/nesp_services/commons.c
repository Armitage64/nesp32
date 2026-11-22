/* COMMONS: pictures from Wikimedia Commons, found by words typed on the
 * console and made into what the NES can show (docs/PROTOCOL.md). The
 * Gallery's service (apps/gallery).
 *
 * SEARCH is both "search for this" and "how is it going", as WIKI's is:
 * the console gives each search an id and sends it again until it has
 * ended one way or another. A search asks Commons's API for up to
 * NESP_COMMONS_RESULTS pictures, with each one's thumbnail, author and
 * licence, and keeps those that pass.
 *
 * What is searched is kept to what Commons's people have judged to be good
 * photographs (its Quality and Featured pictures, as JPEGs), with words
 * that mark adult pictures ruled out of the search itself; a search for
 * such words is not made at all, and a picture whose name has one is
 * dropped. Commons has no safe search of its own, and this is a filter of
 * words: it keeps most such pictures out, not all.
 *
 * OPEN asks for a picture, by its place in the search: the nesp32 fetches
 * its thumbnail, decodes it and makes it into tiles (picture.c), and then
 * says READY. DATA has it NESP_COMMONS_CHUNK bytes at a time. CAPTION has
 * a picture's words for the screen: its name on two lines, by whom, and
 * its licence, which asks that the two be said.
 *
 * Two tasks meet here, as in wiki.c. The link's runs handle() and starts
 * fetches; the fetch's runs body() and done(), and does the parsing and
 * the making. They share the states, under the hal's lock; `generation` is
 * the fetch now wanted, and a sink's call for any other does nothing. What
 * is held is read by the link's task only in a state that says the fetch's
 * task is done with it.
 */
#include <stdio.h>
#include <string.h>

#include "nesp_services.h"

#define COLUMNS NESP_COMMONS_COLUMNS
#define AGENT "nesp32-Gallery/0.1 (pictures from Wikimedia Commons on the NES; nesp32)"
#define BODY_MAX (192 * 1024)       /* a search's reply is about 40 KB, a thumbnail under 64 */
#define URL_MAX 400                 /* of a thumbnail's address */
#define NAME_MAX 160
#define FOUND_MAX 50                /* pictures a reply may list */
#define API "https://commons.wikimedia.org/w/api.php?action=query&format=json" \
    "&formatversion=2&generator=search&gsrnamespace=6&gsrlimit=20&prop=imageinfo" \
    "&iiprop=url%7Cextmetadata&iiextmetadatafilter=Artist%7CLicenseShortName" \
    "&iiurlwidth=320&gsrsearch="
/* After the words: where to look, and what to rule out. */
#define FILTER " filemime:image/jpeg incategory:Quality_images|Featured_pictures_on_Wikimedia_Commons" \
    " -nude -naked -nudity -topless -erotic -sexual -porn -genitalia -penis -vagina" \
    " -breasts -lingerie -bikini -underwear"

/* Words that are not searched for, and pictures whose names have one are
 * not kept: whole words, and words that begin so. */
static const char *const banned_words[] = {
    "naked", "topless", "nipple", "nipples", "breast", "breasts", "boob", "boobs", "tits",
    "penis", "vagina", "vulva", "lingerie", "bikini", "underwear", "xxx", "bdsm", "nsfw",
    "genitals", "genitalia", "orgy", "stripper", "dildo",
};
static const char *const banned_starts[] = {
    "nud", "porn", "erotic", "sex", "fetish", "hentai", "masturbat", "intercourse",
};

typedef struct {
    int32_t index;                  /* the search's order */
    char name[NAME_MAX];
    char artist[NAME_MAX];
    char licence[NAME_MAX];
    char url[URL_MAX];
} found_t;

struct nesp_commons_store {
    uint8_t lines[NESP_COMMONS_RESULTS][NESP_COMMONS_LINES][COLUMNS];
    char urls[NESP_COMMONS_RESULTS][URL_MAX];
    uint8_t picture[NESP_COMMONS_SIZE];
    found_t found[FOUND_MAX];
    uint8_t body[BODY_MAX];
};

static void lock(nesp_commons_t *commons)
{
    commons->hal->lock(commons->hal->ctx);
}

static void unlock(nesp_commons_t *commons)
{
    commons->hal->unlock(commons->hal->ctx);
}

/* A line of words for the console's screen: a line's width, centered,
 * capitals, as the console's own messages are. */
static void message(uint8_t *line, const char *text)
{
    size_t len = strlen(text);
    if (len > COLUMNS) {
        len = COLUMNS;
    }
    size_t left = (COLUMNS - len) / 2;
    memset(line, ' ', COLUMNS);
    for (size_t index = 0; index < len; index++) {
        char letter = text[index];
        if (letter >= 'a' && letter <= 'z') {
            letter = (char)(letter - 'a' + 'A');
        }
        line[left + index] = (uint8_t)letter;
    }
}

/* --- words ------------------------------------------------------------------- */

static char lower(char letter)
{
    return letter >= 'A' && letter <= 'Z' ? (char)(letter - 'A' + 'a') : letter;
}

static bool alnum(char letter)
{
    letter = lower(letter);
    return (letter >= 'a' && letter <= 'z') || (letter >= '0' && letter <= '9');
}

static bool banned_word(const char *word, size_t len)
{
    for (size_t index = 0; index < sizeof(banned_words) / sizeof(banned_words[0]); index++) {
        const char *banned = banned_words[index];
        if (strlen(banned) != len) {
            continue;
        }
        size_t at = 0;
        while (at < len && lower(word[at]) == banned[at]) {
            at++;
        }
        if (at == len) {
            return true;
        }
    }
    for (size_t index = 0; index < sizeof(banned_starts) / sizeof(banned_starts[0]); index++) {
        const char *banned = banned_starts[index];
        size_t start = strlen(banned);
        if (start > len) {
            continue;
        }
        size_t at = 0;
        while (at < start && lower(word[at]) == banned[at]) {
            at++;
        }
        if (at == start) {
            return true;
        }
    }
    return false;
}

bool nesp_commons_unsafe(const char *text, size_t len)
{
    size_t at = 0;
    while (at < len) {
        while (at < len && !alnum(text[at])) {
            at++;
        }
        size_t start = at;
        while (at < len && alnum(text[at])) {
            at++;
        }
        if (at > start && banned_word(text + start, at - start)) {
            return true;
        }
    }
    return false;
}

/* The address of a search for the words. Its length, or 0 if it does not
 * fit. */
size_t nesp_commons_url(const uint8_t *words, size_t len, char *out, size_t max)
{
    static const char hex[] = "0123456789ABCDEF";
    size_t at = strlen(API);
    if (at >= max) {
        return 0;
    }
    memcpy(out, API, at);
    for (size_t part = 0; part < 2; part++) {
        const uint8_t *text = part == 0 ? words : (const uint8_t *)FILTER;
        size_t count = part == 0 ? len : strlen(FILTER);
        for (size_t index = 0; index < count; index++) {
            uint8_t c = text[index];
            if (at + 4 > max) {
                return 0;
            }
            if (alnum((char)c) || c == '-' || c == '_' || c == '.' || c == '~' || c == ':'
                || c == '/') {
                out[at++] = (char)c;
            } else if (c == ' ') {
                out[at++] = '+';
            } else {
                out[at++] = '%';
                out[at++] = hex[c >> 4];
                out[at++] = hex[c & 15];
            }
        }
    }
    out[at] = '\0';
    return at;
}

/* --- a search's reply: just enough JSON ------------------------------------- */

typedef struct {
    const uint8_t *s;
    size_t n;
    size_t i;
    bool bad;
} json_t;

static void json_space(json_t *json)
{
    while (json->i < json->n && (json->s[json->i] == ' ' || json->s[json->i] == '\n'
                                 || json->s[json->i] == '\r' || json->s[json->i] == '\t')) {
        json->i++;
    }
}

static bool json_take(json_t *json, uint8_t c)
{
    json_space(json);
    if (json->i < json->n && json->s[json->i] == c) {
        json->i++;
        return true;
    }
    return false;
}

static uint32_t json_hex(json_t *json)
{
    uint32_t value = 0;
    for (int digit = 0; digit < 4; digit++) {
        if (json->i >= json->n) {
            json->bad = true;
            return 0;
        }
        uint8_t c = json->s[json->i++];
        value <<= 4;
        if (c >= '0' && c <= '9') {
            value |= (uint32_t)(c - '0');
        } else if ((c | 0x20) >= 'a' && (c | 0x20) <= 'f') {
            value |= (uint32_t)((c | 0x20) - 'a' + 10);
        } else {
            json->bad = true;
        }
    }
    return value;
}

/* A string, as ASCII (nesp_to_ascii), into out if it is not NULL: at most
 * max - 1 characters, then a 0. A run of characters with no likeness is one
 * "?". */
static void json_string(json_t *json, char *out, size_t max)
{
    size_t len = 0;
    bool unknown = false;
    if (!json_take(json, '"')) {
        json->bad = true;
        return;
    }
    while (json->i < json->n) {
        uint8_t c = json->s[json->i++];
        uint32_t code;
        if (c == '"') {
            break;
        }
        if (c == '\\') {
            if (json->i >= json->n) {
                json->bad = true;
                break;
            }
            c = json->s[json->i++];
            switch (c) {
            case 'n': code = '\n'; break;
            case 't': code = ' '; break;
            case 'r': case 'b': case 'f': code = ' '; break;
            case 'u':
                code = json_hex(json);
                if (code >= 0xD800 && code < 0xDC00 && json->i + 6 <= json->n
                    && json->s[json->i] == '\\' && json->s[json->i + 1] == 'u') {
                    json->i += 2;
                    uint32_t low = json_hex(json);
                    code = 0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00);
                }
                break;
            default: code = c; break;
            }
        } else if (c < 0x80) {
            code = c;
        } else {
            int more = c >= 0xF0 ? 3 : c >= 0xE0 ? 2 : 1;
            code = c & (more == 3 ? 0x07u : more == 2 ? 0x0Fu : 0x1Fu);
            while (more-- > 0 && json->i < json->n) {
                code = code << 6 | (json->s[json->i++] & 0x3Fu);
            }
        }
        if (out == NULL) {
            continue;
        }
        char ascii[4];
        int count = nesp_to_ascii(code, ascii);
        if (count < 0) {
            if (unknown) {
                continue;
            }
            unknown = true;
            ascii[0] = '?';
            count = 1;
        } else if (count > 0) {
            unknown = false;
        }
        for (int at = 0; at < count && len + 1 < max; at++) {
            out[len++] = ascii[at] == '\n' ? ' ' : ascii[at];
        }
    }
    if (out != NULL && max > 0) {
        out[len] = '\0';
    }
}

static void json_skip(json_t *json);

static void json_skip_group(json_t *json, uint8_t close)
{
    json->i++;
    while (!json->bad) {
        json_space(json);
        if (json->i >= json->n) {
            json->bad = true;
            return;
        }
        if (json->s[json->i] == close) {
            json->i++;
            return;
        }
        if (json->s[json->i] == ',' || json->s[json->i] == ':') {
            json->i++;
            continue;
        }
        json_skip(json);
    }
}

static void json_skip(json_t *json)
{
    json_space(json);
    if (json->i >= json->n) {
        json->bad = true;
        return;
    }
    uint8_t c = json->s[json->i];
    if (c == '"') {
        json_string(json, NULL, 0);
    } else if (c == '{') {
        json_skip_group(json, '}');
    } else if (c == '[') {
        json_skip_group(json, ']');
    } else {
        while (json->i < json->n && json->s[json->i] != ',' && json->s[json->i] != '}'
               && json->s[json->i] != ']') {
            json->i++;
        }
    }
}

/* In an object just entered: the next member's key, and the value is next.
 * False at the end of the object, which is passed. */
static bool json_member(json_t *json, char *key, size_t max)
{
    if (json->bad) {
        return false;
    }
    json_take(json, ',');
    if (json_take(json, '}')) {
        return false;
    }
    json_string(json, key, max);
    if (!json_take(json, ':')) {
        json->bad = true;
        return false;
    }
    return !json->bad;
}

/* In an array just entered: true if an element is next. */
static bool json_element(json_t *json)
{
    if (json->bad) {
        return false;
    }
    json_take(json, ',');
    if (json_take(json, ']')) {
        return false;
    }
    json_space(json);
    return json->i < json->n;
}

static int32_t json_number(json_t *json)
{
    json_space(json);
    int32_t value = 0;
    while (json->i < json->n && json->s[json->i] >= '0' && json->s[json->i] <= '9') {
        value = value * 10 + (json->s[json->i++] - '0');
    }
    json_skip(json);
    return value;
}

/* {"value": "..."}: the value. */
static void json_value(json_t *json, char *out, size_t max)
{
    char key[16];
    if (!json_take(json, '{')) {
        json_skip(json);
        return;
    }
    while (json_member(json, key, sizeof(key))) {
        if (strcmp(key, "value") == 0) {
            json_string(json, out, max);
        } else {
            json_skip(json);
        }
    }
}

static void parse_imageinfo(json_t *json, found_t *found)
{
    char key[24];
    if (!json_take(json, '[')) {
        json_skip(json);
        return;
    }
    bool first = true;
    while (json_element(json)) {
        if (!first || !json_take(json, '{')) {
            json_skip(json);
            continue;
        }
        first = false;
        while (json_member(json, key, sizeof(key))) {
            if (strcmp(key, "thumburl") == 0) {
                json_string(json, found->url, sizeof(found->url));
            } else if (strcmp(key, "extmetadata") == 0 && json_take(json, '{')) {
                while (json_member(json, key, sizeof(key))) {
                    if (strcmp(key, "Artist") == 0) {
                        json_value(json, found->artist, sizeof(found->artist));
                    } else if (strcmp(key, "LicenseShortName") == 0) {
                        json_value(json, found->licence, sizeof(found->licence));
                    } else {
                        json_skip(json);
                    }
                }
            } else {
                json_skip(json);
            }
        }
    }
}

/* The pictures a reply lists, in the order it gives them. */
static size_t parse_reply(const uint8_t *body, size_t len, found_t *found)
{
    json_t json = {body, len, 0, false};
    char key[24];
    size_t count = 0;
    if (!json_take(&json, '{')) {
        return 0;
    }
    while (json_member(&json, key, sizeof(key))) {
        if (strcmp(key, "query") != 0 || !json_take(&json, '{')) {
            json_skip(&json);
            continue;
        }
        while (json_member(&json, key, sizeof(key))) {
            if (strcmp(key, "pages") != 0 || !json_take(&json, '[')) {
                json_skip(&json);
                continue;
            }
            while (json_element(&json)) {
                if (count >= FOUND_MAX || !json_take(&json, '{')) {
                    json_skip(&json);
                    continue;
                }
                found_t *one = &found[count];
                memset(one, 0, sizeof(*one));
                one->index = INT32_MAX;
                while (json_member(&json, key, sizeof(key))) {
                    if (strcmp(key, "index") == 0) {
                        one->index = json_number(&json);
                    } else if (strcmp(key, "title") == 0) {
                        json_string(&json, one->name, sizeof(one->name));
                    } else if (strcmp(key, "imageinfo") == 0) {
                        parse_imageinfo(&json, one);
                    } else {
                        json_skip(&json);
                    }
                }
                if (!json.bad) {
                    count++;
                }
            }
        }
    }
    return count;
}

/* --- a picture's words ------------------------------------------------------- */

/* A file's name as words: no "File:", no extension, spaces for
 * underscores. */
static void tidy_name(char *name)
{
    size_t len = strlen(name);
    if (strncmp(name, "File:", 5) == 0) {
        memmove(name, name + 5, len - 4);
        len -= 5;
    }
    char *dot = strrchr(name, '.');
    if (dot != NULL && len - (size_t)(dot - name) <= 5) {
        *dot = '\0';
    }
    for (char *c = name; *c != '\0'; c++) {
        if (*c == '_') {
            *c = ' ';
        }
    }
}

/* HTML (an author's, as Commons gives it) as plain words: no tags, the
 * common entities as what they stand for, spaces run together. */
static void tidy_html(char *text)
{
    static const struct {
        const char *name;
        char letter;
    } entities[] = {{"&amp;", '&'}, {"&lt;", '<'}, {"&gt;", '>'}, {"&quot;", '"'},
                    {"&#39;", '\''}, {"&#039;", '\''}, {"&apos;", '\''}, {"&nbsp;", ' '}};
    char *out = text;
    bool tag = false;
    bool space = true;              /* none at the start */
    for (const char *in = text; *in != '\0'; in++) {
        if (*in == '<') {
            tag = true;
            continue;
        }
        if (tag) {
            tag = *in != '>';
            continue;
        }
        char letter = *in;
        if (letter == '&') {
            for (size_t index = 0; index < sizeof(entities) / sizeof(entities[0]); index++) {
                size_t len = strlen(entities[index].name);
                if (strncmp(in, entities[index].name, len) == 0) {
                    letter = entities[index].letter;
                    in += len - 1;
                    break;
                }
            }
        }
        if (letter == ' ' || letter == '\t' || letter == '\n') {
            if (space) {
                continue;
            }
            letter = ' ';
        }
        space = letter == ' ';
        *out++ = letter;
    }
    while (out > text && out[-1] == ' ') {
        out--;
    }
    *out = '\0';
}

/* Words into a line of the screen's width, cut with "..." if they are
 * longer. */
static void fill_line(uint8_t *line, const char *text)
{
    size_t len = strlen(text);
    memset(line, ' ', COLUMNS);
    if (len > COLUMNS) {
        memcpy(line, text, COLUMNS - 3);
        memcpy(line + COLUMNS - 3, "...", 3);
    } else {
        memcpy(line, text, len);
    }
}

/* A name over two lines, broken at a space where there is one. */
static void name_lines(uint8_t *first, uint8_t *second, const char *name)
{
    size_t len = strlen(name);
    memset(first, ' ', COLUMNS);
    memset(second, ' ', COLUMNS);
    if (len <= COLUMNS) {
        memcpy(first, name, len);
        return;
    }
    size_t cut = COLUMNS;
    while (cut > COLUMNS / 2 && name[cut] != ' ') {
        cut--;
    }
    if (name[cut] != ' ') {
        cut = COLUMNS;
    }
    memcpy(first, name, cut);
    const char *rest = name + cut;
    while (*rest == ' ') {
        rest++;
    }
    fill_line(second, rest);
}

/* The reply's pictures, the best first, those that pass, as the lines and
 * addresses the console's requests are answered from. Their count. */
static uint8_t keep(struct nesp_commons_store *store, size_t count)
{
    found_t *found = store->found;
    for (size_t a = 1; a < count; a++) {    /* by the search's order */
        for (size_t b = a; b > 0 && found[b].index < found[b - 1].index; b--) {
            found_t swap = found[b];
            found[b] = found[b - 1];
            found[b - 1] = swap;
        }
    }
    uint8_t kept = 0;
    for (size_t index = 0; index < count && kept < NESP_COMMONS_RESULTS; index++) {
        found_t *one = &found[index];
        char *query = strchr(one->url, '?');
        if (query != NULL) {
            *query = '\0';
        }
        tidy_name(one->name);
        tidy_html(one->artist);
        tidy_html(one->licence);
        if (one->url[0] == '\0' || strlen(one->url) >= URL_MAX - 1
            || nesp_commons_unsafe(one->name, strlen(one->name))) {
            continue;
        }
        uint8_t (*lines)[COLUMNS] = store->lines[kept];
        name_lines(lines[0], lines[1], one->name);
        char by[NAME_MAX + 8];
        snprintf(by, sizeof(by), "By %s", one->artist[0] != '\0' ? one->artist : "an unknown author");
        fill_line(lines[2], by);
        fill_line(lines[3], one->licence[0] != '\0' ? one->licence : "Licence not given");
        snprintf(store->urls[kept], URL_MAX, "%s", one->url);
        kept++;
    }
    return kept;
}

/* --- the fetch's task -------------------------------------------------------- */

static bool current(nesp_commons_t *commons, uint32_t id)
{
    lock(commons);
    bool same = commons->generation == id;
    unlock(commons);
    return same;
}

/* The memory, for the fetch's task to work in, if this fetch is still the
 * one wanted. While it is held a deactivate does not give the memory back:
 * let_go does, if it is no longer the service's. */
static struct nesp_commons_store *hold(nesp_commons_t *commons, uint32_t id)
{
    lock(commons);
    struct nesp_commons_store *store = commons->generation == id ? commons->store : NULL;
    commons->busy = store != NULL;
    unlock(commons);
    return store;
}

static void let_go(nesp_commons_t *commons, struct nesp_commons_store *store)
{
    lock(commons);
    commons->busy = false;
    bool dropped = commons->store != store;
    unlock(commons);
    if (dropped) {
        commons->hal->release(commons->hal->ctx, store);
    }
}

static bool body(void *ctx, uint32_t id, const uint8_t *data, size_t len)
{
    nesp_commons_t *commons = ctx;
    struct nesp_commons_store *store = hold(commons, id);
    if (store == NULL) {
        return false;
    }
    if (commons->filling != id) {   /* the first of a new reply */
        commons->filling = id;
        commons->body_len = 0;
        commons->body_full = false;
    }
    size_t room = BODY_MAX - commons->body_len;
    if (len > room) {
        commons->body_full = true;
        len = room;
    }
    memcpy(store->body + commons->body_len, data, len);
    commons->body_len += len;
    bool more = !commons->body_full;
    let_go(commons, store);
    return more && current(commons, id);
}

static void search_done(nesp_commons_t *commons, struct nesp_commons_store *store, uint32_t id,
                        bool ok, const char *why)
{
    uint8_t count = 0;
    if (ok && !commons->body_full) {
        count = keep(store, parse_reply(store->body, commons->body_len, store->found));
    }
    lock(commons);
    if (commons->generation == id) {
        if (!ok || commons->body_full) {
            message(commons->album_message, commons->body_full ? "THE ANSWER WAS TOO LONG"
                                            : why != NULL && why[0] != '\0' ? why
                                            : "THE SEARCH FAILED");
            commons->album = NESP_ALBUM_FAILED;
        } else {
            commons->count = count;
            commons->album = count != 0 ? NESP_ALBUM_READY : NESP_ALBUM_NOT_FOUND;
        }
    }
    unlock(commons);
}

static void photo_done(nesp_commons_t *commons, struct nesp_commons_store *store, uint32_t id,
                       bool ok, const char *why)
{
    const char *failed = NULL;
    if (!ok) {
        failed = why != NULL && why[0] != '\0' ? why : "THE PICTURE DID NOT COME";
    } else if (commons->body_full) {
        failed = "THE PICTURE IS TOO BIG";
    } else {
        uint32_t width = 0;
        uint32_t height = 0;
        uint8_t *rgb = nesp_picture_decode(commons->hal, store->body, commons->body_len,
                                           &width, &height);
        if (rgb == NULL) {
            failed = "THE PICTURE CANNOT BE READ";
        } else {
            /* Nothing reads the picture while one is being fetched. */
            if (!nesp_picture_make(commons->hal, rgb, width, height, store->picture)) {
                failed = "THE NESP32 IS OUT OF MEMORY";
            }
            nesp_picture_release(commons->hal, rgb);
        }
    }
    lock(commons);
    if (commons->generation == id) {
        if (failed != NULL) {
            message(commons->photo_message, failed);
            commons->photo = NESP_PHOTO_FAILED;
        } else {
            commons->photo = NESP_PHOTO_READY;
        }
    }
    unlock(commons);
}

static void done(void *ctx, uint32_t id, bool ok, const char *why)
{
    nesp_commons_t *commons = ctx;
    struct nesp_commons_store *store = hold(commons, id);
    if (store == NULL) {
        return;
    }
    if (commons->filling != id) {   /* nothing of it came */
        commons->filling = id;
        commons->body_len = 0;
        commons->body_full = false;
    }
    lock(commons);
    bool photo = commons->fetching_photo;
    unlock(commons);
    if (photo) {
        photo_done(commons, store, id, ok, why);
    } else {
        search_done(commons, store, id, ok, why);
    }
    let_go(commons, store);
}

/* --- the link's task --------------------------------------------------------- */

static bool online(nesp_commons_t *commons)
{
    nesp_wifi_t wifi;
    memset(&wifi, 0, sizeof(wifi));
    commons->hal->wifi(commons->hal->ctx, &wifi);
    return wifi.state == NESP_WIFI_JOINED;
}

static void begin_search(nesp_commons_t *commons)
{
    char url[1024];
    bool unsafe = nesp_commons_unsafe((const char *)commons->query, commons->query_len);
    bool connected = online(commons);
    lock(commons);
    commons->generation++;          /* whatever was being fetched is no longer wanted */
    commons->fetching_photo = false;
    commons->count = 0;
    commons->photo = NESP_PHOTO_IDLE;
    commons->album = unsafe ? NESP_ALBUM_NOT_FOUND
                   : connected ? NESP_ALBUM_SEARCHING : NESP_ALBUM_NO_WIFI;
    uint32_t id = commons->generation;
    unlock(commons);
    if (unsafe || !connected) {
        commons->hal->fetch_stop(commons->hal->ctx);
        return;
    }
    if (commons->store == NULL
        || nesp_commons_url(commons->query, commons->query_len, url, sizeof(url)) == 0
        || !commons->hal->fetch(commons->hal->ctx, url, AGENT, id, &commons->sink)) {
        lock(commons);
        message(commons->album_message, commons->store == NULL ? "THE NESP32 IS OUT OF MEMORY"
                                                               : "THE NESP32 IS BUSY");
        commons->album = NESP_ALBUM_FAILED;
        unlock(commons);
    }
}

static void search(nesp_commons_t *commons, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len < 2 || request->len > 1 + NESP_COMMONS_QUERY_MAX) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    uint8_t id = request->data[0];
    uint8_t len = (uint8_t)(request->len - 1);
    if (!commons->searched || id != commons->search_id || len != commons->query_len
        || memcmp(commons->query, request->data + 1, len) != 0) {
        commons->searched = true;
        commons->search_id = id;
        commons->query_len = len;
        memcpy(commons->query, request->data + 1, len);
        commons->opened = false;
        begin_search(commons);
    }
    lock(commons);
    uint8_t state = commons->album;
    reply->data[0] = state;
    reply->data[1] = id;
    reply->data[2] = state == NESP_ALBUM_READY ? commons->count : 0;
    reply->len = 3;
    if (state == NESP_ALBUM_FAILED && reply->max >= 3 + COLUMNS) {
        memcpy(reply->data + 3, commons->album_message, COLUMNS);
        reply->len = 3 + COLUMNS;
    }
    unlock(commons);
    reply->once = true;             /* the same request again asks how it is going now */
}

static void caption(nesp_commons_t *commons, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len != 2 || reply->max < 3 + COLUMNS) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    uint8_t index = request->data[0];
    uint8_t line = request->data[1];
    lock(commons);
    uint8_t state = commons->album;
    reply->data[1] = index;
    reply->data[2] = line;
    reply->len = 3;
    if (state == NESP_ALBUM_READY && index < commons->count && line < NESP_COMMONS_LINES) {
        memcpy(reply->data + 3, commons->store->lines[index][line], COLUMNS);
        reply->len = 3 + COLUMNS;
    } else {
        state |= NESP_ALBUM_NO_LINE;
    }
    unlock(commons);
    reply->data[0] = state;
    reply->once = true;
}

static void begin_photo(nesp_commons_t *commons, uint8_t index)
{
    char url[URL_MAX];
    bool connected = online(commons);
    lock(commons);
    bool held = commons->album == NESP_ALBUM_READY && index < commons->count;
    if (held) {
        snprintf(url, sizeof(url), "%s", commons->store->urls[index]);
    }
    commons->generation++;
    commons->fetching_photo = true;
    commons->photo_index = index;
    commons->photo = !held ? NESP_PHOTO_IDLE
                   : connected ? NESP_PHOTO_FETCHING : NESP_PHOTO_NO_WIFI;
    uint32_t id = commons->generation;
    unlock(commons);
    if (!held || !connected) {
        commons->hal->fetch_stop(commons->hal->ctx);
        return;
    }
    if (!commons->hal->fetch(commons->hal->ctx, url, AGENT, id, &commons->sink)) {
        lock(commons);
        message(commons->photo_message, "THE NESP32 IS BUSY");
        commons->photo = NESP_PHOTO_FAILED;
        unlock(commons);
    }
}

static void open_photo(nesp_commons_t *commons, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len != 2) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    uint8_t id = request->data[0];
    uint8_t index = request->data[1];
    if (!commons->opened || id != commons->open_id || index != commons->open_index) {
        commons->opened = true;
        commons->open_id = id;
        commons->open_index = index;
        begin_photo(commons, index);
    }
    lock(commons);
    uint8_t state = commons->photo_index == index ? commons->photo : NESP_PHOTO_IDLE;
    reply->data[0] = state;
    reply->data[1] = id;
    reply->data[2] = index;
    reply->len = 3;
    if (state == NESP_PHOTO_FAILED && reply->max >= 3 + COLUMNS) {
        memcpy(reply->data + 3, commons->photo_message, COLUMNS);
        reply->len = 3 + COLUMNS;
    }
    unlock(commons);
    reply->once = true;
}

static void data(nesp_commons_t *commons, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len != 3 || reply->max < 4 + NESP_COMMONS_CHUNK) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    uint8_t index = request->data[0];
    uint32_t offset = (uint32_t)(request->data[1] | request->data[2] << 8);
    lock(commons);
    uint8_t state = commons->photo_index == index ? commons->photo : NESP_PHOTO_IDLE;
    reply->len = 4;
    if (state == NESP_PHOTO_READY && offset < NESP_COMMONS_SIZE) {
        uint32_t count = NESP_COMMONS_SIZE - offset;
        if (count > NESP_COMMONS_CHUNK) {
            count = NESP_COMMONS_CHUNK;
        }
        memcpy(reply->data + 4, commons->store->picture + offset, count);
        reply->len = (uint8_t)(4 + count);
    } else {
        state |= NESP_PHOTO_NO_DATA;
    }
    unlock(commons);
    reply->data[0] = state;
    reply->data[1] = index;
    reply->data[2] = request->data[1];
    reply->data[3] = request->data[2];
    reply->once = true;
}

static void handle(void *ctx, const nesp_request_t *request, nesp_reply_t *reply)
{
    nesp_commons_t *commons = ctx;
    switch (request->op) {
    case NESP_COMMONS_SEARCH:
        search(commons, request, reply);
        break;
    case NESP_COMMONS_CAPTION:
        caption(commons, request, reply);
        break;
    case NESP_COMMONS_OPEN:
        open_photo(commons, request, reply);
        break;
    case NESP_COMMONS_DATA:
        data(commons, request, reply);
        break;
    default:
        reply->status = NESP_ST_NO_OP;
        break;
    }
}

/* A hello has asked for the service: room for what it holds. */
static void activate(void *ctx)
{
    nesp_commons_t *commons = ctx;
    struct nesp_commons_store *store = commons->hal->alloc(commons->hal->ctx, sizeof(*store));
    lock(commons);
    commons->store = store;
    commons->album = NESP_ALBUM_IDLE;
    commons->photo = NESP_PHOTO_IDLE;
    commons->count = 0;
    commons->generation++;
    unlock(commons);
    commons->searched = false;
    commons->opened = false;
}

/* Another ROM is on the console, or this one was reset. */
static void deactivate(void *ctx)
{
    nesp_commons_t *commons = ctx;
    commons->hal->fetch_stop(commons->hal->ctx);
    lock(commons);
    struct nesp_commons_store *store = commons->store;
    commons->store = NULL;
    commons->album = NESP_ALBUM_IDLE;
    commons->photo = NESP_PHOTO_IDLE;
    commons->count = 0;
    commons->generation++;          /* a fetch still on its way adds nothing */
    if (commons->busy) {            /* the fetch's task is in it: it gives it back */
        store = NULL;
    }
    unlock(commons);
    if (store != NULL) {
        commons->hal->release(commons->hal->ctx, store);
    }
}

void nesp_commons_service(nesp_service_t *service, nesp_commons_t *commons, const nesp_hal_t *hal)
{
    memset(commons, 0, sizeof(*commons));
    commons->hal = hal;
    commons->sink.ctx = commons;
    commons->sink.body = body;
    commons->sink.done = done;
    memset(service, 0, sizeof(*service));
    service->id = NESP_SVC_COMMONS;
    service->name = "COMMONS";
    service->activate = activate;
    service->deactivate = deactivate;
    service->handle = handle;
    service->ctx = commons;
}
