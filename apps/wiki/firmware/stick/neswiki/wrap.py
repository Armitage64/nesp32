"""An article as the console reads it: lines of exactly COLUMNS characters.

Line n is the slice at COLUMNS * n of one buffer, allocated once and used
again for every article, so finding a line is arithmetic and nothing is
allocated while the link is being served.

A byte of a line is a tile number on the console: ASCII for body text, and
ASCII with HEADING set for a heading, which the console's tile set shows in
a second colour.

Wrapper lays plain text out into an Article. The text arrives in pieces of
any size (wikitext.Extractor); a paragraph is held until its newline and
then wrapped. Wikipedia's plain text marks a heading as a paragraph of its
own, "== History ==", with a deeper level for each extra "=".

    title           capitals, in the heading colour, then a blank line
    == Heading ==   capitals, in the heading colour
    === Deeper ===  as written, in the heading colour
    paragraphs      a blank line between them, none after a heading
"""

from neswiki.linkrate import COLUMNS

HEADING = 0x80                  # set on every character of a heading line
PARAGRAPH_MAX = 4096            # a longer run without a newline is cut there
CUT_TEXT = b"[ARTICLE CUT SHORT HERE]"
_SPACES = b" " * COLUMNS


def fill(text, width=COLUMNS):
    """Yield the lines of text wrapped at spaces. A word longer than a line
    is cut to fit."""
    line = b""
    for word in text.split():
        while len(word) > width:
            if line:
                yield line
                line = b""
            yield word[:width]
            word = word[width:]
        if not line:
            line = word
        elif len(line) + 1 + len(word) <= width:
            line = line + b" " + word
        else:
            yield line
            line = word
    if line:
        yield line


class Article:
    """Room for `capacity` lines. The last of them is kept for CUT_TEXT, so
    an article that does not fit says so where it stops."""

    def __init__(self, capacity):
        self.capacity = capacity
        self.data = bytearray(capacity * COLUMNS)
        self.view = memoryview(self.data)
        self.count = 0
        self.full = False
        self.title = b""
        self.skip = 0           # lines to pass over: see fetch.py

    def clear(self):
        self.count = 0
        self.full = False
        self.title = b""
        self.skip = 0

    def add(self, text, flags=0):
        """Store one line, at most COLUMNS characters. False once there is
        no room, and from then on."""
        if self.full:
            return False
        if self.skip:
            self.skip -= 1      # held already, from before the fetch was resumed
            return True
        if self.count == self.capacity - 1:
            self.full = True
            text, flags = CUT_TEXT, HEADING
        if flags:
            text = bytes([char | flags for char in text])
        # Written through a view of the line alone. Storing into a slice of
        # the whole buffer makes MicroPython move everything after the slice
        # as well, even when nothing changes length: a quarter of a megabyte
        # for every line, which took a fetch from seconds to minutes.
        start = self.count * COLUMNS
        line = self.view[start:start + COLUMNS]
        line[:] = text + _SPACES[:COLUMNS - len(text)]
        self.count += 1
        return not self.full

    def line(self, index):
        """Line `index` as COLUMNS bytes."""
        start = index * COLUMNS
        return bytes(self.data[start:start + COLUMNS])


class Wrapper:
    def __init__(self, article):
        self.article = article
        self.paragraph = bytearray()
        self.blank_last = True      # nothing yet: no blank line wanted first
        self.after_heading = False

    def title(self, text):
        self.article.title = bytes(text)
        self._heading(text.upper())
        self._blank()
        self.after_heading = True   # that blank line is the gap

    def put(self, data):
        """More of the article's text: ASCII, with newlines between
        paragraphs."""
        start = 0
        while True:
            newline = data.find(b"\n", start)
            if newline < 0:
                self.paragraph += data[start:]
                if len(self.paragraph) > PARAGRAPH_MAX:
                    self._end_paragraph()
                return
            self.paragraph += data[start:newline]
            self._end_paragraph()
            start = newline + 1

    def close(self):
        """The text has ended; lay out what is held."""
        self._end_paragraph()

    def _end_paragraph(self):
        text = bytes(self.paragraph).strip()
        self.paragraph = bytearray()
        if not text:
            return
        if text.startswith(b"==") and text.endswith(b"==") and len(text) > 4:
            level = len(text) - len(text.lstrip(b"="))
            name = text.strip(b"=").strip()
            if name:
                self._heading(name.upper() if level == 2 else name)
                return
        if not self.after_heading:
            self._blank()
        for line in fill(text):
            self.article.add(line)
        self.blank_last = False
        self.after_heading = False

    def _heading(self, name):
        self._blank()
        for line in fill(name):
            self.article.add(line, HEADING)
        self.blank_last = False
        self.after_heading = True

    def _blank(self):
        if not self.blank_last:
            self.article.add(b"")
            self.blank_last = True
