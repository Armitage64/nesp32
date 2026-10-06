#include "nesp_text.h"

#include <string.h>

/* --- to ASCII ---------------------------------------------------------------- */

/* U+00C0 to U+00FF and U+0100 to U+017F, a character each; "*" is in words. */
static const char latin_1[] =
    "AAAAAA*CEEEEIIIIDNOOOOOxOUUUUY**aaaaaa*ceeeeiiiidnooooo/ouuuuy*y";
static const char latin_a[] =
    "AaAaAaCcCcCcCcDdDdEeEeEeEeEeGgGgGgGgHhHhIiIiIiIiIi**JjKkkLlLlLlLlLl"
    "NnNnNnnNnOoOoOo**RrRrRrSsSsSsSsTtTtTtUuUuUuUuUuUuWwYyYZzZzZzs";

static const struct {
    uint16_t code;
    const char *text;
} words[] = {
    {0xA0, " "}, {0xA1, "!"}, {0xA2, "c"}, {0xA3, "L"}, {0xA5, "Y"}, {0xA6, "|"},
    {0xA7, "S"}, {0xA8, "\""}, {0xA9, "(c)"}, {0xAA, "a"}, {0xAB, "\""}, {0xAC, "-"},
    {0xAD, ""}, {0xAE, "(R)"}, {0xAF, "-"}, {0xB0, " deg"}, {0xB1, "+/-"}, {0xB2, "2"},
    {0xB3, "3"}, {0xB4, "'"}, {0xB5, "u"}, {0xB6, "P"}, {0xB7, "."}, {0xB8, ","},
    {0xB9, "1"}, {0xBA, "o"}, {0xBB, "\""}, {0xBC, "1/4"}, {0xBD, "1/2"}, {0xBE, "3/4"},
    {0xBF, "?"},
    {0xC6, "AE"}, {0xDE, "Th"}, {0xDF, "ss"}, {0xE6, "ae"}, {0xFE, "th"},
    {0x132, "IJ"}, {0x133, "ij"}, {0x152, "OE"}, {0x153, "oe"},
    {0x2018, "'"}, {0x2019, "'"}, {0x201A, "'"}, {0x201B, "'"}, {0x2032, "'"},
    {0x201C, "\""}, {0x201D, "\""}, {0x201E, "\""}, {0x201F, "\""}, {0x2033, "\""},
    {0x2022, "*"}, {0x2026, "..."}, {0x2028, " "}, {0x2029, " "}, {0x202F, " "},
    {0x2044, "/"}, {0x205F, " "}, {0x2060, ""}, {0x20AC, "EUR"}, {0x2122, "(TM)"},
    {0x2190, "<-"}, {0x2192, "->"}, {0x2212, "-"}, {0x2248, "~"}, {0x2260, "!="},
    {0x2264, "<="}, {0x2265, ">="}, {0x3000, " "}, {0xFEFF, ""},
};

static int one(char value, char *out)
{
    out[0] = value;
    return 1;
}

int nesp_to_ascii(uint32_t code, char *out)
{
    if (code < 0x7F) {
        if (code >= 0x20 || code == 0x0A) {
            return one((char)code, out);
        }
        return code == 0x09 ? one(' ', out) : 0;
    }
    if (code < 0xA0) {
        return 0;
    }
    for (size_t index = 0; index < sizeof(words) / sizeof(words[0]); index++) {
        if (words[index].code == code) {
            size_t length = strlen(words[index].text);
            memcpy(out, words[index].text, length);
            return (int)length;
        }
    }
    if (code >= 0xC0 && code <= 0xFF) {
        return one(latin_1[code - 0xC0], out);
    }
    if (code >= 0x100 && code <= 0x17F) {
        return one(latin_a[code - 0x100], out);
    }
    if (code >= 0x300 && code <= 0x36F) {       /* combining marks */
        return 0;
    }
    if (code >= 0x2000 && code <= 0x200A) {     /* spaces of other widths */
        return one(' ', out);
    }
    if (code >= 0x200B && code <= 0x200F) {     /* zero width; direction marks */
        return 0;
    }
    if (code >= 0x2010 && code <= 0x2015) {     /* hyphens and dashes */
        return one('-', out);
    }
    return -1;
}

/* --- lines ------------------------------------------------------------------- */

/* What Python's bytes.split() and strip() take for a space. */
static bool is_space(uint8_t byte)
{
    return byte == ' ' || (byte >= 0x09 && byte <= 0x0D);
}

