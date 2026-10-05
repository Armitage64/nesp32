"""From a search to plain ASCII text, without holding the reply in memory.

One request to Wikipedia's API does both jobs: generator=search finds the
best page for the words typed, and prop=extracts&explaintext returns that
page as plain text, with the markup, tables and references already gone:

    {"batchcomplete":true,"continue":{...},"query":{"pages":[{"pageid":1,
     "ns":0,"title":"...","index":1,"extract":"..."}]}}

A search that finds nothing has no "query" at all.

The extract of a long article is some hundreds of KB, more than a Stick
should hold twice, so Extractor does not parse the JSON. It is fed the body
in chunks of any size and looks for two strings, the page's title and its
extract, decoding each as it passes: JSON's escapes, then UTF-8, then
to_ascii, since the console's tile set is ASCII. Neither key can turn up
inside a string by accident, because a quote inside a JSON string is always
escaped.

Wikipedia sends the text as raw UTF-8 today, but a \\uXXXX escape is as
valid, so both are read.
"""

from neswiki.wrap import Wrapper

HOST = "en.wikipedia.org"
API_PATH = ("/w/api.php?action=query&generator=search&gsrlimit=1"
            "&prop=extracts&explaintext=1&format=json&formatversion=2&gsrsearch=")
# Wikimedia asks every client to say what it is.
USER_AGENT = "NESpedia/0.1 (a Wikipedia reader for the NES, on an M5Stack Stick)"

# Laid out after the article: the text is its contributors', and its licence
# asks that this be said.
SOURCE = (b"From Wikipedia, the free", b"encyclopedia. CC BY-SA 4.0.")

_UNRESERVED = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"


def api_path(query):
    """The request path for a search."""
    out = []
    for byte in query.encode("utf-8"):
        out.append(chr(byte) if byte in _UNRESERVED else "%%%02X" % byte)
    return API_PATH + "".join(out)


# --- to ASCII ------------------------------------------------------------------

# U+00C0 to U+00FF and U+0100 to U+017F, a character each; "*" is in _WORDS.
_LATIN_1 = "AAAAAA*CEEEEIIIIDNOOOOOxOUUUUY**aaaaaa*ceeeeiiiidnooooo/ouuuuy*y"
_LATIN_A = ("AaAaAaCcCcCcCcDdDdEeEeEeEeEeGgGgGgGgHhHhIiIiIiIiIi**JjKkkLlLlLlLlLl"
            "NnNnNnnNnOoOoOo**RrRrRrSsSsSsSsTtTtTtUuUuUuUuUuUuWwYyYZzZzZzs")
_WORDS = {
    0xA0: b" ", 0xA1: b"!", 0xA2: b"c", 0xA3: b"L", 0xA5: b"Y", 0xA6: b"|",
    0xA7: b"S", 0xA8: b'"', 0xA9: b"(c)", 0xAA: b"a", 0xAB: b'"', 0xAC: b"-",
    0xAD: b"", 0xAE: b"(R)", 0xAF: b"-", 0xB0: b" deg", 0xB1: b"+/-", 0xB2: b"2",
    0xB3: b"3", 0xB4: b"'", 0xB5: b"u", 0xB6: b"P", 0xB7: b".", 0xB8: b",",
    0xB9: b"1", 0xBA: b"o", 0xBB: b'"', 0xBC: b"1/4", 0xBD: b"1/2", 0xBE: b"3/4",
    0xBF: b"?",
    0xC6: b"AE", 0xDE: b"Th", 0xDF: b"ss", 0xE6: b"ae", 0xFE: b"th",
    0x132: b"IJ", 0x133: b"ij", 0x152: b"OE", 0x153: b"oe",
    0x2018: b"'", 0x2019: b"'", 0x201A: b"'", 0x201B: b"'", 0x2032: b"'",
    0x201C: b'"', 0x201D: b'"', 0x201E: b'"', 0x201F: b'"', 0x2033: b'"',
    0x2022: b"*", 0x2026: b"...", 0x2028: b" ", 0x2029: b" ", 0x202F: b" ",
    0x2044: b"/", 0x205F: b" ", 0x2060: b"", 0x20AC: b"EUR", 0x2122: b"(TM)",
    0x2190: b"<-", 0x2192: b"->", 0x2212: b"-", 0x2248: b"~", 0x2260: b"!=",
    0x2264: b"<=", 0x2265: b">=", 0x3000: b" ", 0xFEFF: b"",
}


def to_ascii(code):
    """A Unicode character as ASCII bytes, maybe none; None if there is
    nothing like it. A newline stays; the other controls go."""
    if code < 0x7F:
        if code >= 0x20 or code == 0x0A:
            return bytes((code,))
        return b" " if code == 0x09 else b""
    if code < 0xA0:
        return b""
    if code in _WORDS:
        return _WORDS[code]
    if 0xC0 <= code <= 0xFF:
        return _LATIN_1[code - 0xC0].encode()
    if 0x100 <= code <= 0x17F:
        return _LATIN_A[code - 0x100].encode()
    if 0x300 <= code <= 0x36F:          # combining marks
        return b""
    if 0x2000 <= code <= 0x200A:        # spaces of other widths
        return b" "
    if 0x200B <= code <= 0x200F:        # zero width; direction marks
        return b""
    if 0x2010 <= code <= 0x2015:        # hyphens and dashes
        return b"-"
    return None


# --- the reply -----------------------------------------------------------------

