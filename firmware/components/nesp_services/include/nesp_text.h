/* Text for a console: from what the Internet sends to lines of ASCII.
 *
 * Three pieces, each fed in chunks of any size so that nothing is ever held
 * whole, and none of them touching hardware:
 *
 *   nesp_to_ascii     a Unicode character as the nearest ASCII
 *   nesp_extract_t    the title and the text out of a reply from
 *                     Wikipedia's API, decoded as they pass
 *   nesp_wrap_t       plain text laid out in lines of a fixed width, with
 *                     Wikipedia's headings marked
 *
 * They are ports of nes-wiki's wikitext.py and wrap.py, which ran on the
 * Stick under MicroPython, and lay text out the same way.
 */
#ifndef NESP_TEXT_H
#define NESP_TEXT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define NESP_HEADING 0x80           /* set on every character of a heading line */
#define NESP_PARAGRAPH 4096         /* text held while waiting for a paragraph's end */
#define NESP_TITLE_MAX 128
#define NESP_LINE_MAX 40            /* the widest line a wrapper lays out */

/* A Unicode character as ASCII: writes up to 4 bytes to out and returns how
 * many, which may be none; -1 if there is nothing like it. A newline stays;
 * the other controls go. */
int nesp_to_ascii(uint32_t code, char *out);

/* --- lines ------------------------------------------------------------------ */

/* Takes a line as it is laid out: len characters, at most the width, and
 * NESP_HEADING or 0. False once there is no room for more. */
typedef bool (*nesp_line_fn)(void *ctx, const uint8_t *text, size_t len, uint8_t flags);

/* Lays plain text out. The text arrives in pieces; a paragraph is held
 * until its newline and then wrapped at spaces. Wikipedia's plain text
 * marks a heading as a paragraph of its own, "== History ==", with a
 * deeper level for each extra "=".
 *
 *   title           capitals, in the heading colour, then a blank line
 *   == Heading ==   capitals, in the heading colour
 *   === Deeper ===  as written, in the heading colour
 *   paragraphs      a blank line between them, none after a heading
 *
 * A paragraph longer than NESP_PARAGRAPH is laid out as it comes, and is
 * still one paragraph. */
typedef struct {
    nesp_line_fn add;
    void *ctx;
    uint8_t width;
    bool blank_last;                /* nothing yet, or a blank line: none wanted next */
    bool after_heading;
    bool running;                   /* a long paragraph is partly laid out */
    uint8_t line[NESP_LINE_MAX];    /* the line being filled */
    uint8_t line_len;
    size_t len;
    uint8_t paragraph[NESP_PARAGRAPH];
} nesp_wrap_t;

void nesp_wrap_init(nesp_wrap_t *wrap, uint8_t width, nesp_line_fn add, void *ctx);
void nesp_wrap_title(nesp_wrap_t *wrap, const uint8_t *text, size_t len);
/* More of the text: ASCII, with newlines between paragraphs. */
void nesp_wrap_put(nesp_wrap_t *wrap, const uint8_t *data, size_t len);
/* The text has ended; lay out what is held. */
void nesp_wrap_close(nesp_wrap_t *wrap);

/* --- a reply from Wikipedia's API ------------------------------------------- */

/* One request does both jobs: generator=search finds the best page for the
 * words typed, and prop=extracts&explaintext returns it as plain text:
 *
 *   {"batchcomplete":true,"query":{"pages":[{"pageid":1,"ns":0,
 *    "title":"...","index":1,"extract":"..."}]}}
 *
 * A search that finds nothing has no "query" at all. The reply is not
 * parsed. The extractor looks for two strings, the title and the extract,
 * and decodes each as it passes: JSON's escapes, then UTF-8, then
 * nesp_to_ascii. Neither key can turn up inside a string by accident,
 * because a quote inside a JSON string is always escaped. A run of
 * characters with no ASCII likeness becomes one "?".
 *
 * on_title is called once, with the whole title; on_text with the article
 * in pieces. found: the extract began. done: it also ended, and nothing
 * more is wanted; a reply cut short leaves found without done. */
typedef struct {
    void (*on_title)(void *ctx, const uint8_t *text, size_t len);
    void (*on_text)(void *ctx, const uint8_t *data, size_t len);
    void *ctx;
    bool found;
    bool done;
    uint8_t field;                  /* 0 outside both strings */
    uint8_t escape;                 /* 0, 1 after a backslash, 2 to 5 in \uXXXX */
    uint8_t need;                   /* bytes still to come of a UTF-8 character */
    bool unknown;                   /* the last thing sent was a "?" */
    bool bad_hex;
    uint16_t unit;
    uint16_t high;                  /* the first half of a \u surrogate pair */
    uint32_t code;
    uint8_t seen[12];               /* the last bytes outside a string: a key's worth */
    uint8_t seen_len;
    size_t title_len;
    uint8_t title[NESP_TITLE_MAX];
} nesp_extract_t;

void nesp_extract_init(nesp_extract_t *extract,
                       void (*on_title)(void *ctx, const uint8_t *text, size_t len),
                       void (*on_text)(void *ctx, const uint8_t *data, size_t len),
                       void *ctx);
void nesp_extract_feed(nesp_extract_t *extract, const uint8_t *data, size_t len);

/* The address to ask Wikipedia's API for the article a search finds.
 * Returns its length, or 0 if out is too small. out is ended with a 0. */
size_t nesp_wiki_url(const uint8_t *query, size_t len, char *out, size_t max);

#ifdef __cplusplus
}
#endif

#endif
