"""The whole link: the link ROM on py65 and the Stick's own server code,
joined by a cycle-exact serial line (wire.py).

A Host stands in for the Stick's main loop: it polls the server and, when
a search comes, "fetches" for a while and then finishes it. Whatever the
line and the host do, the reader must show the right text or wait.
"""

import random

import pytest
from console import FRAME_CYCLES, PAD_A, PAD_B, PAD_DOWN, PAD_SELECT, PAD_START, PAD_UP
from drive import (STATE_LOADING, STATE_READER, STATE_SEARCH, WINDOW_ROWS, check_reader_frame,
                   numbered_article, open_reader, position, run_until, tap)
from wire import link, ms

from neswiki import proto
from neswiki.linkrate import COLUMNS, PERIOD, REPLY_SIZE, TO_NES_BITS
from neswiki.server import Server
from neswiki.wrap import Article

DEFAULT = b"Nintendo Entertainment System"
STATUS_ROW = 24
REPLY_CYCLES = REPLY_SIZE * TO_NES_BITS * PERIOD


class Host:
    """The Stick's loop: poll the link, and carry out searches. A search
    takes `fetch_polls` polls and ends as `outcome` says: a list of lines
    for an article, or (state, message)."""

    def __init__(self, console, outcome, fetch_polls=40, trickle=0, **options):
        self.article = Article(1200)
        self.outcome = outcome
        self.fetch_polls = fetch_polls
        self.trickle = trickle          # cycles between lines, as an article arrives
        self.arriving = None
        self.next_line = 0
        self.console = console
        self.fetching = 0
        self.searches = []
        online = options.pop("online", True)
        self.server, self.port = link(
            console, lambda port: Server(self.article, port, online=online), **options)
        console.host = self.poll

    def poll(self):
        self.server.poll()
        query = self.server.take_search()
        if query is not None:
            self.searches.append(query)
            self.fetching = self.fetch_polls
            self.arriving = None
            self.article.clear()
        elif self.arriving is not None:
            if self.console.now >= self.next_line:
                self.next_line = self.console.now + self.trickle
                self.article.add(self.arriving.pop(0).rstrip(b" "))
                if not self.arriving:
                    self.arriving = None
                    self.fetching = 0
                    self.server.finish(proto.READY)
        elif self.fetching:
            self.fetching -= 1
            if not self.fetching:
                if isinstance(self.outcome, list) and self.trickle:
                    self.arriving = list(self.outcome)
                elif isinstance(self.outcome, list):
                    for line in self.outcome:
                        self.article.add(line.rstrip(b" "))
                    self.server.finish(proto.READY)
                else:
                    self.server.finish(*self.outcome)


@pytest.fixture
def linked(link_console):
    def make(outcome, **options):
        console = link_console()
        return console, Host(console, outcome, **options)
    return make


def status(console):
    return console.text(1, STATUS_ROW, 2, COLUMNS).strip()


def hold(console, lines, pad, frames):
    since = len(console.frames)
    console.run(frames, pad=pad)
    shown = console.frames[since:]
    for frame in shown:
        check_reader_frame(frame, lines)
    return shown


def end_of(lines):
    return 8 * (len(lines) - WINDOW_ROWS)


def moves(frames):
    places = [position(frame) for frame in frames]
    return [after - before for before, after in zip(places, places[1:])]


def test_a_search_brings_up_the_article(linked):
    lines = numbered_article(90)
    c, host = linked(lines)
    open_reader(c)
    assert host.searches == [DEFAULT]
    assert host.server.search_id == 1
    assert c.word("total") == 90
    frame = c.frames[-1]
    check_reader_frame(frame, lines)
    assert position(frame) == 0
    # Lines 0 to 22 before the reader came up, then five more in hand.
    c.run(10)
    assert host.server.line_requests == WINDOW_ROWS + 1 + 5
    assert c.word("hi") == 28


