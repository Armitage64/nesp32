"""The firmware's text code: from an API reply to ASCII, and from ASCII to
lines of a console's width. Fed in chunks of any size.

These are nes-wiki's tests of the Python this was ported from
(tests/test_wikitext.py and tests/test_wrap.py there), and while that
Python still ran, the two were also compared on thousands of random texts.
"""

import json
import os
import random

import nesp
import nesp_proto as p
import pytest
from nesp import Extract, Wrap, text_of

COLUMNS = p.NESP_WIKI_COLUMNS
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
PARAGRAPH = 4096                # nesp_text.h: text held while a paragraph has not ended


# --- lines -------------------------------------------------------------------------

def lay_out(pieces, title=None):
    """The lines of some text as (text, is a heading)."""
    wrap = Wrap()
    if title is not None:
        wrap.title(title)
    for piece in pieces:
        wrap.put(piece)
    wrap.close()
    assert all(len(line) == COLUMNS for line in wrap.lines)
    return [text_of(line) for line in wrap.lines]


def fill(text):
    """The lines one paragraph wraps to."""
    return [line for line, heading in lay_out([text]) if not heading]


def test_fill_breaks_at_spaces_and_keeps_every_word():
    text = b"The quick brown fox jumps over the lazy dog, twice, and then once more."
    lines = fill(text)
    assert all(len(line) <= COLUMNS for line in lines)
    assert b" ".join(lines).split() == text.split()
    # Greedy: the next line's first word would not have fitted.
    for line, following in zip(lines, lines[1:]):
        assert len(line) + 1 + len(following.split()[0]) > COLUMNS


def test_fill_cuts_a_word_longer_than_a_line():
    word = b"x" * (2 * COLUMNS + 5)
    assert fill(b"ab " + word + b" cd") == [b"ab", word[:COLUMNS], word[:COLUMNS], b"xxxxx cd"]


def test_fill_of_a_word_that_just_fits():
    assert fill(b"a" * COLUMNS + b" b") == [b"a" * COLUMNS, b"b"]


def test_spaces_collapse_and_empty_text_is_no_lines():
    assert fill(b"  a   b  ") == [b"a b"]
    assert fill(b"   ") == []


def test_paragraphs_get_a_blank_line_between():
    assert lay_out([b"First one.\nSecond one.\n\n\nThird."]) == [
        (b"First one.", False), (b"", False), (b"Second one.", False), (b"", False),
        (b"Third.", False)]


def test_title_and_headings():
    assert lay_out(
        [b"Lead text.\n\n\n== History ==\n\n\n=== Early years ===\n\nIt began.\n"
         b"\n\n== See also ==\n\n\n== Notes ==\n\nA note."],
        title=b"Some Thing") == [
        (b"SOME THING", True), (b"", False),
        (b"Lead text.", False), (b"", False),
        (b"HISTORY", True), (b"", False),
        (b"Early years", True),
        (b"It began.", False), (b"", False),
        (b"SEE ALSO", True), (b"", False),
        (b"NOTES", True),
        (b"A note.", False),
    ]


def test_a_long_heading_wraps_and_keeps_its_colour():
    assert lay_out([b"== A heading that is longer than one line of text ==\nBody."]) == [
        (b"A HEADING THAT IS LONGER", True), (b"THAN ONE LINE OF TEXT", True), (b"Body.", False)]


def test_text_with_equals_signs_is_not_a_heading():
    lines = lay_out([b"a == b\n====\n= x =\n"])
    assert [heading for _, heading in lines] == [False] * 5


def test_pieces_of_any_size_give_the_same_article():
    text = (b"Lead paragraph with several words in it, enough to wrap twice over.\n\n\n"
            b"== Section ==\nBody of the section, also long enough to need wrapping.\n"
            b"=== Deeper ===\nLast words")
    whole = lay_out([text], title=b"T")
    generator = random.Random(4)
    for _ in range(50):
        pieces, position = [], 0
        while position < len(text):
            size = generator.randint(1, 12)
            pieces.append(text[position:position + size])
            position += size
        assert lay_out(pieces, title=b"T") == whole
    assert lay_out([text[i:i + 1] for i in range(len(text))], title=b"T") == whole


