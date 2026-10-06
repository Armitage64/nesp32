/* WIKI: a search typed on the console, and the article it finds, a line at
 * a time (docs/PROTOCOL.md). NESpedia's service.
 *
 * The console never holds the article; it has 2 KB of memory. The Stick
 * lays the text out in lines of exactly NESP_WIKI_COLUMNS characters, and
 * the console asks for them by number.
 *
 * SEARCH is both "search for this" and "how is it going". The console gives
 * each search an id and sends the same request again until the search has
 * ended one way or another. A search whose id or words are new starts a
 * fetch; the same one again is only answered with the state. So a lost
 * request or reply needs no handling of its own, and an old article is
 * never taken for the answer to a new search.
 *
 * An article is offered before it has all arrived: once NESP_WIKI_EARLY
 * lines are laid out the state is READY with MORE, and the total is the
 * lines so far. Lines already laid out never change, so they are served
 * while the rest comes in.
 *
 * Two tasks meet here. The link's task runs handle(), which only reads and
 * sets what is held. The fetch's task runs body() and done() as the reply
 * arrives, and does all the work on the text. What both touch is the
 * article and its state, under the hal's lock for a few instructions at a
 * time. `generation` is which fetch the article belongs to: a new search
 * takes a new one, and from then on whatever an older fetch tries to add
 * is refused.
 */
#include <string.h>

#include "nesp_services.h"

#define COLUMNS NESP_WIKI_COLUMNS
#define AGENT "NESpedia/0.2 (a Wikipedia reader for the NES, on an M5Stack Stick; nesp32)"

/* The article's memory, biggest first: the first there is room for. The
 * biggest is about 9000 lines. */
static const uint32_t sizes[] = {256 * 1024, 128 * 1024, 64 * 1024, 32 * 1024};

/* Laid out after the article: the text is its contributors', and its
 * licence asks that this be said. */
static const char *const source[] = {"From Wikipedia, the free", "encyclopedia. CC BY-SA 4.0."};
static const char cut_text[] = "[ARTICLE CUT SHORT HERE]";

static void lock(nesp_wiki_t *wiki)
{
    wiki->hal->lock(wiki->hal->ctx);
}

static void unlock(nesp_wiki_t *wiki)
{
    wiki->hal->unlock(wiki->hal->ctx);
}

/* --- the fetch's task ---------------------------------------------------------- */

/* A line onto the end of the article, if it is still this fetch's. The
 * last line there is room for is kept for cut_text, so an article that
 * does not fit says so where it stops. */
static bool add_line(nesp_wiki_t *wiki, const uint8_t *text, size_t len, uint8_t flags)
{
    bool room = false;
    if (len > COLUMNS) {
        len = COLUMNS;
    }
    lock(wiki);
    if (wiki->generation == wiki->parsing && !wiki->full && wiki->lines != NULL) {
        if (wiki->count + 1 >= wiki->capacity) {
            wiki->full = true;
            text = (const uint8_t *)cut_text;
            len = sizeof(cut_text) - 1;
            flags = NESP_HEADING;
        }
        uint8_t *line = wiki->lines + (size_t)wiki->count * COLUMNS;
        for (size_t index = 0; index < COLUMNS; index++) {
            line[index] = index < len ? (uint8_t)(text[index] | flags) : ' ';
        }
        wiki->count++;              /* last: a line is whole before it is offered */
        room = !wiki->full;
    }
    unlock(wiki);
    return room;
}

static bool wrap_line(void *ctx, const uint8_t *text, size_t len, uint8_t flags)
{
    return add_line(ctx, text, len, flags);
}

static void on_title(void *ctx, const uint8_t *text, size_t len)
{
    nesp_wiki_t *wiki = ctx;
    nesp_wrap_title(&wiki->wrap, text, len);
}

static void on_text(void *ctx, const uint8_t *data, size_t len)
{
    nesp_wiki_t *wiki = ctx;
    nesp_wrap_put(&wiki->wrap, data, len);
}

static bool current(nesp_wiki_t *wiki, uint32_t id)
{
    lock(wiki);
    bool same = wiki->generation == id;
    unlock(wiki);
    return same;
}

static void set_state(nesp_wiki_t *wiki, uint32_t id, uint8_t state)
{
    lock(wiki);
    if (wiki->generation == id) {
        wiki->state = state;
    }
    unlock(wiki);
}

