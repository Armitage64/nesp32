"""The link's frames and the Stick's answers, with no console."""

import random

from neswiki import proto
from neswiki.linkrate import COLUMNS, QUERY_MAX, REPLY_SIZE
from neswiki.server import Server
from neswiki.wrap import HEADING, Article


class FakePort:
    def __init__(self):
        self.incoming = []
        self.replies = []

    def read(self):
        return self.incoming.pop(0) if self.incoming else None

    def write(self, data):
        self.replies.append(proto.parse_reply(bytes(data)))
        assert self.replies[-1] is not None


def make_server(lines=40, **options):
    article = Article(100)
    port = FakePort()
    server = Server(article, port, **options)
    return server, port, article, lines


def ask(server, port, frame):
    port.incoming.append(frame)
    before = len(port.replies)
    answered = server.poll()
    assert answered == (len(port.replies) > before)
    return port.replies[-1] if answered else None


def fetch(server, article, count):
    assert server.take_search() is not None
    article.clear()
    for index in range(count):
        article.add(b"line %d" % index, HEADING if index == 0 else 0)
    server.finish(proto.READY)


def test_crc_is_ccitt_false():
    assert proto.crc16(b"123456789") == 0x29B1
    assert proto.crc16(b"xx123456789yy", 2, 11) == 0x29B1
    assert proto.crc16(b"") == 0xFFFF


def test_request_frames():
    assert proto.line_request(0x1234) == bytes((0x57, 2, 2, 0x34, 0x12)) + bytes(
        divmod(proto.crc16(bytes((2, 2, 0x34, 0x12))), 256))
    frame = proto.search_request(7, b"NES")
    assert frame[:7] == b"\x57\x01\x04\x07NES" and len(frame) == 9
    assert len(proto.search_request(1, b"x" * QUERY_MAX)) == proto.REQUEST_MAX


def test_reply_frames():
    reply = bytearray(REPLY_SIZE)
    text = memoryview(bytearray(b"A" * COLUMNS + b"second line of the text.    "))
    proto.fill_reply(reply, proto.READY, 0x0102, 0x0304, text, COLUMNS)
    assert reply[:6] == bytes((0xA5, 3, 2, 1, 4, 3))
    assert proto.parse_reply(reply) == (3, 0x0102, 0x0304, b"second line of the text.    ")
    proto.fill_reply(reply, proto.IDLE, proto.NO_LINE | 9, 0)
    assert proto.parse_reply(reply) == (0, 0xFF09, 0, b" " * COLUMNS)
    for index in range(REPLY_SIZE):     # any damaged byte is caught
        damaged = bytearray(reply)
        damaged[index] ^= 0x10
        assert proto.parse_reply(damaged) is None
    assert proto.parse_reply(reply[:-1]) is None


def test_message_is_centered_capitals():
    assert proto.message("no route") == b"          NO ROUTE          "
    assert len(proto.message("x" * 40)) == COLUMNS


def test_decoder_finds_requests_among_noise_in_any_pieces():
    frames = [proto.line_request(n) for n in (0, 1, 0x5757, 300)] + [
        proto.search_request(3, b"W W\x57W"), proto.line_request(9)]
    expected = [(frame[1], frame[3:-2]) for frame in frames]
    generator = random.Random(5)
    for _ in range(200):
        stream = bytearray()
        for frame in frames:
            # The controller read's junk, a stray marker, a damaged frame.
            stream += bytes(generator.choice((b"", b"\xf8", b"\xf0\xf8", b"\x57", b"\x57\x02",
                                              b"\x57\x02\x02\x00\x00\x00\x00")))
            stream += frame
        decoder = proto.Decoder()
        found = []
        position = 0
        while position < len(stream):
            size = generator.randint(1, 12)
            found += decoder.feed(bytes(stream[position:position + size]))
            position += size
        assert found == expected
        assert decoder.held == b""


def test_decoder_passes_over_a_marker_with_an_impossible_length():
    decoder = proto.Decoder()
    assert decoder.feed(b"\x57\x01\xff" + proto.line_request(4)) == [(proto.OP_LINE, b"\x04\x00")]
    assert decoder.discarded == 3


def test_decoder_keeps_a_frame_that_has_not_all_come():
    decoder = proto.Decoder()
    frame = proto.search_request(1, b"Nintendo")
    assert decoder.feed(frame[:5]) == []
    assert decoder.feed(frame[5:]) == [(proto.OP_SEARCH, b"\x01Nintendo")]


def test_a_search_starts_a_fetch_once_and_then_reports():
    server, port, article, _ = make_server()
    assert ask(server, port, proto.line_request(0)) == (proto.IDLE | proto.NO_SUCH_LINE, 0, 0,
                                                       b" " * COLUMNS)
    search = proto.search_request(1, b"Famicom")
    assert ask(server, port, search) == (proto.FETCHING, 0xFF01, 0, b" " * COLUMNS)
    assert ask(server, port, search)[0] == proto.FETCHING
    assert server.take_search() == b"Famicom" and server.take_search() is None
    assert ask(server, port, search)[0] == proto.FETCHING
    assert ask(server, port, proto.line_request(0))[0] == proto.FETCHING | proto.NO_SUCH_LINE
    article.add(b"line")
    server.finish(proto.READY)
    assert ask(server, port, search) == (proto.READY, 0xFF01, 1, b" " * COLUMNS)
    assert server.take_search() is None     # asking again fetched nothing