def test_a_paragraph_longer_than_can_be_held_is_laid_out_as_it_comes():
    # Thousands of words and no newline. Nothing is held past the limit,
    # lines come out before the end, and it is still one paragraph: every
    # word in order, none cut, no blank line in the middle.
    count = 3 * PARAGRAPH // 5
    wrap = Wrap()
    wrap.put(b"Before.\n")
    for number in range(count):
        wrap.put(b"w%04d " % number)
        assert wrap.held <= PARAGRAPH
    early = len(wrap.lines)
    wrap.put(b"\nAfter.")
    wrap.close()
    lines = [text_of(line)[0] for line in wrap.lines]
    assert early > 100
    assert lines[:2] == [b"Before.", b""] and lines[-2:] == [b"", b"After."]
    body = lines[2:-2]
    assert b"" not in body
    assert b" ".join(body).split() == [b"w%04d" % number for number in range(count)]
    assert all(len(line) <= COLUMNS for line in body)


def test_a_word_longer_than_can_be_held_does_not_stop_it():
    wrap = Wrap()
    wrap.put(b"x" * (2 * PARAGRAPH + 100) + b" end\nNext.")
    wrap.close()
    lines = [text_of(line)[0] for line in wrap.lines]
    assert b"".join(lines[:-3]).count(b"x") + lines[-3].count(b"x") == 2 * PARAGRAPH + 100
    assert lines[-3].endswith(b"end") and lines[-2:] == [b"", b"Next."]


def test_another_width():
    wrap = Wrap(16)
    wrap.title(b"Wide and narrow")
    wrap.put(b"The quick brown fox jumps over the lazy dog.")
    wrap.close()
    assert [text_of(line)[0] for line in wrap.lines] == [
        b"WIDE AND NARROW", b"", b"The quick brown", b"fox jumps over", b"the lazy dog."]


# --- to ASCII ----------------------------------------------------------------------

def test_what_ascii_is_made_of_other_characters():
    assert nesp.to_ascii(ord("A")) == b"A" and nesp.to_ascii(0x0A) == b"\n"
    assert nesp.to_ascii(0x09) == b" " and nesp.to_ascii(0x0D) == b"" and nesp.to_ascii(0x7F) == b""
    assert [nesp.to_ascii(ord(char)) for char in "éÅŁßæ…€“’–×"] == [
        b"e", b"A", b"L", b"ss", b"ae", b"...", b"EUR", b'"', b"'", b"-", b"x"]
    assert nesp.to_ascii(0x0301) == b"" and nesp.to_ascii(0x200B) == b""     # marks; zero width
    assert nesp.to_ascii(ord("Д")) is None and nesp.to_ascii(0x1F3AE) is None


def plain(text):
    """What the extractor should make of a string, worked out a character
    at a time."""
    out, unknown = bytearray(), False
    for char in text:
        mapped = nesp.to_ascii(ord(char))
        if mapped is None:
            if not unknown:
                out += b"?"
            unknown = True
        elif mapped:
            out += mapped
            unknown = False
    return bytes(out)


# --- a reply from the API ----------------------------------------------------------

def extract(body, chunk=None):
    """(title, text, found, done) from a reply's body."""
    extractor = Extract()
    size = chunk or len(body) or 1
    for start in range(0, len(body), size):
        extractor.feed(body[start:start + size])
    return extractor.title, extractor.text, extractor.found, extractor.done


def reply(title, text, ensure_ascii=False):
    page = {"pageid": 1, "ns": 0, "title": title, "index": 1, "extract": text}
    return json.dumps({"batchcomplete": True, "query": {"pages": [page]}},
                      ensure_ascii=ensure_ascii, separators=(",", ":")).encode("utf-8")


def test_the_address_escapes_the_query():
    url = nesp.wiki_url("Nintendo Entertainment System")
    assert url.startswith("https://en.wikipedia.org/w/api.php?action=query&generator=search")
    assert "&prop=extracts&explaintext=1&format=json&formatversion=2" in url
    assert url.endswith("&gsrsearch=Nintendo%20Entertainment%20System")
    assert nesp.wiki_url("a&b=c?/#").endswith("=a%26b%3Dc%3F%2F%23")
    assert nesp.wiki_url("Pokémon").endswith("=Pok%C3%A9mon")
    assert nesp.wiki_url("A-b_c.d~9").endswith("=A-b_c.d~9")


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
            "1983–1985 ¥14,800 5×3 wait… æon straße 20 km")
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
    assert extract(b'{"extract":"a\\u 0a1b"}')[1] == b"a?b"     # four hex digits or nothing


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


def test_a_title_longer_than_is_kept_is_cut_not_overrun():
    title, text, _, _ = extract(reply("t" * 1000, "Body"))
    assert title == b"t" * 128 and text == b"Body"


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
        extractor = Extract()
        position = 0
        while position < len(body):
            size = generator.randint(1, 300)
            extractor.feed(body[position:position + size])
            position += size
        assert (extractor.title, extractor.text, extractor.found, extractor.done) == expected