/* The text has ended, or the room for it has: what is held is the article. */
static void finish(nesp_wiki_t *wiki, uint32_t id)
{
    nesp_wrap_close(&wiki->wrap);
    add_line(wiki, NULL, 0, 0);
    for (size_t index = 0; index < sizeof(source) / sizeof(source[0]); index++) {
        add_line(wiki, (const uint8_t *)source[index], strlen(source[index]), 0);
    }
    wiki->finished = true;
    set_state(wiki, id, NESP_ARTICLE_READY);
}

static bool body(void *ctx, uint32_t id, const uint8_t *data, size_t len)
{
    nesp_wiki_t *wiki = ctx;
    if (!current(wiki, id)) {
        return false;
    }
    if (wiki->parsing != id) {      /* the first of a new reply */
        wiki->parsing = id;
        wiki->finished = false;
        nesp_extract_init(&wiki->extract, on_title, on_text, wiki);
        nesp_wrap_init(&wiki->wrap, COLUMNS, wrap_line, wiki);
    }
    if (wiki->finished) {
        return false;
    }
    nesp_extract_feed(&wiki->extract, data, len);
    lock(wiki);
    bool full = wiki->full;
    unlock(wiki);
    if (wiki->extract.done || full) {
        finish(wiki, id);
        return false;
    }
    return current(wiki, id);
}

/* A message for the console's screen: a line's width, centered, capitals
 * as the console's own messages are. */
static void set_message(nesp_wiki_t *wiki, const char *text)
{
    size_t len = strlen(text);
    if (len > COLUMNS) {
        len = COLUMNS;
    }
    size_t left = (COLUMNS - len) / 2;
    memset(wiki->message, ' ', COLUMNS);
    for (size_t index = 0; index < len; index++) {
        char letter = text[index];
        if (letter >= 'a' && letter <= 'z') {
            letter = (char)(letter - 'a' + 'A');
        }
        wiki->message[left + index] = (uint8_t)letter;
    }
}

static void done(void *ctx, uint32_t id, bool ok, const char *why)
{
    nesp_wiki_t *wiki = ctx;
    if (!current(wiki, id)) {
        return;
    }
    bool began = wiki->parsing == id;
    if (began && wiki->finished) {
        return;
    }
    lock(wiki);
    uint32_t count = wiki->count;
    unlock(wiki);
    if (began && wiki->extract.found && (ok || count >= NESP_WIKI_EARLY)) {
        /* It ended before its text did. What is held can still be read,
         * if the reply said it was whole or there is a screenful. */
        finish(wiki, id);
    } else if (ok) {
        set_state(wiki, id, NESP_ARTICLE_NOT_FOUND);
    } else {
        lock(wiki);
        if (wiki->generation == id) {
            wiki->count = 0;
            set_message(wiki, why != NULL && why[0] != 0 ? why : "THE SEARCH FAILED");
            wiki->state = NESP_ARTICLE_ERROR;
        }
        unlock(wiki);
    }
}

/* --- the link's task ----------------------------------------------------------- */

/* The state and the total as the console is told them. Called locked. */
static uint8_t offer(const nesp_wiki_t *wiki, uint32_t *total)
{
    *total = 0;
    if (wiki->state == NESP_ARTICLE_READY) {
        *total = wiki->count;
        return NESP_ARTICLE_READY;
    }
    if (wiki->state == NESP_ARTICLE_FETCHING && wiki->count >= NESP_WIKI_EARLY) {
        *total = wiki->count;
        return NESP_ARTICLE_READY | NESP_ARTICLE_MORE;
    }
    return wiki->state;
}

static void begin(nesp_wiki_t *wiki)
{
    char url[256];
    nesp_wifi_t wifi;
    memset(&wifi, 0, sizeof(wifi));
    wiki->hal->wifi(wiki->hal->ctx, &wifi);
    bool online = wifi.state == NESP_WIFI_JOINED;

    lock(wiki);
    wiki->generation++;             /* whatever was being fetched is no longer wanted */
    wiki->count = 0;
    wiki->full = false;
    wiki->state = online ? NESP_ARTICLE_FETCHING : NESP_ARTICLE_NO_WIFI;
    uint32_t id = wiki->generation;
    unlock(wiki);
    if (!online) {
        wiki->hal->fetch_stop(wiki->hal->ctx);
        return;
    }
    if (wiki->lines == NULL
        || nesp_wiki_url(wiki->query, wiki->query_len, url, sizeof(url)) == 0
        || !wiki->hal->fetch(wiki->hal->ctx, url, AGENT, id, &wiki->sink)) {
        lock(wiki);
        set_message(wiki, wiki->lines == NULL ? "THE STICK IS OUT OF MEMORY"
                                              : "THE STICK IS BUSY");
        wiki->state = NESP_ARTICLE_ERROR;
        unlock(wiki);
    }
}

