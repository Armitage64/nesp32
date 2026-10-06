"""WIKI, NESpedia's service, with no console: requests in, replies out, and
the test in place of the Internet."""

import json
import os

import nesp_proto as p
import pytest
from nesp import HEADING, Wrap, frame, text_of

WIKI = p.NESP_SVC_WIKI
COLUMNS = p.NESP_WIKI_COLUMNS
EARLY = p.NESP_WIKI_EARLY
IDLE, NO_WIFI, FETCHING = p.NESP_ARTICLE_IDLE, p.NESP_ARTICLE_NO_WIFI, p.NESP_ARTICLE_FETCHING
READY, NOT_FOUND, ERROR = p.NESP_ARTICLE_READY, p.NESP_ARTICLE_NOT_FOUND, p.NESP_ARTICLE_ERROR
MORE, NO_LINE = p.NESP_ARTICLE_MORE, p.NESP_ARTICLE_NO_LINE
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
SOURCE = [b"", b"From Wikipedia, the free", b"encyclopedia. CC BY-SA 4.0."]


def body_of(title, text):
    page = {"pageid": 1, "ns": 0, "title": title, "index": 1, "extract": text}
    return json.dumps({"batchcomplete": True, "query": {"pages": [page]}},
                      separators=(",", ":")).encode("utf-8")


def paragraphs(count):
    return "\n".join("Paragraph %d." % number for number in range(count))


class Reader:
    """A console's side of the service."""

    def __init__(self, stick, online=True):
        self.stick = stick
        if online:
            stick.set_wifi(p.NESP_WIFI_JOINED, address=(10, 0, 0, 2))
        assert stick.hello(app=b"WIKI", services=[WIKI]).ok
        self.id = 0

    def search(self, words, new=True):
        """(state, total, message) of a search: a new one, or the last
        again."""
        if new:
            self.id = (self.id + 1) & 0xFF
        reply = self.stick.ask(WIKI, p.NESP_WIKI_SEARCH, bytes((self.id,)) + words)
        assert reply.ok and reply.payload[1] == self.id
        total = reply.payload[2] | reply.payload[3] << 8
        return reply.payload[0], total, reply.payload[4:]

    def line(self, number):
        """(state, total, the line or None)."""
        reply = self.stick.ask(WIKI, p.NESP_WIKI_LINE, bytes((number & 0xFF, number >> 8)))
        assert reply.ok and reply.payload[1] | reply.payload[2] << 8 == number
        total = reply.payload[3] | reply.payload[4] << 8
        if reply.payload[0] & NO_LINE:
            assert len(reply.payload) == 5
            return reply.payload[0], total, None
        assert len(reply.payload) == 5 + COLUMNS
        return reply.payload[0], total, reply.payload[5:]

    def lines(self, total):
        return [text_of(self.line(number)[2])[0] for number in range(total)]


@pytest.fixture
def reader(stick):
    return Reader(stick)


def test_it_answers_only_after_a_hello_asks_for_it(stick):
    assert stick.ask(WIKI, p.NESP_WIKI_LINE, b"\0\0").status == p.NESP_ST_INACTIVE
    assert stick.hello(services=[WIKI]).ok
    reply = stick.ask(WIKI, p.NESP_WIKI_LINE, b"\0\0")
    assert reply.ok and reply.payload == bytes((IDLE | NO_LINE, 0, 0, 0, 0))


def test_a_search_is_fetched_from_wikipedia(reader):
    assert reader.search(b"Famicom Disk System") == (FETCHING, 0, b"")
    stick = reader.stick
    assert stick.fetches == 1 and stick.fetching
    assert stick.fetch_url.startswith("https://en.wikipedia.org/w/api.php?")
    assert stick.fetch_url.endswith("&gsrsearch=Famicom%20Disk%20System")
    assert stick.fetch_agent.startswith("NESpedia/")       # Wikimedia asks to be told


def test_the_same_search_again_only_asks_how_it_is_going(reader):
    reader.search(b"Zelda")
    for _ in range(5):
        assert reader.search(b"Zelda", new=False) == (FETCHING, 0, b"")
    assert reader.stick.fetches == 1
    # The same words under a new id are a new search: Start was pressed again.
    reader.search(b"Zelda")
    assert reader.stick.fetches == 2


def test_an_article_is_laid_out_and_read_by_the_line(reader):
    reader.search(b"x")
    stick = reader.stick
    text = "Lead text of the article.\n\n\n== History ==\nIt began."
    assert stick.fetch_body(body_of("Some Thing", text)) is False      # it has all it wants
    stick.fetch_done()
    assert reader.search(b"x", new=False) == (READY, 9, b"")
    lines = [reader.line(number) for number in range(9)]
    assert all((state, total) == (READY, 9) for state, total, _ in lines)
    assert [text_of(line) for _, _, line in lines] == [
        (b"SOME THING", True), (b"", False),
        (b"Lead text of the article.", False), (b"", False),
        (b"HISTORY", True), (b"It began.", False), (b"", False),
        (b"From Wikipedia, the free", False), (b"encyclopedia. CC BY-SA 4.0.", False)]
    # A line is the screen's width exactly, padded with spaces.
    assert lines[5][2] == b"It began.".ljust(COLUMNS)