void nesp_wrap_init(nesp_wrap_t *wrap, uint8_t width, nesp_line_fn add, void *ctx)
{
    wrap->add = add;
    wrap->ctx = ctx;
    wrap->width = width > NESP_LINE_MAX ? NESP_LINE_MAX : width;
    wrap->blank_last = true;
    wrap->after_heading = false;
    wrap->running = false;
    wrap->line_len = 0;
    wrap->len = 0;
}

static void blank(nesp_wrap_t *wrap)
{
    if (!wrap->blank_last) {
        wrap->add(wrap->ctx, wrap->line, 0, 0);
        wrap->blank_last = true;
    }
}

static void end_line(nesp_wrap_t *wrap, uint8_t flags)
{
    if (wrap->line_len != 0) {
        wrap->add(wrap->ctx, wrap->line, wrap->line_len, flags);
        wrap->line_len = 0;
    }
}

/* A word onto the line being filled. One longer than a line is cut to fit. */
static void add_word(nesp_wrap_t *wrap, const uint8_t *word, size_t len, uint8_t flags)
{
    while (len > wrap->width) {
        end_line(wrap, flags);
        wrap->add(wrap->ctx, word, wrap->width, flags);
        word += wrap->width;
        len -= wrap->width;
    }
    if (wrap->line_len != 0 && wrap->line_len + 1 + len > wrap->width) {
        end_line(wrap, flags);
    }
    if (wrap->line_len != 0) {
        wrap->line[wrap->line_len++] = ' ';
    }
    memcpy(wrap->line + wrap->line_len, word, len);
    wrap->line_len = (uint8_t)(wrap->line_len + len);
}

/* The words of some text onto the line being filled, wrapping at spaces. */
static void add_words(nesp_wrap_t *wrap, const uint8_t *text, size_t len, uint8_t flags)
{
    size_t at = 0;
    while (at < len) {
        while (at < len && is_space(text[at])) {
            at++;
        }
        size_t start = at;
        while (at < len && !is_space(text[at])) {
            at++;
        }
        if (at > start) {
            add_word(wrap, text + start, at - start, flags);
        }
    }
}

static void heading(nesp_wrap_t *wrap, uint8_t *name, size_t len, bool capitals)
{
    if (capitals) {
        for (size_t index = 0; index < len; index++) {
            if (name[index] >= 'a' && name[index] <= 'z') {
                name[index] = (uint8_t)(name[index] - 'a' + 'A');
            }
        }
    }
    blank(wrap);
    add_words(wrap, name, len, NESP_HEADING);
    end_line(wrap, NESP_HEADING);
    wrap->blank_last = false;
    wrap->after_heading = true;
}

void nesp_wrap_title(nesp_wrap_t *wrap, const uint8_t *text, size_t len)
{
    uint8_t name[NESP_TITLE_MAX];
    if (len > sizeof(name)) {
        len = sizeof(name);
    }
    memcpy(name, text, len);
    heading(wrap, name, len, true);
    blank(wrap);
    wrap->after_heading = true;     /* that blank line is the gap */
}

static void end_paragraph(nesp_wrap_t *wrap)
{
    uint8_t *text = wrap->paragraph;
    size_t len = wrap->len;
    wrap->len = 0;
    if (wrap->running) {            /* the last of a long paragraph */
        add_words(wrap, text, len, 0);
        end_line(wrap, 0);
        wrap->running = false;
        return;
    }
    while (len != 0 && is_space(text[len - 1])) {
        len--;
    }
    while (len != 0 && is_space(text[0])) {
        text++;
        len--;
    }
    if (len == 0) {
        return;
    }
    if (len > 4 && text[0] == '=' && text[1] == '=' && text[len - 1] == '='
        && text[len - 2] == '=') {
        size_t level = 0;
        while (level < len && text[level] == '=') {
            level++;
        }
        uint8_t *name = text + level;
        size_t name_len = len - level;
        while (name_len != 0 && name[name_len - 1] == '=') {
            name_len--;
        }
        while (name_len != 0 && is_space(name[name_len - 1])) {
            name_len--;
        }
        while (name_len != 0 && is_space(name[0])) {
            name++;
            name_len--;
        }
        if (name_len != 0) {
            heading(wrap, name, name_len, level == 2);
            return;
        }
    }
    if (!wrap->after_heading) {
        blank(wrap);
    }
    add_words(wrap, text, len, 0);
    end_line(wrap, 0);
    wrap->blank_last = false;
    wrap->after_heading = false;
}

