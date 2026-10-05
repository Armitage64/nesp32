"""Fetching an article a few pages at a time, and making the search again
when the connection has gone."""

import json

import pytest

from neswiki import proto, wikitext
from neswiki.fetch import CHUNK, Fetch
from neswiki.linkrate import FILL_HIGH, FILL_LOW
from neswiki.server import Server
from neswiki.wrap import Article


def reply(paragraphs):
    text = "\n".join("Paragraph %d of the text, with words enough to wrap." % index
                     for index in range(paragraphs))
    page = {"pageid": 1, "ns": 0, "title": "Long", "index": 1, "extract": text}
    return json.dumps({"query": {"pages": [page]}}, separators=(",", ":")).encode()


class Stream:
    def __init__(self, body, fail_after=None):
        self.body = body
        self.fail_after = fail_after    # reads before the connection drops
        self.reads = 0
        self.closed = False

    def read(self, count):
        self.reads += 1
        if self.fail_after is not None and self.reads > self.fail_after:
            raise OSError("ETIMEDOUT")
        data, self.body = self.body[:count], self.body[count:]
        return data

    def close(self):
        self.closed = True


def whole(body):
    article = Article(3000)
    assert wikitext.load([body], article)
    return [article.line(index) for index in range(article.count)]


def lines_of(article):
    return [article.line(index) for index in range(article.count)]


def run(fetch, limit=10000):
    for _ in range(limit):
        result = fetch.step()
        if result is not None:
            return result
    raise AssertionError("the fetch did not end")


def test_a_fetch_in_steps_gives_the_article_a_single_load_does():
    body = reply(300)
    article = Article(3000)
    streams = []
    fetch = Fetch(article, lambda query: streams.append(Stream(body)) or streams[-1])
    fetch.start("long")
    counts = []
    result = None
    while result is None:
        result = fetch.step()
        counts.append(article.count)
    assert result == proto.READY
    # A step is a little: a paragraph or two's worth of lines at the most.
    assert max(after - before for before, after in zip(counts, counts[1:])) <= 12
    assert len(counts) > len(body) // 96
    assert lines_of(article) == whole(body)
    assert not fetch.active and streams[0].closed and len(streams) == 1


def test_a_dropped_connection_is_resumed_where_it_stopped():
    body = reply(300)
    article = Article(3000)
    streams = []

    def open_stream(query):
        # The first two connections drop; the third holds.
        streams.append(Stream(body, fail_after=(7, 30, None)[len(streams)]))
        return streams[-1]
    fetch = Fetch(article, open_stream)
    fetch.start("long")
    assert run(fetch) == proto.READY
    assert len(streams) == 3 and fetch.reopened == 2
    assert lines_of(article) == whole(body)
    assert all(stream.closed for stream in streams)


def test_lines_are_never_taken_back_while_a_fetch_is_resumed():
    body = reply(300)
    article = Article(3000)
    streams = []
    fetch = Fetch(article, lambda query: streams.append(
        Stream(body, fail_after=12 if not streams else None)) or streams[-1])
    fetch.start("long")
    counts = []
    held = []
    while fetch.step() is None:
        counts.append(article.count)
        if len(held) < 40 <= article.count:
            held = lines_of(article)[:40]
    assert counts == sorted(counts)
    assert lines_of(article)[:40] == held


def test_a_connection_that_keeps_dropping_leaves_what_was_read():
    body = reply(300)
    article = Article(3000)
    opened = []

    def open_stream(query):
        opened.append(1)
        return Stream(body, fail_after=10 if len(opened) == 1 else 0)
    fetch = Fetch(article, open_stream)
    fetch.start("long")
    assert run(fetch) == proto.READY        # enough to read: it is kept
    assert 28 <= article.count < len(whole(body)) and not fetch.active
    assert lines_of(article) == whole(body)[:article.count]


def test_one_that_drops_before_a_screenful_is_an_error():
    article = Article(3000)
    opened = []

    def open_stream(query):
        opened.append(1)
        return Stream(reply(300), fail_after=1 if len(opened) == 1 else 0)
    fetch = Fetch(article, open_stream)
    fetch.start("long")
    with pytest.raises(OSError):
        run(fetch)
    assert not fetch.active


def test_nothing_found():
    article = Article(100)
    fetch = Fetch(article, lambda query: Stream(b'{"batchcomplete":true}'))
    fetch.start("zzqq")
    assert run(fetch) == proto.NOT_FOUND and article.count == 0


def test_a_new_search_drops_the_one_under_way():
    article = Article(3000)
    streams = []
    fetch = Fetch(article, lambda query: streams.append(Stream(reply(50))) or streams[-1])
    fetch.start("one")
    fetch.step()
    fetch.start("two")
    assert streams[0].closed and article.count == 0
    assert run(fetch) == proto.READY


class Port:
    def __init__(self):
        self.incoming = []

    def read(self):
        return self.incoming.pop(0) if self.incoming else None

    def write(self, data):
        self.reply = proto.parse_reply(bytes(data))


def test_only_a_few_pages_ahead_of_the_reader_are_laid_out():
    body = reply(600)
    total = len(whole(body))
    article = Article(3000)
    port = Port()
    server = Server(article, port)
    fetch = Fetch(article, lambda query: Stream(body))
    port.incoming.append(proto.search_request(1, b"long"))
    server.poll()
    fetch.start(server.take_search().decode())

    def settle():
        steps = 0
        while fetch.active and server.hungry():
            if fetch.step() == proto.READY:
                server.finish(proto.READY)
            steps += 1
        return steps

    assert settle() > 0
    first = article.count
    assert FILL_HIGH <= first < FILL_HIGH + 6 and first < total
    # Reading on does nothing until the reader nears the end of what is held.
    for line in range(first - FILL_LOW):
        port.incoming.append(proto.line_request(line))
        server.poll()
        assert port.reply[:2] == (proto.READY | proto.MORE, line)
        assert settle() == 0 and article.count == first
    port.incoming.append(proto.line_request(first - FILL_LOW + 1))
    server.poll()
    assert settle() > 0
    assert article.count >= first - FILL_LOW + 1 + FILL_HIGH
    # Asking for the line past the last, as the console does to learn the
    # length, is not reading: it brings nothing in.
    count = article.count
    port.incoming.append(proto.line_request(count))
    server.poll()
    assert port.reply[:3] == (proto.READY | proto.MORE | proto.NO_SUCH_LINE, count, count)
    assert settle() == 0
    # Read to the end, and the whole article has come.
    line = 0
    while fetch.active:
        port.incoming.append(proto.line_request(min(line, article.count - 1)))
        server.poll()
        settle()
        line += 20
    assert server.state == proto.READY and lines_of(article) == whole(body)