def test_the_recorded_reply_is_laid_out_as_the_wrapper_lays_it(reader):
    with open(os.path.join(FIXTURES, "nes_trimmed.json"), "rb") as handle:
        body = handle.read()
    page = json.loads(body)["query"]["pages"][0]
    reader.search(b"Nintendo Entertainment System")
    for start in range(0, len(body), 100):
        reader.stick.fetch_body(body[start:start + 100])
    reader.stick.fetch_done()
    state, total, _ = reader.search(b"Nintendo Entertainment System", new=False)
    assert state == READY
    lines = [reader.line(number)[2] for number in range(total)]
    assert all(len(line) == COLUMNS for line in lines)
    text = [text_of(line)[0] for line in lines]
    assert text[:4] == [b"NINTENDO ENTERTAINMENT", b"SYSTEM", b"", b"The Nintendo Entertainment"]
    assert lines[0][0] & HEADING and not lines[3][0] & HEADING
    assert text[-3:] == SOURCE
    history = text.index(b"HISTORY")
    assert text[history - 1] == b"" and text[history + 1:history + 3] == [b"", b"Background"]
    # Every word of the article is there, in order.
    wrap = Wrap()
    wrap.title(page["title"].encode())
    assert text[:2] == [text_of(line)[0] for line in wrap.lines][:2]
    assert b"Dendy (Russian: ?)" in b" ".join(text) and b"a price of Y9,800" in b" ".join(text)
    # Past the end there is no line, and the reply is short.
    assert reader.line(total) == (READY | NO_LINE, total, None)
    assert reader.line(0xFFFF) == (READY | NO_LINE, total, None)


def test_an_article_is_offered_while_it_is_still_arriving(reader):
    reader.search(b"long")
    stick = reader.stick
    body = body_of("T", paragraphs(60))
    head = body.index(b"Paragraph 5.")
    assert stick.fetch_body(body[:head]) is True
    state, total, _ = reader.search(b"long", new=False)
    assert (state, total) == (FETCHING, 0)              # under a screenful: not yet
    assert reader.line(0) == (FETCHING | NO_LINE, 0, None)
    middle = body.index(b"Paragraph 30.")
    stick.fetch_body(body[head:middle])
    state, total, _ = reader.search(b"long", new=False)
    assert state == READY | MORE and total >= EARLY
    first = reader.lines(total)
    assert first[:3] == [b"T", b"", b"Paragraph 0."]
    assert reader.line(total) == (READY | MORE | NO_LINE, total, None)
    # The rest comes in. What was laid out has not changed, and the total grew.
    stick.fetch_body(body[middle:])
    stick.fetch_done()
    state, grown, _ = reader.search(b"long", new=False)
    assert state == READY and grown > total
    assert reader.lines(total) == first and reader.lines(grown)[-3:] == SOURCE
    assert reader.line(5)[:2] == (READY, grown)         # every reply has the total


