"""The reader on the standalone ROM: what is on the screen is always the
article at the place the scroll says, whatever the controller and the host
do."""

import random

import pytest
from console import (PAD_A, PAD_B, PAD_DOWN, PAD_LEFT, PAD_RIGHT, PAD_SELECT, PAD_START, PAD_UP)
from drive import (BLANK, STATE_OPENING, STATE_READER, STATE_SEARCH, WINDOW_ROWS,
                   check_reader_frame, expected_lines, numbered_article, open_reader, position,
                   run_until, tap)

SPRITE_HIDDEN = 0xF0
THUMB_TOP, THUMB_TRAVEL = 63, 168
PAGE = 8 * (WINDOW_ROWS - 2)


def reader_frames(console, since):
    return console.frames[since:]


def hold(console, article, pad, frames):
    """Hold buttons for some frames, checking each. Returns the frames."""
    since = len(console.frames)
    console.run(frames, pad=pad)
    shown = console.frames[since:]
    for frame in shown:
        check_reader_frame(frame, article)
    return shown


def end_of(article):
    return 8 * max(0, len(article) - WINDOW_ROWS)


def test_opening_shows_the_top_of_the_article(console, article):
    c = console()
    open_reader(c)
    frame = c.frames[-1]
    check_reader_frame(frame, article)
    assert (frame.top, frame.fine) == (0, 0)
    assert bytes(tile & 0x7F for tile in frame.lines[0]).rstrip() == b"NESPEDIA"
    assert all(tile & 0x80 for tile in frame.lines[0][:8])      # a heading: second colour
    assert c.word("total") == len(article)


def test_the_search_screen_stays_up_until_the_window_is_full(console, article):
    c = console()
    c.run(3)
    tap(c, PAD_START)
    run_until(c, STATE_OPENING)
    assert c.text(1, 24, 2, 28).strip() == "SEARCHING..."
    run_until(c, STATE_READER)
    c.run(2)
    assert c.text(1, 24, 2, 28).strip() == "LOADING..."
    splits = [frame.split is not None for frame in c.frames]
    first = splits.index(True)
    assert not any(splits[:first]) and all(splits[first:])
    check_reader_frame(c.frames[first], article)


