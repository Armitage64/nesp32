"""From an API reply to ASCII text, fed in chunks of any size."""

import json
import os
import random

import pytest
from conftest import FIXTURES

from neswiki import wikitext
from neswiki.linkrate import COLUMNS
from neswiki.wrap import HEADING, Article


def extract(body, chunk=None):
    """(title, text, found, done) from a reply's body."""
    titles, text = [], bytearray()
    extractor = wikitext.Extractor(titles.append, text.extend)
    size = chunk or len(body) or 1
    for start in range(0, len(body), size):
        extractor.feed(body[start:start + size])
    assert len(titles) <= 1
    return (titles[0] if titles else None), bytes(text), extractor.found, extractor.done


def reply(title, text, ensure_ascii=False):
    page = {"pageid": 1, "ns": 0, "title": title, "index": 1, "extract": text}
    return json.dumps({"batchcomplete": True, "query": {"pages": [page]}},
                      ensure_ascii=ensure_ascii, separators=(",", ":")).encode("utf-8")


def plain(text):
    """What the extractor should make of a string, worked out a character
    at a time."""
    out, unknown = bytearray(), False
    for char in text:
        mapped = wikitext.to_ascii(ord(char))
        if mapped is None:
            if not unknown:
                out += b"?"
            unknown = True
        elif mapped:
            out += mapped
            unknown = False
    return bytes(out)


def test_api_path_escapes_the_query():
    path = wikitext.api_path("Nintendo Entertainment System")
    assert path.endswith("&gsrsearch=Nintendo%20Entertainment%20System")
    assert wikitext.api_path("a&b=c?/#").endswith("=a%26b%3Dc%3F%2F%23")
    assert wikitext.api_path("Pokémon").endswith("=Pok%C3%A9mon")
    assert wikitext.api_path("A-b_c.d~9").endswith("=A-b_c.d~9")


def test_title_and_text():
    assert extract(reply("A Title", "Some text.\nMore.")) == (
        b"A Title", b"Some text.\nMore.", True, True)


def test_escapes():
    body = reply("Q", 'He said "hi" \\ back/forth\ttab\r\n')
    assert b'\\"hi\\"' in body and b"\\\\" in body and b"\\t" in body
    assert extract(body)[1] == b'He said "hi" \\ back/forth tab\n'
    # An escaped slash is allowed too.
    assert extract(b'{"extract":"a\\/b"}')[1] == b"a/b"


def test_a_quote_in_the_title_does_not_end_it():
    assert extract(reply('The "extract":" trap', "Body"))[:2] == (b'The "extract":" trap', b"Body")


@pytest.mark.parametrize("ensure_ascii", [False, True])
def test_characters_outside_ascii(ensure_ascii):
    text = ("café Ångström Łódź “quoted” it’s "
            "1983–1985 ¥14,800 5×3 wait… æon straße 20 km")
    body = reply("Pokémon", text, ensure_ascii)
    assert (b"\\u" in body) == ensure_ascii
    title, out, _, _ = extract(body)
    assert title == b"Pokemon"
    assert out == (b'cafe Angstrom Lodz "quoted" it\'s 1983-1985 Y14,800 5x3 wait... '
                   b"aeon strasse 20 km")


@pytest.mark.parametrize("ensure_ascii", [False, True])
def test_a_run_of_unknown_characters_is_one_question_mark(ensure_ascii):
    # Cyrillic with a combining accent inside, Japanese, and an emoji, which
    # is a surrogate pair when escaped.
    text = ("Dendy (Де́нди), "
            "ファミコン and \U0001F3AE\U0001F3AE!")
    assert extract(reply("T", text, ensure_ascii))[1] == b"Dendy (?), ? and ?!"


def test_broken_utf8_and_broken_escapes_do_not_stop_it():
    assert extract(b'{"extract":"a\xffb\xc3(c\xe2\x82"}')[1] == b"a?b?(c"
    assert extract(b'{"extract":"a\\uZZZZb\\ud83dc\\udc00d"}')[1] == b"a?bc?d"