/* The held text is as long as may be held and its paragraph has not ended:
 * lay out its whole words, and keep the one that may not have all come. */
static void run_on(nesp_wrap_t *wrap)
{
    if (!wrap->running) {
        if (!wrap->after_heading) {
            blank(wrap);
        }
        wrap->running = true;
        wrap->blank_last = false;
        wrap->after_heading = false;
    }
    size_t whole = wrap->len;
    while (whole != 0 && !is_space(wrap->paragraph[whole - 1])) {
        whole--;
    }
    if (whole == 0) {               /* one word, thousands of characters long */
        whole = wrap->len;
    }
    add_words(wrap, wrap->paragraph, whole, 0);
    memmove(wrap->paragraph, wrap->paragraph + whole, wrap->len - whole);
    wrap->len -= whole;
}

void nesp_wrap_put(nesp_wrap_t *wrap, const uint8_t *data, size_t len)
{
    for (size_t index = 0; index < len; index++) {
        if (data[index] == '\n') {
            end_paragraph(wrap);
            continue;
        }
        if (wrap->len == NESP_PARAGRAPH) {
            run_on(wrap);
        }
        wrap->paragraph[wrap->len++] = data[index];
    }
}

void nesp_wrap_close(nesp_wrap_t *wrap)
{
    end_paragraph(wrap);
}

/* --- a reply from Wikipedia's API -------------------------------------------- */

enum { FIELD_NONE, FIELD_TITLE, FIELD_EXTRACT };

static const char title_key[] = "\"title\":\"";
static const char extract_key[] = "\"extract\":\"";
#define NO_CODE 0xFFFFFFFFu         /* a character that could not be read */

void nesp_extract_init(nesp_extract_t *extract,
                       void (*on_title)(void *ctx, const uint8_t *text, size_t len),
                       void (*on_text)(void *ctx, const uint8_t *data, size_t len),
                       void *ctx)
{
    memset(extract, 0, sizeof(*extract));
    extract->on_title = on_title;
    extract->on_text = on_text;
    extract->ctx = ctx;
}

/* Bytes of the string that is open, to where they go. */
static void send(nesp_extract_t *extract, const char *data, size_t len)
{
    if (extract->field == FIELD_TITLE) {
        if (len > sizeof(extract->title) - extract->title_len) {
            len = sizeof(extract->title) - extract->title_len;
        }
        memcpy(extract->title + extract->title_len, data, len);
        extract->title_len += len;
    } else {
        extract->on_text(extract->ctx, (const uint8_t *)data, len);
    }
}

static void map(nesp_extract_t *extract, uint32_t code)
{
    char text[4];
    int count = code == NO_CODE ? -1 : nesp_to_ascii(code, text);
    if (count < 0) {
        if (!extract->unknown) {
            send(extract, "?", 1);
            extract->unknown = true;
        }
    } else if (count > 0) {
        send(extract, text, (size_t)count);
        extract->unknown = false;
    }
}

/* A byte of a string that is not part of an escape: UTF-8. */
static void plain(nesp_extract_t *extract, uint8_t byte)
{
    extract->high = 0;
    if (extract->need != 0) {
        if ((byte & 0xC0) == 0x80) {
            extract->code = extract->code << 6 | (byte & 0x3F);
            if (--extract->need == 0) {
                map(extract, extract->code);
            }
            return;
        }
        extract->need = 0;          /* cut short: not UTF-8 */
        map(extract, NO_CODE);
    }
    if (byte < 0x80) {
        char one_byte = (char)byte;
        send(extract, &one_byte, 1);
        extract->unknown = false;
    } else if (byte >= 0xF0) {
        extract->need = 3;
        extract->code = byte & 0x07;
    } else if (byte >= 0xE0) {
        extract->need = 2;
        extract->code = byte & 0x0F;
    } else if (byte >= 0xC0) {
        extract->need = 1;
        extract->code = byte & 0x1F;
    } else {
        map(extract, NO_CODE);      /* a continuation byte with no start */
    }
}