def test_down_scrolls_two_pixels_a_frame_to_the_end(console, article):
    c = console()
    open_reader(c)
    end = end_of(article)
    shown = hold(c, article, PAD_DOWN, end // 2 + 20)
    places = [position(frame) for frame in shown]
    steps = [after - before for before, after in zip(places, places[1:])]
    assert set(steps) <= {0, 2}
    # The host is never waited for: once the press is read, every frame
    # moves until the end.
    assert steps[:end // 2] == [0] + [2] * (end // 2 - 1)
    assert places[-1] == end and steps[-5:] == [0] * 5
    assert bytes(shown[-1].lines[-1]) == article[-1]


def test_up_scrolls_back_to_the_top(console, article):
    c = console()
    open_reader(c)
    hold(c, article, PAD_DOWN, 200)
    shown = hold(c, article, PAD_UP, 220)
    places = [position(frame) for frame in shown]
    steps = [after - before for before, after in zip(places, places[1:])]
    # The press is read a frame after it is made, and what it does is seen
    # the frame after that: the first two frames still show Down's doing.
    assert set(steps[2:]) <= {0, -2}
    assert places[-1] == 0 and steps[2:152] == [-2] * 150


def test_a_page_glides_four_pixels_a_frame(console, article):
    c = console()
    open_reader(c)
    for button in (PAD_A, PAD_RIGHT):
        before = position(c.frames[-1])
        c.run(1, pad=button)
        shown = hold(c, article, 0, 60)
        places = [position(frame) for frame in shown]
        assert places[-1] == before + PAGE
        steps = [b - a for a, b in zip(places, places[1:]) if b != a]
        assert steps == [4] * (PAGE // 4)
        # Two lines of the last page are still in view.
        assert shown[-1].lines[0] == article[before // 8 + WINDOW_ROWS - 2]
    for button in (PAD_LEFT, PAD_LEFT):
        before = position(c.frames[-1])
        c.run(1, pad=button)
        shown = hold(c, article, 0, 60)
        assert position(shown[-1]) == before - PAGE
    assert position(c.frames[-1]) == 0


def test_pages_stop_at_the_ends(console, article):
    c = console()
    open_reader(c)
    c.run(1, pad=PAD_LEFT)
    assert all(position(frame) == 0 for frame in hold(c, article, 0, 20))
    assert c.byte("glide") == 0
    for _ in range(len(article) // (WINDOW_ROWS - 2) + 1):
        c.run(1, pad=PAD_A)
        hold(c, article, 0, 45)
    assert position(c.frames[-1]) == end_of(article)
    assert c.byte("glide") == 0


def test_scrolling_by_hand_ends_a_glide(console, article):
    c = console()
    open_reader(c)
    c.run(1, pad=PAD_A)
    hold(c, article, 0, 5)
    hold(c, article, PAD_UP, 4)
    hold(c, article, 0, 2)          # the last of Up is seen
    at = position(c.frames[-1])
    assert all(position(frame) == at for frame in hold(c, article, 0, 20))


def test_start_goes_back_to_the_top(console, article):
    c = console()
    open_reader(c)
    hold(c, article, PAD_DOWN, 300)
    assert position(c.frames[-1]) > 400
    tap(c, PAD_START)
    assert c.byte("state") == STATE_OPENING
    run_until(c, STATE_READER)
    c.run(2)
    check_reader_frame(c.frames[-1], article)
    assert position(c.frames[-1]) == 0
    # At the top already, Start does nothing.
    tap(c, PAD_START)
    assert c.byte("state") == STATE_READER


@pytest.mark.parametrize("button", (PAD_B, PAD_SELECT), ids=("b", "select"))
def test_b_and_select_go_back_to_the_search_and_the_article_opens_again(console, article, button):
    # Built by itself: on the cartridge, Select is its menu.
    c = console()
    open_reader(c)
    hold(c, article, PAD_DOWN, 50)
    tap(c, button)
    c.run(3)
    assert c.byte("state") == STATE_SEARCH
    assert c.frames[-1].split is None and c.frames[-1].header == 0x0400
    assert c.text(1, 24, 2, 28).strip() == ""
    assert c.oam[4] == SPRITE_HIDDEN
    tap(c, PAD_START)
    run_until(c, STATE_READER)
    c.run(2)
    check_reader_frame(c.frames[-1], article)
    assert position(c.frames[-1]) == 0


def test_the_thumb_follows_the_window(console, article):
    c = console()
    open_reader(c)
    assert c.oam[4:8] == bytes((THUMB_TOP, 2, 0, 244))
    places = []
    for _ in range(end_of(article) // 2 + 10):
        c.run(1, pad=PAD_DOWN)
        places.append(c.oam[4])
    assert places == sorted(places)
    assert places[-1] == THUMB_TOP + THUMB_TRAVEL
    top = c.word("top")
    assert top == len(article) - WINDOW_ROWS
    hold(c, article, PAD_UP, 4 * (top // 2))    # half way back
    assert abs(c.oam[4] - (THUMB_TOP + THUMB_TRAVEL // 2)) <= 1


@pytest.mark.parametrize("length", [1, 5, 21, 22, 23, 24, 30, 31, 52])
def test_articles_of_awkward_lengths(console, length):
    lines = numbered_article(length)
    c = console()
    c.load_article(lines)
    open_reader(c)
    frame = c.frames[-1]
    check_reader_frame(frame, lines)
    assert frame.lines == expected_lines(lines, 0, WINDOW_ROWS)
    if length < WINDOW_ROWS:
        assert frame.lines[length:] == [BLANK] * (WINDOW_ROWS - length)
    shown = hold(c, lines, PAD_DOWN, 8 * length // 2 + 30)
    assert position(shown[-1]) == end_of(lines)
    assert (c.oam[4] == SPRITE_HIDDEN) == (length <= WINDOW_ROWS)
    shown = hold(c, lines, PAD_UP, 8 * length // 2 + 30)
    assert position(shown[-1]) == 0
    c.run(1, pad=PAD_A)
    shown = hold(c, lines, 0, 60)
    assert position(shown[-1]) == min(PAGE, end_of(lines))


def test_an_article_of_more_than_256_lines(console):
    lines = numbered_article(585)       # all the ROM has room for
    c = console()
    c.load_article(lines)
    open_reader(c)
    for _ in range(585 // (WINDOW_ROWS - 2) + 1):
        c.run(1, pad=PAD_A)
        hold(c, lines, 0, 42)
    frame = c.frames[-1]
    assert position(frame) == end_of(lines) and frame.lines[-1] == lines[-1]
    assert c.oam[4] == THUMB_TOP + THUMB_TRAVEL
    shown = hold(c, lines, PAD_UP, 300)
    assert end_of(lines) - 600 <= position(shown[-1]) <= end_of(lines) - 590


def test_a_host_that_often_fails_only_slows_the_scroll(console, article):
    generator = random.Random(11)
    c = console()
    open_reader(c)
    c.on_line = lambda console: generator.random() < 0.7
    end = end_of(article)
    places = []
    for _ in range(40):
        places += [position(frame) for frame in hold(c, article, PAD_DOWN, 100)]
        if places[-1] == end:
            break
    assert places[-1] == end, "never reached the end"
    steps = [b - a for a, b in zip(places, places[1:])]
    assert set(steps) <= {0, 1, 2} and 0 in steps[:400]     # it did wait
    shown = hold(c, article, PAD_UP, 400)
    assert position(shown[-1]) < end - 200


def test_a_host_that_stops_answering_stops_the_scroll_at_the_last_line_it_gave(console, article):
    c = console()
    open_reader(c)
    hold(c, article, PAD_DOWN, 40)
    c.on_line = lambda console: True
    shown = hold(c, article, PAD_DOWN, 200)
    places = [position(frame) for frame in shown]
    assert places[-1] == places[-100]               # it stopped
    assert places[-1] < 80 + 8 * 8                  # within the lines it had in hand
    c.on_line = None
    shown = hold(c, article, PAD_DOWN, 50)
    assert position(shown[-1]) > places[-1] + 80    # and went on when the host came back


def test_any_mix_of_buttons_and_failures_keeps_the_screen_right(console):
    lines = numbered_article(140)
    generator = random.Random(23)
    c = console()
    c.load_article(lines)
    open_reader(c)
    c.on_line = lambda console: generator.random() < 0.4
    moves = (PAD_DOWN, PAD_UP, PAD_A, PAD_LEFT, PAD_RIGHT, 0, PAD_DOWN | PAD_A, PAD_DOWN)
    seen = set()
    for _ in range(150):
        pad = generator.choice(moves)
        for frame in hold(c, lines, pad, generator.randint(1, 40)):
            seen.add(frame.top)
            # What the reader counts on: every line in view is in the ring.
        lo, hi, top = c.word("lo"), c.word("hi"), c.word("top")
        assert lo <= top and hi - lo == c.byte("held") <= 30
        assert hi >= min(c.word("limit"), top + WINDOW_ROWS)
        assert c.byte("lo_row") == lo % 30 and c.byte("hi_row") == hi % 30
    assert min(seen) == 0 and max(seen) == len(lines) - WINDOW_ROWS


def test_the_ring_keeps_lines_ahead_of_the_way_the_window_moves(console, article):
    c = console()
    open_reader(c)
    hold(c, article, PAD_DOWN, 200)
    hold(c, article, 0, 20)
    top = c.word("top")
    assert (c.word("lo"), c.word("hi")) == (top - 2, top + 28)
    hold(c, article, PAD_UP, 40)
    hold(c, article, 0, 20)
    top = c.word("top")
    assert (c.word("lo"), c.word("hi")) == (top - 5, top + 25)


def test_one_line_at_most_is_drawn_a_frame(console, article):
    c = console()
    open_reader(c)
    since = len(c.frames)
    hold(c, article, PAD_DOWN, 100)
    c.run(1, pad=PAD_LEFT)
    hold(c, article, 0, 50)
    for frame in c.frames[since:]:
        assert len(frame.vblank_writes) in (0, 28)
        assert len({address // 32 for address in frame.vblank_writes}) <= 1
