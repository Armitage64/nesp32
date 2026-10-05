"""Laying text out in lines of COLUMNS characters."""

import random

from neswiki.linkrate import COLUMNS
from neswiki.wrap import CUT_TEXT, HEADING, PARAGRAPH_MAX, Article, Wrapper, fill


def lines_of(article):
    """Each line as (text, is a heading)."""
    out = []
    for index in range(article.count):
        line = article.line(index)
        assert len(line) == COLUMNS
        heading = bool(line[0] & HEADING)
        text = bytes(char & 0x7F for char in line).rstrip()
        # A heading has the flag on every character, body text on none.
        assert all(bool(char & HEADING) == heading for char in line[:len(text)])
        out.append((text, heading))
    return out


def lay_out(pieces, capacity=200, title=None):
    article = Article(capacity)
    wrapper = Wrapper(article)
    if title is not None:
        wrapper.title(title)
    for piece in pieces:
        wrapper.put(piece)
    wrapper.close()
    return article


def test_fill_breaks_at_spaces_and_keeps_every_word():
    text = b"The quick brown fox jumps over the lazy dog, twice, and then once more."
    lines = list(fill(text))
    assert all(len(line) <= COLUMNS for line in lines)
    assert b" ".join(lines).split() == text.split()
    # Greedy: the next line's first word would not have fitted.
    for line, following in zip(lines, lines[1:]):
        assert len(line) + 1 + len(following.split()[0]) > COLUMNS


def test_fill_cuts_a_word_longer_than_a_line():
    word = b"x" * (2 * COLUMNS + 5)
    assert list(fill(b"ab " + word + b" cd")) == [
        b"ab", word[:COLUMNS], word[:COLUMNS], b"xxxxx cd"]


def test_fill_of_a_word_that_just_fits():
    assert list(fill(b"a" * COLUMNS + b" b")) == [b"a" * COLUMNS, b"b"]


def test_spaces_collapse_and_empty_text_is_no_lines():
    assert list(fill(b"  a   b  ")) == [b"a b"]
    assert list(fill(b"   ")) == []


def test_paragraphs_get_a_blank_line_between():
    article = lay_out([b"First one.\nSecond one.\n\n\nThird."])
    assert lines_of(article) == [(b"First one.", False), (b"", False), (b"Second one.", False),
                                 (b"", False), (b"Third.", False)]


def test_title_and_headings():
    article = lay_out(
        [b"Lead text.\n\n\n== History ==\n\n\n=== Early years ===\n\nIt began.\n"
         b"\n\n== See also ==\n\n\n== Notes ==\n\nA note."],
        title=b"Some Thing")
    assert lines_of(article) == [
        (b"SOME THING", True), (b"", False),
        (b"Lead text.", False), (b"", False),
        (b"HISTORY", True), (b"", False),
        (b"Early years", True),
        (b"It began.", False), (b"", False),
        (b"SEE ALSO", True), (b"", False),
        (b"NOTES", True),
        (b"A note.", False),
    ]
    assert article.title == b"Some Thing"


def test_a_long_heading_wraps_and_keeps_its_colour():
    article = lay_out([b"== A heading that is longer than one line of text ==\nBody."])
    assert lines_of(article) == [(b"A HEADING THAT IS LONGER", True),
                                 (b"THAN ONE LINE OF TEXT", True), (b"Body.", False)]


def test_text_with_equals_signs_is_not_a_heading():
    article = lay_out([b"a == b\n====\n= x =\n"])
    assert [heading for _, heading in lines_of(article)] == [False] * 5


def test_pieces_of_any_size_give_the_same_article():
    text = (b"Lead paragraph with several words in it, enough to wrap twice over.\n\n\n"
            b"== Section ==\nBody of the section, also long enough to need wrapping.\n"
            b"=== Deeper ===\nLast words")
    whole = lines_of(lay_out([text], title=b"T"))
    generator = random.Random(4)
    for _ in range(50):
        pieces, position = [], 0
        while position < len(text):
            size = generator.randint(1, 12)
            pieces.append(text[position:position + size])
            position += size
        assert lines_of(lay_out(pieces, title=b"T")) == whole
    assert lines_of(lay_out([text[i:i + 1] for i in range(len(text))], title=b"T")) == whole


def test_a_full_article_ends_with_the_cut_line():
    article = lay_out([b"word\n" * 50], capacity=10)
    lines = lines_of(article)
    assert article.count == 10 and article.full
    assert lines[-1] == (CUT_TEXT, True)
    assert lines[:3] == [(b"word", False), (b"", False), (b"word", False)]
    assert article.add(b"more") is False and article.count == 10


def test_an_article_is_reused():
    article = lay_out([b"word\n" * 50], capacity=10)
    article.clear()
    wrapper = Wrapper(article)
    wrapper.put(b"Short.")
    wrapper.close()
    assert lines_of(article) == [(b"Short.", False)]
    assert not article.full and article.title == b""


def test_a_run_with_no_newline_is_laid_out_before_it_grows_without_limit():
    article = Article(1000)
    wrapper = Wrapper(article)
    for _ in range(3 * PARAGRAPH_MAX // 5):
        wrapper.put(b"word ")
        assert len(wrapper.paragraph) <= PARAGRAPH_MAX + 5
    assert article.count > 0
    wrapper.close()
    words = b" ".join(text for text, _ in lines_of(article)).split()
    assert words == [b"word"] * (3 * PARAGRAPH_MAX // 5)