/* A \uXXXX has all come: a character, or half of one. */
static void utf16(nesp_extract_t *extract)
{
    uint16_t high = extract->high;
    uint32_t code = extract->unit;
    extract->high = 0;
    if (extract->bad_hex) {
        code = NO_CODE;
    } else if (code >= 0xD800 && code < 0xDC00) {
        extract->high = extract->unit;
        return;
    } else if (code >= 0xDC00 && code < 0xE000) {
        code = high != 0 ? 0x10000 + ((uint32_t)(high - 0xD800) << 10) + (code - 0xDC00)
                         : NO_CODE;
    }
    map(extract, code);
}

static void close_string(nesp_extract_t *extract)
{
    extract->need = 0;
    extract->high = 0;
    extract->unknown = false;
    if (extract->field == FIELD_TITLE) {
        extract->on_title(extract->ctx, extract->title, extract->title_len);
        extract->title_len = 0;
    } else {
        extract->done = true;
    }
    extract->field = FIELD_NONE;
}

static void in_string(nesp_extract_t *extract, uint8_t byte)
{
    if (extract->escape == 1) {
        if (byte == 'u') {
            extract->escape = 2;
            extract->unit = 0;
            extract->bad_hex = false;
            return;
        }
        extract->escape = 0;
        switch (byte) {
        case 'n': map(extract, 0x0A); break;
        case 't': map(extract, 0x09); break;
        case 'r': map(extract, 0x0D); break;
        case 'b': map(extract, 0x08); break;
        case 'f': map(extract, 0x0C); break;
        default: map(extract, byte); break;
        }
    } else if (extract->escape >= 2) {
        uint8_t digit;
        if (byte >= '0' && byte <= '9') {
            digit = (uint8_t)(byte - '0');
        } else if ((byte | 0x20) >= 'a' && (byte | 0x20) <= 'f') {
            digit = (uint8_t)((byte | 0x20) - 'a' + 10);
        } else {
            digit = 0;
            extract->bad_hex = true;
        }
        extract->unit = (uint16_t)(extract->unit << 4 | digit);
        if (++extract->escape == 6) {
            extract->escape = 0;
            utf16(extract);
        }
    } else if (byte == '"') {
        close_string(extract);
    } else if (byte == '\\') {
        extract->escape = 1;
    } else {
        plain(extract, byte);
    }
}

static bool ends_with(const nesp_extract_t *extract, const char *key)
{
    size_t length = strlen(key);
    return extract->seen_len >= length
           && memcmp(extract->seen + extract->seen_len - length, key, length) == 0;
}

/* Outside both strings: is this the last byte of one of the keys? */
static void seek(nesp_extract_t *extract, uint8_t byte)
{
    if (extract->seen_len == sizeof(extract->seen)) {
        memmove(extract->seen, extract->seen + 1, sizeof(extract->seen) - 1);
        extract->seen_len--;
    }
    extract->seen[extract->seen_len++] = byte;
    if (ends_with(extract, title_key)) {
        extract->field = FIELD_TITLE;
    } else if (ends_with(extract, extract_key)) {
        extract->field = FIELD_EXTRACT;
        extract->found = true;
    } else {
        return;
    }
    extract->seen_len = 0;
    extract->escape = 0;
}

void nesp_extract_feed(nesp_extract_t *extract, const uint8_t *data, size_t len)
{
    for (size_t index = 0; index < len && !extract->done; index++) {
        if (extract->field == FIELD_NONE) {
            seek(extract, data[index]);
        } else {
            in_string(extract, data[index]);
        }
    }
}

/* --- the request -------------------------------------------------------------- */

static const char api[] =
    "https://en.wikipedia.org/w/api.php?action=query&generator=search&gsrlimit=1"
    "&prop=extracts&explaintext=1&format=json&formatversion=2&gsrsearch=";

size_t nesp_wiki_url(const uint8_t *query, size_t len, char *out, size_t max)
{
    static const char hex[] = "0123456789ABCDEF";
    size_t at = sizeof(api) - 1;
    if (max < at + 3 * len + 1) {
        return 0;
    }
    memcpy(out, api, at);
    for (size_t index = 0; index < len; index++) {
        uint8_t byte = query[index];
        bool unreserved = (byte >= 'A' && byte <= 'Z') || (byte >= 'a' && byte <= 'z')
                          || (byte >= '0' && byte <= '9') || byte == '-' || byte == '.'
                          || byte == '_' || byte == '~';
        if (unreserved) {
            out[at++] = (char)byte;
        } else {
            out[at++] = '%';
            out[at++] = hex[byte >> 4];
            out[at++] = hex[byte & 0x0F];
        }
    }
    out[at] = 0;
    return at;
}