def test_scrolling_never_waits_for_a_stick_that_answers_in_a_millisecond(linked):
    lines = numbered_article(140)
    c, host = linked(lines)
    open_reader(c)
    shown = hold(c, lines, PAD_DOWN, end_of(lines) // 2 + 10)
    assert moves(shown)[1:end_of(lines) // 2] == [2] * (end_of(lines) // 2 - 1)
    assert position(shown[-1]) == end_of(lines)
    shown = hold(c, lines, PAD_UP, 200)
    assert moves(shown)[3:190] == [-2] * 187
    # Not one exchange failed: every line asked for was drawn.
    assert host.server.unanswered == 0
    drawn = sum(1 for frame in c.frames + [c.frame]
                if frame.vblank_writes and frame.vblank_writes[0] < 0x2400)
    assert host.server.line_requests == drawn


def test_pages_glide_at_full_speed(linked):
    lines = numbered_article(200)
    c, host = linked(lines)
    open_reader(c)
    for _ in range(4):
        c.run(1, pad=PAD_A)
        shown = hold(c, lines, 0, 44)
        assert [step for step in moves(shown) if step] == [4] * 40
    c.run(1, pad=PAD_B)
    shown = hold(c, lines, 0, 44)
    assert [step for step in moves(shown) if step] == [-4] * 40


def test_each_line_is_asked_for_once(linked):
    lines = numbered_article(140)
    c, host = linked(lines)
    open_reader(c)
    asked = []
    poll = host.server.poll

    def watch():
        before = host.server.line_requests
        poll()
        if host.server.line_requests != before:
            asked.append(host.server.reply[2] | host.server.reply[3] << 8)
    host.server.poll = watch
    hold(c, lines, PAD_DOWN, 300)
    assert asked == list(range(asked[0], asked[0] + len(asked)))


@pytest.mark.parametrize("turnaround_ms", [0.2, 1.0, 2.5, 4.0, 5.0])
def test_replies_within_the_budget_all_land(linked, turnaround_ms):
    lines = numbered_article(120)
    c, host = linked(lines, turnaround=ms(turnaround_ms))
    open_reader(c)
    shown = hold(c, lines, PAD_DOWN, 250)
    assert moves(shown)[1:] == [2] * 248
    # Every reply ended before the vblank that would have cut it off.
    for at, data in host.port.sent:
        frame_end = (at // FRAME_CYCLES + 1) * FRAME_CYCLES
        assert at + REPLY_CYCLES < frame_end


def test_the_budget_is_what_the_plan_says(linked):
    """The longest turnaround at which a line's reply still lands, found by
    trying. docs/PROTOCOL.md says about 5.2 ms; nes-jukebox's Stick took 3.9
    at worst."""
    def lands(turnaround_ms):
        lines = numbered_article(60)
        c, host = linked(lines)
        open_reader(c)
        host.port.turnaround = ms(turnaround_ms)
        shown = hold(c, lines, PAD_DOWN, 60)
        return moves(shown)[1:] == [2] * 58
    budget = max(step / 4 for step in range(16, 40) if lands(step / 4))
    assert 4.75 <= budget <= 5.75, budget


def test_a_stick_that_is_always_late_stops_the_scroll_and_shows_nothing_wrong(linked):
    lines = numbered_article(120)
    c, host = linked(lines)
    open_reader(c)
    hold(c, lines, PAD_DOWN, 20)
    host.port.turnaround = ms(9.0)
    shown = hold(c, lines, PAD_DOWN, 150)
    at = position(shown[-1])
    assert moves(shown)[-80:] == [0] * 80
    assert 8 * 5 <= at <= 40 + 8 * 6        # as far as the lines in hand went
    host.port.turnaround = ms(1.0)
    shown = hold(c, lines, PAD_DOWN, 60)
    assert position(shown[-1]) > at + 100


def test_replies_of_any_lateness_only_slow_it(linked):
    generator = random.Random(3)
    lines = numbered_article(120)
    c, host = linked(lines, turnaround=lambda: ms(generator.uniform(0.3, 9.0)))
    open_reader(c)
    shown = hold(c, lines, PAD_DOWN, 900)
    assert position(shown[-1]) == end_of(lines)
    assert set(moves(shown)) <= {0, 1, 2} and 0 in moves(shown)[:300]
    hold(c, lines, PAD_UP, 300)


def damage(generator, share):
    def to_console(data):
        roll = generator.random()
        if roll > share:
            return data
        kind = generator.randrange(5)
        if kind == 0:
            return None                                     # lost whole
        if kind == 1:
            return data[:generator.randrange(1, len(data))]     # cut short
        if kind == 2:
            at = generator.randrange(len(data))
            return data[:at] + data[at + 1:]                # a byte dropped
        if kind == 3:
            return bytes((generator.randrange(256),)) + data    # a byte of junk ahead
        at = generator.randrange(len(data))
        return data[:at] + bytes((data[at] ^ 1 << generator.randrange(8),)) + data[at + 1:]
    return to_console


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_damaged_and_lost_replies_never_reach_the_screen(linked, seed):
    generator = random.Random(seed)
    lines = numbered_article(110)
    c, host = linked(lines, to_console=damage(generator, 0.35))
    c.run(3)
    tap(c, PAD_START)
    run_until(c, STATE_READER, limit=900)
    c.run(2)
    pads = (PAD_DOWN, PAD_DOWN, PAD_UP, PAD_A, PAD_B, 0)
    for _ in range(40):
        hold(c, lines, generator.choice(pads), generator.randint(5, 50))
    shown = hold(c, lines, PAD_DOWN, 700)
    assert position(shown[-1]) == end_of(lines)


@pytest.mark.parametrize("error", [-0.02, 0.02])
def test_a_stick_whose_clock_is_two_percent_out(linked, error):
    lines = numbered_article(80)
    c, host = linked(lines, clock_error=error)
    open_reader(c)
    shown = hold(c, lines, PAD_DOWN, 250)
    assert position(shown[-1]) == end_of(lines)
    assert host.server.decoder.discarded > 0    # the controller read's junk byte


def test_a_stick_that_goes_deaf_and_comes_back(linked):
    lines = numbered_article(120)
    c, host = linked(lines)
    open_reader(c)
    hold(c, lines, PAD_DOWN, 30)
    host.port.deaf = True
    shown = hold(c, lines, PAD_DOWN, 200)
    assert moves(shown)[-100:] == [0] * 100
    host.port.deaf = False
    host.port.search_from = c.now               # what it missed is gone
    shown = hold(c, lines, PAD_DOWN, 100)
    assert moves(shown)[-50:] == [2] * 50
    assert c.byte("state") == STATE_READER


def test_a_stick_that_lost_the_article_sends_the_console_back_to_search(linked):
    lines = numbered_article(120)
    c, host = linked(lines)
    open_reader(c)
    hold(c, lines, PAD_DOWN, 30)
    # Switched off and on: a new server, holding nothing.
    Host(c, lines)
    c.run(10, pad=PAD_DOWN)
    c.run(10, pad=0)
    assert c.byte("state") == STATE_SEARCH
    assert status(c) == "THE STICK LOST THE ARTICLE"
    assert c.frames[-1].split is None


def test_the_same_search_after_a_console_reset_needs_no_fetch(linked, link_console):
    lines = numbered_article(60)
    c, host = linked(lines)
    open_reader(c)
    again = link_console()                      # reset: ids count from 1 again
    again.joy2_level, again.joy2_quiet_until = host.port.wire.level, host.port.wire.quiet_until
    host.port.console = again
    host.port.tap.__init__()
    host.port.search_from = 0.0
    again.on_joy1 = host.port.tap.write
    again.host, again.host_every = host.poll, c.host_every
    # The wire's clock is the first console's: start the second where it is.
    again.mpu.processorCycles = c.now
    again.frame.start = c.now
    again.next_vblank = c.now + FRAME_CYCLES
    open_reader(again)
    assert host.searches == [DEFAULT]           # fetched once
    check_reader_frame(again.frames[-1], lines)


def test_a_second_search_fetches_again(linked):
    lines = numbered_article(60)
    c, host = linked(lines)
    open_reader(c)
    tap(c, PAD_SELECT)
    tap(c, PAD_B)                               # ...Syste
    tap(c, PAD_START)
    run_until(c, STATE_READER)
    assert host.searches == [DEFAULT, DEFAULT[:-1]]
    assert host.server.search_id == 2


@pytest.mark.parametrize("outcome, shown", [
    ((proto.NOT_FOUND,), "NO ARTICLE FOUND"),
    ((proto.ERROR, "http 503"), "HTTP 503"),
    ((proto.ERROR,), ""),
])
def test_searches_that_fail_say_so(linked, outcome, shown):
    c, host = linked(outcome)
    c.run(3)
    tap(c, PAD_START)
    c.run(8)
    assert status(c) == "SEARCHING..."
    run_until(c, STATE_SEARCH)
    c.run(4)
    assert status(c) == shown
    # And the keyboard is back: a new search can be made.
    host.outcome = numbered_article(30)
    tap(c, PAD_START)
    run_until(c, STATE_READER)


def test_a_stick_with_no_wifi_says_so(linked):
    c, host = linked(numbered_article(30), online=False)
    c.run(3)
    tap(c, PAD_START)
    run_until(c, STATE_LOADING)
    run_until(c, STATE_SEARCH)
    c.run(4)
    assert status(c) == "THE STICK HAS NO WI-FI" and host.searches == []


def test_no_stick_at_all_gives_up_after_half_a_minute(link_console):
    c = link_console()
    c.run(3)
    tap(c, PAD_START)
    c.run(1700)
    assert c.byte("state") == STATE_LOADING and status(c) == "SEARCHING..."
    c.run(200)
    assert c.byte("state") == STATE_SEARCH
    assert status(c) == "NO ANSWER FROM THE STICK"


def test_a_stick_too_busy_to_answer_for_a_while_is_waited_for(linked):
    lines = numbered_article(40)
    c, host = linked(lines, fetch_polls=10)
    c.run(3)
    host.port.deaf = True                       # in a TLS handshake, say
    tap(c, PAD_START)
    c.run(300)
    assert c.byte("state") == STATE_LOADING
    host.port.deaf = False
    run_until(c, STATE_READER)
    c.run(2)
    check_reader_frame(c.frames[-1], lines)
    assert host.searches == [DEFAULT]           # the pile of repeats was one search


def test_a_lost_reply_to_the_search_is_asked_for_again(linked):
    lines = numbered_article(40)
    drop = [True, True, True]
    c, host = linked(lines, to_console=lambda data: None if drop and drop.pop() else data)
    open_reader(c)
    assert host.searches == [DEFAULT] and not drop


def test_the_line_rests_at_mark_and_requests_keep_clear_of_the_controller_read(linked):
    lines = numbered_article(80)
    c, host = linked(lines)
    c.joy1_writes = []
    open_reader(c)
    c.run(60, pad=PAD_DOWN)
    tap_line = host.port.tap
    lows = [(tap_line.times[index], tap_line.times[index + 1])
            for index in range(1, len(tap_line.times) - 1) if tap_line.levels[index] == 0]
    reads = [(start, end) for start, end in lows if 90 <= end - start <= 100]
    assert len(reads) >= 60                     # one a frame, 94 cycles each
    # A UART takes a read for a byte, which ends ten bits after the read
    # began. The line then rests for a byte's length or more before a
    # request, so the two are never run together.
    gaps = []
    for start, end in reads:
        after = min((low for low, _ in lows if low > end), default=float("inf"))
        gaps.append(after - start)
    assert min(gaps) > 2 * 10 * PERIOD, min(gaps)
    assert tap_line.levels[-1] == 1
    # Every request the Stick's decoder was given, it found.
    sent = sum(1 for data in host.port.received if b"\x57" in data)
    assert host.server.requests >= len(host.port.sent) and sent >= host.server.requests


def test_reading_starts_before_the_article_has_all_arrived(linked):
    lines = numbered_article(130)
    c, host = linked(lines, trickle=200000)     # cycles between lines: about 9 lines a second
    open_reader(c)
    arrived = host.article.count
    assert 28 <= arrived < 60 and host.server.state == proto.FETCHING
    assert c.word("total") <= arrived and c.byte("more")
    check_reader_frame(c.frames[-1], lines)
    # Held down, the window follows the article as it comes in, waiting at
    # what is so far its end, and stops at its real end when all is in.
    waited = False
    shown = []
    for _ in range(40):
        shown = hold(c, lines, PAD_DOWN, 60)
        waited = waited or (0 in moves(shown) and host.server.state == proto.FETCHING)
        assert c.word("total") <= host.article.count
        if host.server.state == proto.READY and position(shown[-1]) == end_of(lines):
            break
    assert waited and position(shown[-1]) == end_of(lines)
    assert c.word("total") == 130 and not c.byte("more")
    assert shown[-1].lines[-1] == lines[-1]
    assert c.oam[4] == 63 + 168                 # the thumb is at the bottom


def test_an_article_that_stops_arriving_can_still_be_read(linked):
    lines = numbered_article(130)
    c, host = linked(lines, trickle=200000)
    open_reader(c)
    hold(c, lines, PAD_DOWN, 100)
    host.next_line = float("inf")               # the fetch hangs
    have = host.article.count
    shown = hold(c, lines, PAD_DOWN, 600)
    assert position(shown[-1]) == 8 * (have - WINDOW_ROWS)
    shown = hold(c, lines, PAD_UP, 100)
    assert set(moves(shown)[5:]) <= {0, -2} and position(shown[-1]) < 8 * (have - WINDOW_ROWS) - 100