_TITLE, _EXTRACT = 1, 2
_KEYS = ((b'"title":"', _TITLE), (b'"extract":"', _EXTRACT))
_KEY_TAIL = 10                  # a key may be split across chunks: its length less one
_ESCAPES = {0x6E: 0x0A, 0x74: 0x09, 0x72: 0x0D, 0x62: 0x08, 0x66: 0x0C}
_UNKNOWN = 0x3F                 # "?"


class Extractor:
    """feed() it the reply's body. on_title(bytes) is called once with the
    page's title, then on_text(bytes) with the article in pieces, all ASCII.
    A run of characters with no ASCII likeness becomes one "?".

    found: the extract began. done: it also ended, and nothing more is
    wanted; a reply cut short leaves found without done.
    """

    def __init__(self, on_title, on_text):
        self.on_title = on_title
        self.on_text = on_text
        self.found = False
        self.done = False
        self._field = None
        self._tail = b""
        self._title = bytearray()
        self._need = 0          # bytes still to come of a UTF-8 character
        self._code = 0
        self._high = 0          # the first half of a \\u surrogate pair
        self._unknown = False   # the last thing sent was a "?"

    def feed(self, data):
        if self.done:
            return
        if self._tail:
            data = self._tail + data
            self._tail = b""
        position, size = 0, len(data)
        while position < size and not self.done:
            if self._field is None:
                position = self._seek(data, position)
            else:
                position = self._string(data, position)

    def _seek(self, data, position):
        found, after = -1, 0
        for key, field in _KEYS:
            at = data.find(key, position)
            if at >= 0 and (found < 0 or at < found):
                found, after = at, at + len(key)
                self._field = field
        if found < 0:
            self._tail = bytes(data[max(position, len(data) - _KEY_TAIL):])
            return len(data)
        if self._field == _EXTRACT:
            self.found = True
        return after

    def _string(self, data, position):
        size = len(data)
        end = size
        quote = data.find(b'"', position)
        if quote >= 0:
            end = quote
        slash = data.find(b"\\", position, end)
        if slash >= 0:
            end = slash
        if end > position:
            self._plain(data[position:end])
        if end == size:
            return size
        if data[end] == 0x22:
            self._close()
            return end + 1
        # An escape. Keep it for the next chunk if not all of it is here.
        if end + 1 >= size:
            self._tail = bytes(data[end:])
            return size
        char = data[end + 1]
        if char != 0x75:
            self._send_code(_ESCAPES.get(char, char))
            return end + 2
        if end + 6 > size:
            self._tail = bytes(data[end:])
            return size
        try:
            unit = int(str(data[end + 2:end + 6], "ascii"), 16)
        except ValueError:
            unit = None
        self._utf16(unit)
        return end + 6

    def _utf16(self, unit):
        high, self._high = self._high, 0
        if unit is not None and 0xD800 <= unit < 0xDC00:
            self._high = unit
            return
        if unit is not None and 0xDC00 <= unit < 0xE000:
            unit = 0x10000 + ((high - 0xD800) << 10) + unit - 0xDC00 if high else None
        self._send_code(unit)

    def _send_code(self, code):
        out = bytearray()
        self._map(code, out)
        if out:
            self._send(bytes(out))

    def _plain(self, run):
        """Bytes of a string with no escapes among them: UTF-8."""
        self._high = 0
        if not self._need and max(run) < 0x80:
            self._unknown = False
            self._send(run)
            return
        out = bytearray()
        for byte in run:
            if self._need:
                if byte & 0xC0 == 0x80:
                    self._code = self._code << 6 | byte & 0x3F
                    self._need -= 1
                    if not self._need:
                        self._map(self._code, out)
                    continue
                self._need = 0          # cut short: not UTF-8
                self._map(None, out)
            if byte < 0x80:
                out.append(byte)
                self._unknown = False
            elif byte >= 0xF0:
                self._need, self._code = 3, byte & 0x07
            elif byte >= 0xE0:
                self._need, self._code = 2, byte & 0x0F
            elif byte >= 0xC0:
                self._need, self._code = 1, byte & 0x1F
            else:
                self._map(None, out)    # a continuation byte with no start
        if out:
            self._send(bytes(out))

    def _map(self, code, out):
        text = to_ascii(code) if code is not None else None
        if text is None:
            if not self._unknown:
                out.append(_UNKNOWN)
                self._unknown = True
        elif text:
            out += text
            self._unknown = False

    def _send(self, data):
        if self._field == _TITLE:
            self._title += data
        else:
            self.on_text(bytes(data))

    def _close(self):
        self._need = self._high = 0
        self._unknown = False
        if self._field == _TITLE:
            self.on_title(bytes(self._title))
            self._title = bytearray()
        else:
            self.done = True
        self._field = None


def add_source(article):
    """End an article with SOURCE."""
    article.add(b"")
    for line in SOURCE:
        article.add(line)


def load(chunks, article):
    """Lay out the article in an API reply, given as an iterable of chunks
    of its body, into `article`. True if the reply held one.

    It stops reading once the extract has ended or the article is full, so
    `chunks` may be left unfinished. The article ends with SOURCE."""
    article.clear()
    wrapper = Wrapper(article)
    extractor = Extractor(wrapper.title, wrapper.put)
    for chunk in chunks:
        extractor.feed(chunk)
        if extractor.done or article.full:
            break
    wrapper.close()
    if extractor.found:
        add_source(article)
    return extractor.found
