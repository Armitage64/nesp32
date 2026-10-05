"""Answer the console's requests from the article the Stick holds.

Nothing here touches hardware or the network. A *port* is the UART:

    read()          the bytes received since the last call, or None
    write(data)     queue a reply

and whoever owns the Server does the fetching. The Stick's loop is:

    server.poll()                   as often as it can
    query = server.take_search()    a search to carry out, or None
    ... fetch, with server.poll() between chunks ...
    server.finish(READY)            or NOT_FOUND, or ERROR with a message

A search arrives with an id, and the console sends the same search again
every few frames to ask how it is going. A search with a new id or new
words starts a fetch; the same one again is only answered with the state.

An article is offered before it has all arrived. Once EARLY_LINES of it are
laid out the Server says READY with MORE set, and a total that is the lines
so far; the console starts reading and learns the growing total from every
reply. The lines already laid out never change, so they can be served while
the rest comes in. take_search() empties the article, so what is offered
is always the search being fetched and never the one before it.

The rest comes in only as it is wanted: see hungry().

poll() answers only the last request it finds. The console listens for a
reply just after it asks, and then no longer, so after a spell of not
polling (a TLS handshake) the older requests are past answering.
"""

from neswiki import proto
from neswiki.linkrate import COLUMNS, EARLY_LINES, FILL_HIGH, FILL_LOW, REPLY_SIZE


class Server:
    def __init__(self, article, port, online=True):
        self.article = article
        self.port = port
        self.online = online            # False: searches are answered NO_WIFI
        self.decoder = proto.Decoder()
        self.reply = bytearray(REPLY_SIZE)
        self.lines = memoryview(article.data)
        self.state = proto.IDLE
        self.message = None             # COLUMNS bytes, with ERROR
        self.search_id = None
        self.query = None
        self.pending = None
        self.reached = 0                # the furthest line the console has been given
        self.filling = True
        self.requests = 0
        self.line_requests = 0
        self.unanswered = 0             # requests found behind a later one

    def poll(self):
        """Answer what has come. True if a reply went out."""
        data = self.port.read()
        if not data:
            return False
        found = self.decoder.feed(data)
        if not found:
            return False
        self.requests += len(found)
        self.unanswered += len(found) - 1
        op, payload = found[-1]
        if op == proto.OP_LINE and len(payload) == 2:
            self._line(payload[0] | payload[1] << 8)
        elif op == proto.OP_SEARCH and len(payload) >= 2:
            self._search(payload[0], bytes(payload[1:]))
        else:
            return False
        self.port.write(self.reply)
        return True

    def _offer(self):
        """(state, total) as the console is told them."""
        if self.state == proto.READY:
            return proto.READY, self.article.count
        if (self.state == proto.FETCHING and self.pending is None
                and self.article.count >= EARLY_LINES):
            return proto.READY | proto.MORE, self.article.count
        return self.state, 0

    def _line(self, number):
        self.line_requests += 1
        state, total = self._offer()
        if number < total:
            if number > self.reached:
                self.reached = number
            proto.fill_reply(self.reply, state, number, total, self.lines, number * COLUMNS)
        else:
            proto.fill_reply(self.reply, state | proto.NO_SUCH_LINE, number, total)

    def _search(self, search_id, query):
        if search_id != self.search_id or query != self.query:
            self.search_id = search_id
            self.query = query
            self.message = None
            if self.online:
                self.state = proto.FETCHING
                self.pending = query
            else:
                self.state = proto.NO_WIFI
                self.pending = None
        state, total = self._offer()
        proto.fill_reply(self.reply, state, proto.NO_LINE | search_id, total, self.message)

    def take_search(self):
        """The words of a search that is waiting to be carried out, once.
        The article is emptied for it."""
        query, self.pending = self.pending, None
        if query is not None:
            self.article.clear()
            self.reached = 0
            self.filling = True
        return query

    def hungry(self):
        """Should more of the article be laid out? It is kept between
        FILL_LOW and FILL_HIGH lines ahead of the furthest line the console
        has been given, in runs, so that the laying out, which makes the
        Stick slow to answer, mostly happens while a page is being read
        and not while it is being scrolled."""
        ahead = self.article.count - self.reached
        if self.filling:
            if ahead >= FILL_HIGH:
                self.filling = False
        elif ahead < FILL_LOW:
            self.filling = True
        return self.filling

    def finish(self, state, text=None):
        """The fetch is over: READY with the article laid out, NOT_FOUND,
        or ERROR with a few words for the console's screen. A newer search
        that came in the meantime stays waiting."""
        if self.pending is None:
            self.state = state
            self.message = proto.message(text) if text else None
