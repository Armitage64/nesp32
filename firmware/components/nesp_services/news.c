/* Headlines for a console's screen, out of an RSS feed (TUNER's NEWS).
 *
 * The feed is NPR's news (docs/PROTOCOL.md, TUNER): a few dozen <item>s,
 * each with a <title> and a <description> of a sentence or two. Up to
 * NESP_TUNER_NEWS_PAGES of them are laid out as a page each, of
 * NESP_TUNER_NEWS_ROWS lines of NESP_TUNER_NEWS_COLUMNS characters: the
 * headline on up to three lines, a blank line, and as much of the summary
 * as the rest holds, with "..." where either was cut.
 *
 * It is fed in pieces of any size and holds an item's two texts and no
 * more of the feed. A text may be in a CDATA section or have its
 * characters as entities, and either may have tags in it, which go. The
 * console's font is capitals, so everything is made that.
 */
#include <string.h>

#include "nesp_services.h"
#include "nesp_text.h"

enum { TEXT, TAG, CDATA };
enum { F_NONE, F_TITLE, F_SUMMARY };

#define COLUMNS NESP_TUNER_NEWS_COLUMNS
#define ROWS NESP_TUNER_NEWS_ROWS
#define TITLE_ROWS 3

void nesp_news_init(nesp_news_t *news)
{
    memset(news, 0, sizeof(*news));
    memset(news->rows, ' ', sizeof(news->rows));
}

/* --- an item's text, made plain ------------------------------------------------ */

static const struct {
    const char *name;
    uint32_t code;
} entities[] = {
    {"amp", '&'}, {"lt", '<'}, {"gt", '>'}, {"quot", '"'}, {"apos", '\''}, {"nbsp", ' '},
    {"mdash", 0x2014}, {"ndash", 0x2013}, {"rsquo", 0x2019}, {"lsquo", 0x2018},
    {"rdquo", 0x201D}, {"ldquo", 0x201C}, {"hellip", 0x2026},
};

/* The character at text[*at], which may be an entity or several bytes of
 * UTF-8, and *at moved past it. *literal says it stood for itself. */
static uint32_t next_char(const uint8_t *text, size_t len, size_t *at, bool *literal)
{
    uint8_t byte = text[(*at)++];
    *literal = true;
    if (byte == '&') {
        size_t end = *at;
        while (end < len && end - *at < 10 && text[end] != ';') {
            end++;
        }
        if (end < len && text[end] == ';') {
            const uint8_t *name = text + *at;
            size_t size = end - *at;
            uint32_t code = 0;
            bool found = false;
            if (size > 1 && name[0] == '#') {
                bool hex = name[1] == 'x' || name[1] == 'X';
                found = size > (hex ? 2u : 1u);
                for (size_t index = hex ? 2 : 1; index < size && found; index++) {
                    uint8_t digit = name[index];
                    if (digit >= '0' && digit <= '9') {
                        code = code * (hex ? 16u : 10u) + (uint32_t)(digit - '0');
                    } else if (hex && (digit | 0x20) >= 'a' && (digit | 0x20) <= 'f') {
                        code = code * 16u + (uint32_t)((digit | 0x20) - 'a' + 10);
                    } else {
                        found = false;
                    }
                }
            } else {
                for (size_t index = 0; index < sizeof(entities) / sizeof(entities[0]); index++) {
                    if (strlen(entities[index].name) == size
                        && memcmp(entities[index].name, name, size) == 0) {
                        code = entities[index].code;
                        found = true;
                    }
                }
            }
            if (!found && size > 1) {
                /* An accented letter, by its name: the letter. */
                static const char *const marks[] = {"acute", "grave", "circ", "uml", "tilde",
                                                    "cedil", "ring", "slash", "caron"};
                for (size_t index = 0; index < sizeof(marks) / sizeof(marks[0]); index++) {
                    if (strlen(marks[index]) == size - 1
                        && memcmp(marks[index], name + 1, size - 1) == 0) {
                        code = name[0];
                        found = true;
                    }
                }
            }
            if (found) {
                *at = end + 1;
                *literal = false;
                return code;
            }
        }
        return '&';
    }
    if (byte < 0x80) {
        return byte;
    }
    int more = byte >= 0xF0 ? 3 : byte >= 0xE0 ? 2 : byte >= 0xC0 ? 1 : -1;
    if (more < 0) {
        return 0xFFFD;
    }
    uint32_t code = byte & (0x3Fu >> more);
    while (more-- > 0 && *at < len && (text[*at] & 0xC0) == 0x80) {
        code = code << 6 | (text[(*at)++] & 0x3Fu);
    }
    return code;
}

/* A text in place as the console can show it: its entities and UTF-8 as
 * capitals of ASCII, its tags gone, and a space where there was any run of
 * spaces. Returns its new length. */
static size_t make_plain(uint8_t *text, size_t len)
{
    size_t at = 0;
    size_t out = 0;
    bool spaced = true;             /* none at its start */
    while (at < len) {
        bool literal;
        uint32_t code = next_char(text, len, &at, &literal);
        if (code == '<' && literal) {
            while (at < len && text[at] != '>') {
                at++;
            }
            at += at < len;
            code = ' ';
        }
        char mapped[4];
        int count = nesp_to_ascii(code, mapped);
        for (int index = 0; index < count; index++) {
            uint8_t ch = (uint8_t)mapped[index];
            if (ch >= 'a' && ch <= 'z') {
                ch = (uint8_t)(ch - 'a' + 'A');
            } else if (ch == '`') {
                ch = '\'';
            } else if (ch == '{' || ch == '}') {
                ch = ch == '{' ? '(' : ')';
            } else if (ch == '|') {
                ch = '/';
            } else if (ch == '~') {
                ch = '-';
            }
            if (ch <= ' ' || ch > '_') {
                ch = ' ';
            }
            if (ch == ' ' && spaced) {
                continue;
            }
            spaced = ch == ' ';
            /* What is written never passes what is read: an entity is
             * longer than what it stands for, and so is UTF-8, but for the
             * few characters that become a word. Those may lose their end. */
            if (out < at) {
                text[out++] = ch;
            }
        }
    }
    while (out != 0 && text[out - 1] == ' ') {
        out--;
    }
    return out;
}

