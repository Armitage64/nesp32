"""The whole link: the link ROM on py65 and the Stick's own code, joined by
a cycle-exact serial line (wire.py).

The Stick's end is nesp32's firmware: its link and its WIKI service, built
for this computer (conftest.py). A Host stands in for the rest of a Stick
and for Wikipedia: it polls the link and, when a search is fetched, takes
a while and then feeds the service a reply. Whatever the line and the host
do, the reader must show the right text or wait.
"""

import json
import random
import urllib.parse

import nesp
import nesp_proto as p
import pytest
from console import FRAME_CYCLES, PAD_A, PAD_B, PAD_DOWN, PAD_LEFT, PAD_START, PAD_UP
from drive import (STATE_LOADING, STATE_READER, STATE_SEARCH, WINDOW_ROWS, check_reader_frame,
                   open_reader, position, run_until, tap)
from wire import link, ms

COLUMNS = p.NESP_WIKI_COLUMNS
PERIOD = p.NESP_PERIOD
DEFAULT = b"Nintendo Entertainment System"
STATUS_ROW = 24
# A line's reply: the frame round a state, a number, a total and the line.
REPLY_CYCLES = (p.NESP_OVERHEAD + 5 + COLUMNS) * p.NESP_TO_NES_BITS * PERIOD
NOT_FOUND, ERROR = p.NESP_ARTICLE_NOT_FOUND, p.NESP_ARTICLE_ERROR
SOURCE = (b"", b"From Wikipedia, the free", b"encyclopedia. CC BY-SA 4.0.")


class Lines(list):
    """An article as the console should show it, a line a row, with the
    reply from Wikipedia that lays out to it."""

    body = b""