static void search(nesp_wiki_t *wiki, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len < 2 || request->len > 1 + NESP_WIKI_QUERY_MAX) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    uint8_t id = request->data[0];
    uint8_t len = (uint8_t)(request->len - 1);
    if (!wiki->searched || id != wiki->search_id || len != wiki->query_len
        || memcmp(wiki->query, request->data + 1, len) != 0) {
        wiki->searched = true;
        wiki->search_id = id;
        wiki->query_len = len;
        memcpy(wiki->query, request->data + 1, len);
        begin(wiki);
    }
    uint32_t total;
    lock(wiki);
    uint8_t state = offer(wiki, &total);
    if (state == NESP_ARTICLE_ERROR && reply->max >= 4 + COLUMNS) {
        memcpy(reply->data + 4, wiki->message, COLUMNS);
        reply->len = 4 + COLUMNS;
    } else {
        reply->len = 4;
    }
    unlock(wiki);
    reply->data[0] = state;
    reply->data[1] = id;
    reply->data[2] = (uint8_t)total;
    reply->data[3] = (uint8_t)(total >> 8);
    reply->once = true;             /* the same request again asks how it is going now */
}

static void line(nesp_wiki_t *wiki, const nesp_request_t *request, nesp_reply_t *reply)
{
    if (request->len != 2 || reply->max < 5 + COLUMNS) {
        reply->status = NESP_ST_BAD_ARG;
        return;
    }
    uint32_t number = (uint32_t)(request->data[0] | request->data[1] << 8);
    uint32_t total;
    lock(wiki);
    uint8_t state = offer(wiki, &total);
    if (number < total) {
        memcpy(reply->data + 5, wiki->lines + (size_t)number * COLUMNS, COLUMNS);
        reply->len = 5 + COLUMNS;
    } else {
        state |= NESP_ARTICLE_NO_LINE;
        reply->len = 5;
    }
    unlock(wiki);
    reply->data[0] = state;
    reply->data[1] = request->data[0];
    reply->data[2] = request->data[1];
    reply->data[3] = (uint8_t)total;
    reply->data[4] = (uint8_t)(total >> 8);
    reply->once = true;             /* a line not held yet may be by the next time */
}

static void handle(void *ctx, const nesp_request_t *request, nesp_reply_t *reply)
{
    nesp_wiki_t *wiki = ctx;
    switch (request->op) {
    case NESP_WIKI_SEARCH:
        search(wiki, request, reply);
        break;
    case NESP_WIKI_LINE:
        line(wiki, request, reply);
        break;
    default:
        reply->status = NESP_ST_NO_OP;
        break;
    }
}

/* A hello has asked for the service: room for an article. */
static void activate(void *ctx)
{
    nesp_wiki_t *wiki = ctx;
    uint8_t *lines = NULL;
    uint32_t capacity = 0;
    for (size_t index = 0; index < sizeof(sizes) / sizeof(sizes[0]) && lines == NULL; index++) {
        lines = wiki->hal->alloc(wiki->hal->ctx, sizes[index]);
        capacity = sizes[index] / COLUMNS;
    }
    lock(wiki);
    wiki->lines = lines;
    wiki->capacity = lines != NULL ? capacity : 0;
    wiki->count = 0;
    wiki->full = false;
    wiki->state = NESP_ARTICLE_IDLE;
    wiki->generation++;
    unlock(wiki);
    wiki->searched = false;
}

/* Another ROM is on the console, or this one was reset. */
static void deactivate(void *ctx)
{
    nesp_wiki_t *wiki = ctx;
    wiki->hal->fetch_stop(wiki->hal->ctx);
    lock(wiki);
    uint8_t *lines = wiki->lines;
    wiki->lines = NULL;
    wiki->capacity = 0;
    wiki->count = 0;
    wiki->state = NESP_ARTICLE_IDLE;
    wiki->generation++;             /* a fetch still on its way adds nothing */
    unlock(wiki);
    if (lines != NULL) {
        wiki->hal->release(wiki->hal->ctx, lines);
    }
}

void nesp_wiki_service(nesp_service_t *service, nesp_wiki_t *wiki, const nesp_hal_t *hal)
{
    memset(wiki, 0, sizeof(*wiki));
    wiki->hal = hal;
    wiki->sink.ctx = wiki;
    wiki->sink.body = body;
    wiki->sink.done = done;
    memset(service, 0, sizeof(*service));
    service->id = NESP_SVC_WIKI;
    service->name = "WIKI";
    service->activate = activate;
    service->deactivate = deactivate;
    service->handle = handle;
    service->ctx = wiki;
}