def test_no_article():
    assert extract(b'{"batchcomplete":true}') == (None, b"", False, False)
    assert extract(b"") == (None, b"", False, False)
    assert extract(b'{"error":{"code":"x","info":"y"}}') == (None, b"", False, False)


def test_a_reply_cut_short_is_found_but_not_done():
    body = reply("T", "Some text here")
    assert extract(body[:-12]) == (b"T", b"Some te", True, False)


def test_nothing_after_the_extract_is_read():
    body = reply("T", "Body")[:-3] + b',"title":"Other","extract":"More"}]}}'
    assert extract(body) == (b"T", b"Body", True, True)


def test_every_chunk_size_gives_the_same_text():
    text = ('Lead “quoted” café "x" \\ Денди end.\n\n\n'
            "== H ==\nBody \U0001F3AE… ¥5")
    for ensure_ascii in (False, True):
        body = reply("Tié", text, ensure_ascii)
        whole = extract(body)
        assert whole == (b"Tie", plain(text), True, True)
        for size in range(1, 40):
            assert extract(body, size) == whole


def test_random_chunks_of_the_recorded_reply():
    with open(os.path.join(FIXTURES, "nes_trimmed.json"), "rb") as handle:
        body = handle.read()
    page = json.loads(body)["query"]["pages"][0]
    expected = (plain(page["title"]), plain(page["extract"]), True, True)
    assert extract(body) == expected
    assert b"Dendy (Russian: ?)" in expected[1] and b"a price of Y9,800" in expected[1]
    generator = random.Random(7)
    for _ in range(20):
        titles, text = [], bytearray()
        extractor = wikitext.Extractor(titles.append, text.extend)
        position = 0
        while position < len(body):
            size = generator.randint(1, 300)
            extractor.feed(body[position:position + size])
            position += size
        assert (titles[0], bytes(text), extractor.found, extractor.done) == expected


def test_load_lays_out_the_recorded_reply():
    with open(os.path.join(FIXTURES, "nes_trimmed.json"), "rb") as handle:
        body = handle.read()
    article = Article(400)
    assert wikitext.load([body[start:start + 512] for start in range(0, len(body), 512)], article)
    assert article.title == b"Nintendo Entertainment System"
    lines = [article.line(index) for index in range(article.count)]
    text = [bytes(char & 0x7F for char in line).rstrip() for line in lines]
    assert text[:4] == [b"NINTENDO ENTERTAINMENT", b"SYSTEM", b"", b"The Nintendo Entertainment"]
    assert all(char & HEADING for char in lines[0][:22]) and not lines[3][0] & HEADING
    history = text.index(b"HISTORY")
    assert text[history - 1] == b"" and text[history + 1:history + 3] == [b"", b"Background"]
    assert lines[history + 2][0] & HEADING and text[history + 3] != b""
    # Every word of the article is there, in order.
    page = json.loads(body)["query"]["pages"][0]
    words = [word.strip(b"=") for word in plain(page["extract"]).split()]
    assert text[-3:] == [b"", b"From Wikipedia, the free", b"encyclopedia. CC BY-SA 4.0."]
    laid_out = b" ".join(text[3:-2]).split()
    assert [word.upper() for word in laid_out] == [word.upper() for word in words if word]
    assert all(len(line) == COLUMNS for line in lines) and not article.full


def test_load_of_a_search_that_finds_nothing():
    article = Article(10)
    article.add(b"left over")
    assert wikitext.load([b'{"batchcomplete":true}'], article) is False
    assert article.count == 0


def test_load_stops_reading_when_the_article_is_full():
    def chunks():
        yield b'{"query":{"pages":[{"title":"T","extract":"'
        for number in range(1000):
            taken.append(number)
            yield b"paragraph\\n"

    taken = []
    article = Article(8)
    assert wikitext.load(chunks(), article)
    assert article.full and article.count == 8 and len(taken) < 10
    assert article.line(7).rstrip() == bytes(char | 0x80 for char in b"[ARTICLE CUT SHORT HERE]")
