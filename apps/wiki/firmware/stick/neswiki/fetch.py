"""Fetch an article a few pages at a time.

A long article is hundreds of KB, and laying it out keeps the Stick too
busy to answer the console promptly. So it is not fetched in one go. A
Fetch lays out one small piece of the reply per step(), and whoever owns it
calls step() only while more lines are wanted (Server.hungry), and only
when there is time for one before the console next asks for something
(device.py). Between times the connection just waits, with the rest of the
reply unread.

A server does not hold a stalled connection open for ever. When the read
fails, or ends before the article has, the search is made again and laid
out from the top with Article.skip set: the lines already held come out
the same and are passed over, and laying out goes on from where it stopped.

Nothing here touches hardware. open_stream(query) returns an object with
read(count) and close(), positioned at the reply's body; net.open_search is
the Stick's.
"""

from neswiki import proto, wikitext
from neswiki.linkrate import EARLY_LINES
from neswiki.wrap import Wrapper

CHUNK = 512             # bytes read at a time
PIECE = 96              # bytes laid out in one step: a millisecond or two of work,
                        # more where a paragraph ends and is wrapped
RETRIES = 3             # times in a row the search may be made again


class Fetch:
    def __init__(self, article, open_stream):
        self.article = article
        self.open_stream = open_stream
        self.stream = None
        self.data = b""             # read, and not yet laid out
        self.offset = 0
        self.query = None
        self.retries = 0
        self.reopened = 0           # times the search was made again, for the log

    @property
    def active(self):
        return self.query is not None

    def start(self, query):
        """Begin a search, dropping any other. Raises what open_stream does."""
        self.close()
        self.article.clear()
        self.query = query
        self.retries = 0
        self._open()

    def _open(self):
        self.article.skip = self.article.count
        self.wrapper = Wrapper(self.article)
        self.extractor = wikitext.Extractor(self.wrapper.title, self.wrapper.put)
        self.data = b""
        self.offset = 0
        self.stream = self.open_stream(self.query)

    def close(self):
        if self.stream is not None:
            try:
                self.stream.close()
            except OSError:
                pass
        self.stream = None
        self.query = None
        self.article.skip = 0

    def step(self):
        """Lay out one piece, reading more of the reply first if what was
        read is used up. None while there is more to come; proto.READY or
        proto.NOT_FOUND when the fetch is over. Raises if it failed with
        too little laid out to be worth reading."""
        if self.offset >= len(self.data):
            try:
                data = self.stream.read(CHUNK)
            except OSError:
                data = None
            if not data:
                return self._ended_early()
            self.retries = 0
            self.data = data
            self.offset = 0
            return None             # reading was this step's work
        start = self.offset
        self.offset = start + PIECE
        self.extractor.feed(self.data[start:start + PIECE])
        if self.extractor.done or self.article.full:
            return self._finish()
        return None

    def _finish(self):
        self.wrapper.close()
        wikitext.add_source(self.article)
        self.close()
        return proto.READY

    def _ended_early(self):
        """The reply stopped before the article did."""
        found = self.extractor.found or self.article.count
        if not found:
            self.close()
            return proto.NOT_FOUND
        self.retries += 1
        try:
            if self.retries > RETRIES:
                raise OSError("the connection keeps dropping")
            self.stream.close()
            self.stream = None
            self.reopened += 1
            self._open()
            return None
        except OSError:
            # What is held can still be read, if it is a screenful.
            enough = self.article.count >= EARLY_LINES
            self.close()
            if enough:
                return proto.READY
            raise