def numbered_article(count):
    """An article of `count` lines, which must be even, whose every
    paragraph says which it is. A paragraph is a line here, with a blank
    line after it, and the article ends as every article does."""
    assert count % 2 == 0 and count >= 6
    texts = ["Line %04d of %04d" % (index, count) for index in range((count - 4) // 2)]
    page = {"pageid": 1, "ns": 0, "title": "Numbered", "index": 1,
            "extract": "\n".join(texts)}
    lines = Lines()
    lines.body = json.dumps({"batchcomplete": True, "query": {"pages": [page]}},
                            separators=(",", ":")).encode()
    # The firmware's own wrapper says what the lines are; that it lays text
    # out rightly is nesp32's tests' business.
    wrap = nesp.Wrap()
    wrap.title(b"Numbered")
    wrap.put("\n".join(texts).encode())
    wrap.close()
    lines.extend(wrap.lines)
    lines.extend(line.ljust(COLUMNS) for line in SOURCE)
    assert len(lines) == count
    return lines


class Host:
    """A Stick, and Wikipedia. A search takes `fetch_polls` polls and ends
    as `outcome` says: an article from numbered_article, or (state,
    message). With `trickle`, an article arrives that many cycles a line."""

    def __init__(self, console, outcome, fetch_polls=40, trickle=0, online=True, **options):
        self.outcome = outcome
        self.fetch_polls = fetch_polls
        self.trickle = trickle
        self.arriving = None
        self.next_piece = 0
        self.console = console
        self.fetching = 0
        self.fetches = 0
        self.searches = []
        # What the Stick last told the console.
        self.state = None
        self.total = 0
        self.asked = []                 # the lines asked for, in order
        self.stick, self.port = link(console, nesp.Stick, **options)
        if online:
            self.stick.set_wifi(p.NESP_WIFI_JOINED, address=(10, 0, 0, 2))
        write = self.port.write

        def watch(data):
            reply = nesp.parse(data)
            if reply.svc == p.NESP_SVC_WIKI and reply.ok:
                if len(reply.payload) in (5, 5 + COLUMNS):
                    self.asked.append(reply.payload[1] | reply.payload[2] << 8)
                    self.total = reply.payload[3] | reply.payload[4] << 8
                else:
                    self.total = reply.payload[2] | reply.payload[3] << 8
                self.state = reply.payload[0]
            write(data)
        self.port.write = watch
        console.host = self.poll

    @property
    def line_requests(self):
        return len(self.asked)

    def poll(self):
        stick = self.stick
        stick.poll()
        if stick.fetches != self.fetches:
            self.fetches = stick.fetches
            query = urllib.parse.unquote_to_bytes(stick.fetch_url.rsplit("=", 1)[1])
            self.searches.append(query)
            self.fetching = self.fetch_polls
            self.arriving = None
        elif self.arriving is not None:
            if self.console.now >= self.next_piece:
                # A paragraph is two lines: the text, and a blank one.
                self.next_piece = self.console.now + 2 * self.trickle
                stick.fetch_body(self.arriving.pop(0))
                if not self.arriving:
                    self.arriving = None
                    stick.fetch_done()
        elif self.fetching:
            self.fetching -= 1
            if not self.fetching:
                if isinstance(self.outcome, list) and self.trickle:
                    body = self.outcome.body
                    start = body.index(b"Line 0000")
                    pieces = body[start:].split(b"\\n")
                    self.arriving = [body[:start] + pieces[0] + b"\\n"]
                    self.arriving += [piece + b"\\n" for piece in pieces[1:-1]] + [pieces[-1]]
                elif isinstance(self.outcome, list):
                    stick.fetch_body(self.outcome.body)
                    stick.fetch_done()
                elif self.outcome[0] == NOT_FOUND:
                    stick.fetch_body(b'{"batchcomplete":true}')
                    stick.fetch_done()
                else:
                    stick.fetch_done(False, self.outcome[1].encode() if self.outcome[1:] else b"")


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
    assert host.stick.app == (b"WIKI", 2)       # it said who it was first
    assert c.byte("search_id") == 1
    assert c.word("total") == 90
    frame = c.frames[-1]
    check_reader_frame(frame, lines)
    assert position(frame) == 0
    # Lines 0 to 22 before the reader came up, then five more in hand.
    c.run(10)
    assert host.line_requests == WINDOW_ROWS + 1 + 5
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
    assert host.stick.dropped == 0 and host.stick.repeats == 0
    drawn = sum(1 for frame in c.frames + [c.frame]
                if frame.vblank_writes and frame.vblank_writes[0] < 0x2400)
    assert host.line_requests == drawn


def test_pages_glide_at_full_speed(linked):
    lines = numbered_article(200)
    c, host = linked(lines)
    open_reader(c)
    for _ in range(4):
        c.run(1, pad=PAD_A)
        shown = hold(c, lines, 0, 44)
        assert [step for step in moves(shown) if step] == [4] * 40
    c.run(1, pad=PAD_LEFT)
    shown = hold(c, lines, 0, 44)
    assert [step for step in moves(shown) if step] == [-4] * 40


def test_each_line_is_asked_for_once(linked):
    lines = numbered_article(140)
    c, host = linked(lines)
    open_reader(c)
    del host.asked[:]
    hold(c, lines, PAD_DOWN, 300)
    asked = host.asked
    assert len(asked) > 60 and asked == list(range(asked[0], asked[0] + len(asked)))


@pytest.mark.parametrize("turnaround_ms", [0.05, 0.2, 1.0, 2.5, 4.0])
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
    trying. docs/PROTOCOL.md says about 4.5 ms; nesp32's firmware took 0.2
    at worst on a StickS3."""
    def lands(turnaround_ms):
        lines = numbered_article(60)
        c, host = linked(lines)
        open_reader(c)
        host.port.turnaround = ms(turnaround_ms)
        shown = hold(c, lines, PAD_DOWN, 60)
        return moves(shown)[1:] == [2] * 58
    budget = max(step / 4 for step in range(16, 40) if lands(step / 4))
    assert 4.0 <= budget <= 5.0, budget


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
    pads = (PAD_DOWN, PAD_DOWN, PAD_UP, PAD_A, PAD_LEFT, 0)
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
    assert host.stick.noise > 0                 # the controller read's junk byte


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
    assert status(c) == "THE NESP32 LOST THE ARTICLE"
    assert c.frames[-1].split is None


def test_a_console_reset_starts_from_nothing_and_fetches_again(linked, link_console):
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
    # A reset console says hello again, and the Stick starts it from
    # nothing: the article is fetched afresh.
    assert host.searches == [DEFAULT, DEFAULT] and host.stick.hellos == 2
    check_reader_frame(again.frames[-1], lines)


def test_a_second_search_fetches_again(linked):
    lines = numbered_article(60)
    c, host = linked(lines)
    open_reader(c)
    tap(c, PAD_B)                               # back to the search,
    tap(c, PAD_B)                               # ...Syste
    tap(c, PAD_START)
    run_until(c, STATE_READER)
    assert host.searches == [DEFAULT, DEFAULT[:-1]]
    assert c.byte("search_id") == 2 and host.stick.hellos == 1


@pytest.mark.parametrize("outcome, shown", [
    ((NOT_FOUND,), "NO ARTICLE FOUND"),
    ((ERROR, "the site said 503"), "THE SITE SAID 503"),
    ((ERROR,), "THE SEARCH FAILED"),
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
    assert status(c) == "THE NESP32 HAS NO WI-FI" and host.searches == []


def test_no_stick_at_all_gives_up_after_half_a_minute(link_console):
    c = link_console()
    c.run(3)
    tap(c, PAD_START)
    c.run(1700)
    assert c.byte("state") == STATE_LOADING and status(c) == "SEARCHING..."
    c.run(200)
    assert c.byte("state") == STATE_SEARCH
    assert status(c) == "NO ANSWER FROM THE NESP32"


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
    assert host.stick.requests == len(host.port.sent) and host.stick.dropped == 0


def test_reading_starts_before_the_article_has_all_arrived(linked):
    lines = numbered_article(130)
    c, host = linked(lines, trickle=200000)     # cycles between lines: about 9 lines a second
    open_reader(c)
    arrived = host.total
    assert 28 <= arrived < 60 and host.state == p.NESP_ARTICLE_READY | p.NESP_ARTICLE_MORE
    assert c.word("total") <= arrived and c.byte("more")
    check_reader_frame(c.frames[-1], lines)
    # Held down, the window follows the article as it comes in, waiting at
    # what is so far its end, and stops at its real end when all is in.
    waited = False
    shown = []
    for _ in range(40):
        shown = hold(c, lines, PAD_DOWN, 60)
        waited = waited or (0 in moves(shown) and host.arriving is not None)
        assert c.word("total") <= host.total
        if host.arriving is None and position(shown[-1]) == end_of(lines):
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
    host.next_piece = float("inf")              # the fetch hangs
    shown = hold(c, lines, PAD_DOWN, 600)
    have = c.word("total")                      # as much as came
    assert 40 < have < 130 and c.byte("more")
    assert position(shown[-1]) == 8 * (have - WINDOW_ROWS)
    shown = hold(c, lines, PAD_UP, 100)
    assert set(moves(shown)[5:]) <= {0, -2} and position(shown[-1]) < 8 * (have - WINDOW_ROWS) - 100


# --- a Bluetooth keyboard ----------------------------------------------------------

ESCAPE, BACKSPACE, ENTER = (bytes((key,)) for key in (p.NESP_KEY_ESCAPE, p.NESP_KEY_BACKSPACE,
                                                       p.NESP_KEY_ENTER))


def query(console):
    length = console.byte("query_len")
    start = console.labels["query"]
    return bytes(console.memory[start + offset] for offset in range(length))


def test_what_is_typed_on_a_bluetooth_keyboard_is_searched_for(linked):
    c, host = linked(numbered_article(30))
    c.run(40)
    assert host.stick.kbd_on and host.stick.hellos == 1    # greeted from the search screen
    host.stick.kbd_type(ESCAPE + b"Mario Kart")
    c.run(20)
    assert query(c) == b"Mario Kart"
    host.stick.kbd_type(ENTER)
    run_until(c, STATE_READER)
    assert host.searches == [b"Mario Kart"] and host.stick.hellos == 1


def test_backspace_takes_back_and_what_has_no_key_on_the_screen_is_not_typed(linked):
    c, host = linked(numbered_article(30))
    c.run(40)
    host.stick.kbd_type(ESCAPE + b"link's!?(x" + BACKSPACE + b" AWAKENING")
    c.run(30)
    assert query(c) == b"link's AWAKENING"
    host.stick.kbd_type(b"x" * 20)                  # no more than a search holds
    c.run(30)
    assert query(c) == b"link's AWAKENING" + b"x" * 14


def test_the_keyboard_on_the_screen_and_the_bluetooth_one_type_into_one_field(linked):
    c, host = linked(numbered_article(30))
    c.run(40)
    host.stick.kbd_type(ESCAPE + b"Sup")
    c.run(20)
    tap(c, PAD_A)                                   # the key the cursor starts on: Q
    host.stick.kbd_type(b"er")
    c.run(20)
    assert query(c) == b"SupQer"


def test_what_is_typed_while_reading_is_not_searched_for_on_coming_back(linked):
    lines = numbered_article(30)
    c, host = linked(lines)
    open_reader(c)
    host.stick.kbd_type(b"Metroid" + ENTER)
    tap(c, PAD_SELECT)                              # back to the search
    run_until(c, STATE_SEARCH)
    c.run(40)
    assert c.byte("state") == STATE_SEARCH and query(c) == DEFAULT
    assert host.stick.kbd_unread == 0
    host.stick.kbd_type(ENTER)
    run_until(c, STATE_READER)
    assert host.searches == [DEFAULT, DEFAULT]


def test_a_stick_without_kbd_is_searched_with_all_the_same(linked):
    c, host = linked(numbered_article(30))
    write = host.port.write

    def without_kbd(data):
        # The hello's reply, as a firmware from before KBD gives it.
        reply = nesp.parse(data)
        if reply.svc == p.NESP_SVC_SYS and reply.ok and len(reply.payload) == 7:
            data = nesp.reply_frame(reply.svc, p.NESP_ST_NO_SERVICE, reply.seq,
                                    reply.payload[:6] + bytes((1, p.NESP_SVC_KBD)))
        write(data)
    host.port.write = without_kbd
    c.run(40)
    assert c.byte("greeted") and not c.byte("typing")
    host.stick.kbd_type(b"never")
    c.run(30)
    assert query(c) == DEFAULT and host.stick.kbd_unread == 5
    tap(c, PAD_START)
    run_until(c, STATE_READER)
    assert host.searches == [DEFAULT]