def test_a_new_search_empties_the_article_and_an_old_fetch_adds_nothing(reader):
    reader.search(b"first")
    stick = reader.stick
    old = stick.fetch_id
    body = body_of("First", paragraphs(40))
    stick.fetch_body(body[:len(body) // 2])
    assert reader.search(b"first", new=False)[0] == READY | MORE
    assert reader.search(b"second") == (FETCHING, 0, b"")
    assert stick.fetches == 2 and stick.fetch_id != old
    assert reader.line(0) == (FETCHING | NO_LINE, 0, None)
    # The first fetch's bytes are still on their way.
    assert stick.fetch_body(body[len(body) // 2:], fetch=old) is False
    stick.fetch_done(fetch=old)
    assert reader.search(b"second", new=False) == (FETCHING, 0, b"")
    stick.fetch_body(body_of("Second", "Its text."))
    stick.fetch_done()
    state, total, _ = reader.search(b"second", new=False)
    assert state == READY and reader.lines(total)[:3] == [b"SECOND", b"", b"Its text."]


def test_a_search_that_finds_nothing(reader):
    reader.search(b"qqqqzzzz")
    reader.stick.fetch_body(b'{"batchcomplete":true}')
    reader.stick.fetch_done()
    assert reader.search(b"qqqqzzzz", new=False) == (NOT_FOUND, 0, b"")
    assert reader.line(0) == (NOT_FOUND | NO_LINE, 0, None)


def test_a_fetch_that_fails_says_why_on_a_line_of_the_screen(reader):
    reader.search(b"x")
    reader.stick.fetch_done(ok=False, why=b"Wikipedia said 429")
    state, total, message = reader.search(b"x", new=False)
    assert (state, total) == (ERROR, 0)
    assert message == b"WIKIPEDIA SAID 429".center(COLUMNS)
    # With nothing to say, something is still said.
    reader.search(b"y")
    reader.stick.fetch_done(ok=False)
    assert reader.search(b"y", new=False)[2].strip() == b"THE SEARCH FAILED"


def test_a_reply_cut_short_is_read_if_there_is_a_screenful_of_it(reader):
    body = body_of("T", paragraphs(60))
    reader.search(b"x")
    reader.stick.fetch_body(body[:body.index(b"Paragraph 40.")])
    reader.stick.fetch_done(ok=False, why=b"the connection dropped")
    state, total, _ = reader.search(b"x", new=False)
    assert state == READY and total > EARLY
    assert reader.lines(total)[-3:] == SOURCE
    # With less than a screenful it is a failure.
    reader.search(b"y")
    reader.stick.fetch_body(body[:body.index(b"Paragraph 3.")])
    reader.stick.fetch_done(ok=False, why=b"the connection dropped")
    state, total, message = reader.search(b"y", new=False)
    assert (state, total) == (ERROR, 0) and message.strip() == b"THE CONNECTION DROPPED"
    assert reader.line(0)[2] is None


def test_without_wifi_nothing_is_fetched(stick):
    reader = Reader(stick, online=False)
    assert reader.search(b"x") == (NO_WIFI, 0, b"")
    assert stick.fetches == 0
    # It is asked again once there is a network, as a new search.
    stick.set_wifi(p.NESP_WIFI_JOINED)
    assert reader.search(b"x") == (FETCHING, 0, b"")


def test_a_fetch_that_cannot_be_started(reader):
    reader.stick.refuse_fetches()
    state, _, message = reader.search(b"x")
    assert state == ERROR and message.strip() == b"THE NESP32 IS BUSY"


def test_an_article_too_long_for_the_room_says_where_it_was_cut(stick):
    stick.alloc_most(32 * 1024)             # the least it will work with
    reader = Reader(stick)
    capacity = 32 * 1024 // COLUMNS
    reader.search(b"x")
    head = b'{"query":{"pages":[{"title":"T","extract":"'
    assert stick.fetch_body(head) is True
    wanted = True
    for count in range(1, 2000):
        wanted = stick.fetch_body(b"paragraph\\n")
        if not wanted:
            break
    assert count < capacity // 2 + 5        # it stops asking as soon as it is full
    stick.fetch_done()
    state, total, _ = reader.search(b"x", new=False)
    assert (state, total) == (READY, capacity)
    last = reader.line(total - 1)[2]
    assert text_of(last) == (b"[ARTICLE CUT SHORT HERE]", True)
    assert text_of(reader.line(total - 2)[2])[0] in (b"paragraph", b"")


def test_with_no_room_at_all_it_says_so(stick):
    stick.alloc_most(1024)
    reader = Reader(stick)
    state, _, message = reader.search(b"x")
    assert state == ERROR and message.strip() == b"THE NESP32 IS OUT OF MEMORY"
    assert stick.fetches == 0 and stick.allocated == 0


def test_another_rom_frees_the_article_and_stops_the_fetch(reader):
    stick = reader.stick
    assert stick.allocated == 1
    reader.search(b"x")
    old = stick.fetch_id
    stick.fetch_body(body_of("T", paragraphs(40)))
    assert stick.hello(app=b"SETP", services=[p.NESP_SVC_NET]).ok
    assert stick.allocated == 0 and stick.fetch_stops >= 1
    assert stick.ask(WIKI, p.NESP_WIKI_LINE, b"\0\0").status == p.NESP_ST_INACTIVE
    stick.fetch_body(b"late bytes", fetch=old)          # nowhere to put them, and no harm
    stick.fetch_done(fetch=old)
    # A reset of the same ROM starts from nothing too.
    again = Reader(stick)
    assert stick.allocated == 1
    assert again.line(0) == (IDLE | NO_LINE, 0, None)


def test_requests_that_are_not_what_the_ops_take(reader):
    stick = reader.stick
    for payload in (b"", b"\x01", b"\x01" + b"q" * 31):
        assert stick.ask(WIKI, p.NESP_WIKI_SEARCH, payload).status == p.NESP_ST_BAD_ARG
    for payload in (b"", b"\x01", b"\x01\x02\x03"):
        assert stick.ask(WIKI, p.NESP_WIKI_LINE, payload).status == p.NESP_ST_BAD_ARG
    assert stick.ask(WIKI, 0x7F).status == p.NESP_ST_NO_OP
    assert stick.fetches == 0
    # A ROM that cannot take a line's worth of reply cannot ask for lines.
    stick.hello(services=[WIKI], reply_max=p.NESP_REPLY_MIN)
    assert stick.ask(WIKI, p.NESP_WIKI_LINE, b"\0\0").status == p.NESP_ST_BAD_ARG


def test_a_request_sent_again_is_answered_afresh_not_from_memory(reader):
    # The same line asked for with the same bytes, before and after it came.
    stick = reader.stick
    reader.search(b"x")
    request = frame(WIKI, p.NESP_WIKI_LINE, 77, b"\0\0")
    before = stick.feed(request)
    stick.fetch_body(body_of("T", "Text."))
    stick.fetch_done()
    after = stick.feed(request)
    assert before != after and stick.repeats == 0
