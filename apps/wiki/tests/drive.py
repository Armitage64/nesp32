"""Working the ROM's two screens from the tests."""

from console import PAD_START

STATE_SEARCH, STATE_LOADING, STATE_OPENING, STATE_READER = range(4)
WINDOW_ROWS = 22
RING_ROWS = 30
COLUMNS = 28
BLANK = b" " * COLUMNS
SPLIT_LINE = 63                 # the scanline above the article
HBLANK = range(257, 341)        # dots where the split's last write may land
HEADER_SCROLL = 0x0400          # nametable 1, top left


def tap(console, buttons):
    """Press and let go, a frame each."""
    console.run(1, pad=buttons)
    console.run(1, pad=0)


def run_until(console, state, limit=600):
    for _ in range(limit):
        if console.byte("state") == state:
            return
        console.run(1)
    raise AssertionError("state %d after %d frames, not %d"
                         % (console.byte("state"), limit, state))


def open_reader(console):
    """From power-on: search for the default, and wait for the reader."""
    console.run(3)
    tap(console, PAD_START)
    run_until(console, STATE_READER)
    console.run(2)              # a frame of the reader has been shown in full


def expected_lines(article, top, count):
    """Lines top .. top + count - 1; past the article's end they are blank."""
    return [article[index] if index < len(article) else BLANK
            for index in range(top, top + count)]


def position(frame):
    """A reader frame's place in the article, in pixels."""
    return 8 * frame.top + frame.fine


def check_reader_frame(frame, article):
    """A frame of the reader showed the header, then exactly the lines the
    ROM thought it was showing."""
    assert frame.header == HEADER_SCROLL
    assert frame.split is not None, "no split"
    assert frame.split_line == SPLIT_LINE and frame.split_dot in HBLANK, (
        "the split landed on line %s dot %s" % (frame.split_line, frame.split_dot))
    assert frame.split_y == position(frame) % (8 * RING_ROWS)
    count = WINDOW_ROWS + (1 if frame.fine else 0)
    assert frame.lines == expected_lines(article, frame.top, count), (
        "wrong text at line %d" % frame.top)
    # Nothing was drawn into a row that was in view.
    first_row = frame.split_y // 8
    rows = {(first_row + index) % RING_ROWS for index in range(count)}
    drawn = {(address - 0x2000) // 32 for address in frame.vblank_writes if address < 0x2400}
    assert not rows & drawn, "row %s drawn while in view" % sorted(rows & drawn)


def numbered_article(count):
    """An article whose every line says which it is."""
    return [("Line %04d of %04d" % (index, count)).ljust(COLUMNS).encode()
            for index in range(count)]
