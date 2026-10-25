/* What a station is playing, as a page for a console's screen (TUNER's
 * second mode).
 *
 * A station's stream may carry titles (ICY: tuner.c takes them out of it),
 * of whatever the station likes: most say "ARTIST - SONG", some the
 * programme, some only the station's name. The title is laid out as a page
 * of NESP_TUNER_NEWS_ROWS lines of NESP_TUNER_NEWS_COLUMNS characters:
 * NOW PLAYING at the top, a blank line, and then an artist and a song on
 * up to three lines each, a blank line between, or a title with no " - "
 * on the seven, with "..." where either was cut.
 *
 * A title may have entities, or UTF-8; the console's font is capitals, so
 * everything is made that.
 */
#include <string.h>

#include "nesp_services.h"
#include "nesp_text.h"

#define COLUMNS NESP_TUNER_NEWS_COLUMNS
#define ROWS NESP_TUNER_NEWS_ROWS
#define HEADING "NOW PLAYING"
#define FIRST_ROW 2             /* under the heading and a blank line */
#define PART_ROWS 3             /* an artist's, and a song's */

/* --- a text, made plain ------------------------------------------------ */

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

/* Trailing separators off a part: "BULLSEYE WITH JESSE THORN-" is a
 * station's title for its programme. */
static size_t trimmed(const uint8_t *text, size_t len)
{
    while (len != 0 && (text[len - 1] == ' ' || text[len - 1] == '-')) {
        len--;
    }
    return len;
}

void nesp_news_title(nesp_page_t page, uint8_t *title, size_t len)
{
    memset(page, ' ', sizeof(nesp_page_t));
    memcpy(page[0], HEADING, sizeof(HEADING) - 1);
    len = trimmed(title, make_plain(title, len));
    size_t split = 0;
    while (split + 3 <= len && memcmp(title + split, " - ", 3) != 0) {
        split++;
    }
    if (split + 3 > len || split == 0) {
        lay_out(title, len, page + FIRST_ROW, ROWS - FIRST_ROW);
        return;
    }
    size_t song = split + 3;
    lay_out(title, trimmed(title, split), page + FIRST_ROW, PART_ROWS);
    lay_out(title + song, trimmed(title + song, len - song), page + FIRST_ROW + PART_ROWS + 1,
            PART_ROWS);
}