/* Lay a text out on up to `rows` lines, words whole where they fit a line.
 * Returns the lines used; a text cut short ends in "...". */
static uint8_t lay_out(const uint8_t *text, size_t len, uint8_t (*lines)[COLUMNS], uint8_t rows)
{
    uint8_t row = 0;
    uint8_t column = 0;
    size_t at = 0;
    while (at < len) {
        size_t end = at;
        while (end < len && text[end] != ' ') {
            end++;
        }
        size_t word = end - at;
        if (column != 0 && column + 1 + word > COLUMNS) {
            row++;
            column = 0;
        }
        if (row == rows) {
            break;
        }
        if (column != 0) {
            column++;
        }
        if (word > COLUMNS) {
            word = COLUMNS;         /* a word wider than a line is broken */
        }
        memcpy(lines[row] + column, text + at, word);
        column = (uint8_t)(column + word);
        at += word;
        at += at < len && text[at] == ' ';
    }
    if (at < len && rows != 0) {
        /* Cut: the last line ends in "...", after the last of its words
         * that leaves room for them. */
        uint8_t *last = lines[rows - 1];
        size_t used = COLUMNS;
        while (used != 0 && last[used - 1] == ' ') {
            used--;
        }
        if (used > COLUMNS - 3) {
            size_t whole = COLUMNS - 3;
            while (whole != 0 && last[whole] != ' ') {
                whole--;
            }
            while (whole != 0 && last[whole - 1] == ' ') {
                whole--;
            }
            used = whole != 0 ? whole : COLUMNS - 3;
        }
        memcpy(last + used, "...", 3);
        memset(last + used + 3, ' ', COLUMNS - used - 3);
        return rows;
    }
    return (uint8_t)(row + (column != 0));
}

/* An item has ended: a page of it, if it has a headline and there is room. */
static void end_item(nesp_news_t *news)
{
    if (news->count < NESP_TUNER_NEWS_PAGES) {
        size_t title = make_plain(news->title, news->title_len);
        size_t summary = make_plain(news->summary, news->summary_len);
        if (title != 0) {
            uint8_t (*page)[COLUMNS] = news->rows[news->count];
            uint8_t used = lay_out(news->title, title, page, TITLE_ROWS);
            lay_out(news->summary, summary, page + used + 1, (uint8_t)(ROWS - used - 1));
            news->count++;
        }
    }
    news->title_len = news->summary_len = 0;
}

/* --- the feed ---------------------------------------------------------------- */

static void keep(nesp_news_t *news, uint8_t byte)
{
    if (news->field == F_TITLE && news->title_len < sizeof(news->title)) {
        news->title[news->title_len++] = byte;
    } else if (news->field == F_SUMMARY && news->summary_len < sizeof(news->summary)) {
        news->summary[news->summary_len++] = byte;
    }
}

static bool named(const nesp_news_t *news, const char *name)
{
    size_t len = strlen(name);
    return news->tag_len >= len && memcmp(news->tag, name, len) == 0
           && (news->tag_len == len || news->tag[len] == ' ' || news->tag[len] == '/');
}

static void end_tag(nesp_news_t *news)
{
    if (named(news, "item")) {
        news->in_item = true;
        news->title_len = news->summary_len = 0;
    } else if (named(news, "/item")) {
        if (news->in_item) {
            end_item(news);
        }
        news->in_item = false;
        news->field = F_NONE;
    } else if (named(news, "title")) {
        news->field = news->in_item ? F_TITLE : F_NONE;
    } else if (named(news, "description")) {
        news->field = news->in_item ? F_SUMMARY : F_NONE;
    } else if (named(news, "/title") || named(news, "/description")) {
        news->field = F_NONE;
    } else {
        keep(news, ' ');            /* a tag in a text, where a space might have been */
    }
}

void nesp_news_feed(nesp_news_t *news, const uint8_t *data, size_t len)
{
    for (size_t index = 0; index < len; index++) {
        uint8_t byte = data[index];
        switch (news->mode) {
        case TEXT:
            if (byte == '<') {
                news->mode = TAG;
                news->tag_len = 0;
            } else {
                keep(news, byte);
            }
            break;
        case TAG:
            if (byte == '>') {
                news->mode = TEXT;
                end_tag(news);
                break;
            }
            if (news->tag_len < sizeof(news->tag)) {
                news->tag[news->tag_len++] = byte;
            }
            if (news->tag_len == 8 && memcmp(news->tag, "![CDATA[", 8) == 0) {
                news->mode = CDATA;
                news->closing = 0;
            }
            break;
        default:
            /* To "]]>". The brackets are kept back until it is known that
             * they are not its end. */
            if (byte == ']') {
                if (news->closing == 2) {
                    keep(news, ']');
                } else {
                    news->closing++;
                }
            } else if (byte == '>' && news->closing == 2) {
                news->mode = TEXT;
            } else {
                while (news->closing != 0) {
                    keep(news, ']');
                    news->closing--;
                }
                keep(news, byte);
            }
            break;
        }
    }
}