def test_lines():
    server, port, article, _ = make_server()
    ask(server, port, proto.search_request(1, b"x"))
    fetch(server, article, 12)
    state, line, total, text = ask(server, port, proto.line_request(0))
    assert (state, line, total) == (proto.READY, 0, 12)
    assert text == bytes(char | HEADING for char in b"line 0") + b" " * 22
    assert ask(server, port, proto.line_request(11)) == (proto.READY, 11, 12,
                                                        b"line 11".ljust(COLUMNS))
    assert ask(server, port, proto.line_request(12)) == (proto.READY | proto.NO_SUCH_LINE, 12, 12,
                                                        b" " * COLUMNS)
    assert server.line_requests == 3


def test_a_new_id_or_new_words_is_a_new_search():
    server, port, article, _ = make_server()
    ask(server, port, proto.search_request(1, b"one"))
    fetch(server, article, 3)
    assert ask(server, port, proto.search_request(2, b"one"))[:2] == (proto.FETCHING, 0xFF02)
    assert server.take_search() == b"one"
    server.finish(proto.NOT_FOUND)
    assert ask(server, port, proto.search_request(2, b"one"))[0] == proto.NOT_FOUND
    # A console that was reset counts its ids from 1 again.
    assert ask(server, port, proto.search_request(2, b"two"))[0] == proto.FETCHING
    assert server.take_search() == b"two"


def test_a_search_made_during_a_fetch_is_not_lost():
    server, port, article, _ = make_server()
    ask(server, port, proto.search_request(1, b"one"))
    assert server.take_search() == b"one"
    ask(server, port, proto.search_request(2, b"two"))     # while "one" is being fetched
    article.add(b"one's text")
    server.finish(proto.READY)
    assert ask(server, port, proto.search_request(2, b"two"))[0] == proto.FETCHING
    assert ask(server, port, proto.line_request(0))[0] == proto.FETCHING | proto.NO_SUCH_LINE
    assert server.take_search() == b"two"


def test_an_article_is_offered_while_it_is_still_arriving():
    server, port, article, _ = make_server()
    search = proto.search_request(1, b"x")
    ask(server, port, search)
    assert server.take_search() == b"x"
    for index in range(27):
        article.add(b"line %d" % index)
    assert ask(server, port, search)[:3] == (proto.FETCHING, 0xFF01, 0)
    assert ask(server, port, proto.line_request(0))[0] == proto.FETCHING | proto.NO_SUCH_LINE
    article.add(b"line 27")
    assert ask(server, port, search)[:3] == (proto.READY | proto.MORE, 0xFF01, 28)
    assert ask(server, port, proto.line_request(27)) == (
        proto.READY | proto.MORE, 27, 28, b"line 27".ljust(COLUMNS))
    assert ask(server, port, proto.line_request(28))[:3] == (
        proto.READY | proto.MORE | proto.NO_SUCH_LINE, 28, 28)
    article.add(b"line 28")
    assert ask(server, port, proto.line_request(28))[:3] == (proto.READY | proto.MORE, 28, 29)
    server.finish(proto.READY)
    assert ask(server, port, proto.line_request(28))[:3] == (proto.READY, 28, 29)


def test_the_article_before_is_never_offered_for_a_new_search():
    server, port, article, _ = make_server()
    ask(server, port, proto.search_request(1, b"one"))
    fetch(server, article, 40)
    again = proto.search_request(2, b"two")
    assert ask(server, port, again)[:3] == (proto.FETCHING, 0xFF02, 0)   # 40 lines of "one" held
    assert ask(server, port, proto.line_request(0))[0] == proto.FETCHING | proto.NO_SUCH_LINE
    assert server.take_search() == b"two" and article.count == 0
    # Nor while "one" is still coming in when "two" is asked for.
    ask(server, port, proto.search_request(3, b"three"))
    server.take_search()
    for index in range(40):
        article.add(b"three %d" % index)
    ask(server, port, proto.search_request(4, b"four"))
    assert ask(server, port, proto.search_request(4, b"four"))[:3] == (proto.FETCHING, 0xFF04, 0)
    server.finish(proto.READY)
    assert ask(server, port, proto.search_request(4, b"four"))[0] == proto.FETCHING


def test_errors_carry_a_message():
    server, port, _, _ = make_server()
    ask(server, port, proto.search_request(1, b"x"))
    server.take_search()
    server.finish(proto.ERROR, "HTTP 503")
    assert ask(server, port, proto.search_request(1, b"x")) == (
        proto.ERROR, 0xFF01, 0, b"          HTTP 503          ")
    assert ask(server, port, proto.search_request(2, b"x"))[3] == b" " * COLUMNS


def test_offline_searches_are_answered_no_wifi():
    server, port, _, _ = make_server(online=False)
    assert ask(server, port, proto.search_request(1, b"x"))[0] == proto.NO_WIFI
    assert server.take_search() is None
    server.online = True
    assert ask(server, port, proto.search_request(1, b"x"))[0] == proto.NO_WIFI   # the same search
    assert ask(server, port, proto.search_request(2, b"x"))[0] == proto.FETCHING


def test_only_the_last_of_several_requests_is_answered():
    server, port, article, _ = make_server()
    ask(server, port, proto.search_request(1, b"x"))
    fetch(server, article, 5)
    reply = ask(server, port, proto.line_request(1) + b"\xf8" + proto.line_request(2)
                + b"\xf8" + proto.line_request(3))
    assert reply[1] == 3 and len(port.replies) == 2     # the search's, and this one
    assert server.unanswered == 2


def test_requests_it_cannot_make_sense_of_get_no_reply():
    server, port, _, _ = make_server()
    assert ask(server, port, proto.request(9, b"??")) is None
    assert ask(server, port, proto.request(proto.OP_LINE, b"\x00")) is None
    assert ask(server, port, proto.request(proto.OP_SEARCH, b"\x01")) is None    # no words
    assert ask(server, port, b"\xf8\xf8") is None
