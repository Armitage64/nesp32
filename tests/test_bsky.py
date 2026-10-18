"""BSKY, with no console: requests in, replies out, and the test in place of
Bluesky and of the clock."""

import calendar
import json
import os

import nesp_proto as p
import pytest

BSKY = p.NESP_SVC_BSKY
IDLE, NO_WIFI, FETCHING = p.NESP_FEED_IDLE, p.NESP_FEED_NO_WIFI, p.NESP_FEED_FETCHING
READY, NOT_FOUND, FAILED = p.NESP_FEED_READY, p.NESP_FEED_NOT_FOUND, p.NESP_FEED_FAILED
NO_LINE = p.NESP_FEED_NO_LINE
ROWS, COLUMNS, POSTS = p.NESP_BSKY_ROWS, p.NESP_BSKY_COLUMNS, p.NESP_BSKY_POSTS
HANDLE_MAX, FAVORITES = p.NESP_BSKY_HANDLE_MAX, p.NESP_BSKY_FAVORITES
REPLY, REPOST, LIKE = chr(p.NESP_BSKY_REPLY), chr(p.NESP_BSKY_REPOST), chr(p.NESP_BSKY_LIKE)
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
FEED_URL = ("https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"
            "?filter=posts_no_replies&limit=%d&actor=%s")
DEFAULTS = [b"levimaaia.com", b"andyreitano.com", b"adriansdigitalbasement.com",
            b"jeriellsworth.bsky.social"]
NOW = calendar.timegm((2026, 10, 18, 10, 0, 0))


def fixture(name):
    with open(os.path.join(FIXTURES, name), "rb") as handle:
        return handle.read()


def item(text="Hello", handle="someone.bsky.social", name="Someone",
         when="2026-10-18T09:00:00.000Z", replies=1, reposts=2, likes=3, by=None):
    """One item of "feed", with the things around it that a real one has:
    the same keys deeper down, in an embedded post and a reply's parent."""
    post = {"uri": "at://did:plc:x/app.bsky.feed.post/1", "cid": "bafy",
            "author": {"did": "did:plc:x", "handle": handle, "avatar": "https://x/y.jpg",
                       "labels": [], "createdAt": "2024-01-01T00:00:00.000Z"},
            "record": {"$type": "app.bsky.feed.post", "createdAt": when, "langs": ["en"],
                       "text": text,
                       "facets": [{"index": {"byteStart": 0, "byteEnd": 1},
                                   "features": [{"$type": "app.bsky.richtext.facet#tag",
                                                 "tag": "text"}]}]},
            "embed": {"$type": "app.bsky.embed.record#view",
                      "record": {"author": {"handle": "quoted.bsky.social",
                                            "displayName": "Quoted"},
                                 "value": {"text": "a quoted post's text"},
                                 "indexedAt": "2020-01-01T00:00:00.000Z"}},
            "replyCount": replies, "repostCount": reposts, "likeCount": likes,
            "quoteCount": 0, "indexedAt": when, "viewer": {}, "labels": []}
    if name is not None:
        post["author"]["displayName"] = name
    out = {"post": post,
           "reply": {"parent": {"author": {"handle": "parent.bsky.social"},
                                "record": {"text": "the parent's text"}}}}
    if by is not None:
        out["reason"] = {"$type": "app.bsky.feed.defs#reasonRepost",
                         "by": {"did": "did:plc:y", "handle": by, "displayName": "By"},
                         "indexedAt": when}
    return out


def feed_reply(*items):
    return json.dumps({"feed": list(items), "cursor": "2026"}, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


class Reader:
    """A console's side of the service."""

    def __init__(self, stick, online=True):
        self.stick = stick
        if online:
            stick.set_wifi(p.NESP_WIFI_JOINED, address=(10, 0, 0, 2))
        assert stick.hello(app=b"BSKY", services=[BSKY]).ok
        self.id = 0
        self.count = 0
        self.why = b""

    def feed(self, handle=b"bsky.app", new=True):
        """How a handle stands: a new choice, or the last again."""
        if new:
            self.id = (self.id + 1) & 0xFF
        reply = self.stick.ask(BSKY, p.NESP_BSKY_FEED, bytes((self.id,)) + handle)
        assert reply.ok and len(reply.payload) >= 3 and reply.payload[1] == self.id
        self.count, self.why = reply.payload[2], reply.payload[3:]
        assert not self.why or reply.payload[0] == FAILED
        return reply.payload[0]

    def line(self, post, row):
        reply = self.stick.ask(BSKY, p.NESP_BSKY_LINE, bytes((post, row)))
        assert reply.ok and reply.payload[1:3] == bytes((post, row))
        if len(reply.payload) == 4:
            assert reply.payload[0] & NO_LINE
            return None
        assert len(reply.payload) == 4 + COLUMNS and not reply.payload[0] & NO_LINE
        return reply.payload[4:].decode("latin-1")

    def post(self, number):
        return [self.line(number, row) for row in range(ROWS)]

    def land(self, body, pieces=None):
        assert self.stick.fetching
        step = pieces or len(body) or 1
        for at in range(0, len(body), step):
            if not self.stick.fetch_body(body[at:at + step]):
                break
        self.stick.fetch_done(True)

    def read(self, body, handle=b"bsky.app", pieces=None):
        """Choose a handle, and have its posts come."""
        assert self.feed(handle) == FETCHING
        self.land(body, pieces)
        assert self.feed(handle, new=False) == READY
        return [self.post(number) for number in range(self.count)]

    def favorites(self):
        out = []
        number = 0
        while True:
            reply = self.stick.ask(BSKY, p.NESP_BSKY_FAVORITE, bytes((number,)))
            assert reply.ok and reply.payload[1] == number
            if number >= reply.payload[0]:
                assert len(reply.payload) == 2
                return out
            out.append(reply.payload[2:])
            number += 1


@pytest.fixture
def reader(stick):
    stick.set_time(NOW)
    return Reader(stick)


def heading(text):
    """A line in the second colour."""
    return "".join(chr(ord(char) | 0x80) for char in text) + " " * (COLUMNS - len(text))


def lines(*texts):
    return [text.ljust(COLUMNS) for text in texts]


def when(age, replies, reposts, likes):
    """A post's last line: its age at the left, its counts at the right."""
    counts = "%s%s %s%s %s%s" % (REPLY, replies, REPOST, reposts, LIKE, likes)
    return age.ljust(COLUMNS - len(counts)) + counts


# --- posts ---------------------------------------------------------------------------

def test_posts_from_what_bluesky_really_sent(reader):
    posts = reader.read(fixture("bsky_feed.json"), pieces=97)
    assert reader.stick.fetch_url == FEED_URL % (POSTS, "bsky.app")
    assert reader.stick.fetch_agent.startswith("nesp32-bluesky/")
    assert len(posts) == 8
    assert posts[0] == [heading("Bluesky")] + lines(
        "@bsky.app",
        "",
        '"Pro wrestling',
        "conversations, like sports",
        "on Bluesky across the board,",
        "rarely engagement-farm-posts",
        "are celebratory and much",
        "more real. The lesson is to",
        "invest in product features",
        "that serve people who care",
        "more about the community",
        "than they care about going",
        'viral." - @harry.bsky.team',
        "",
        when("1d", 110, 111, 860),
    )
    # A repost says who reposted it; a count of thousands is in k.
    assert posts[1][:3] == [heading("Stephen Judkins")] + lines(
        "@stephenjudkins.bsky.social", "Reposted by @bsky.app")
    assert posts[1][-1] == when("3d", 47, 360, "3k")
    assert posts[1][-2] == "detailed and correct".ljust(COLUMNS)    # it just fits
    # Newlines: a blank line between paragraphs, and no more than one.
    assert posts[2][3:9] == lines("v1.135 is live!", "", "You can now browse quote",
                                  "posts by Top in addition to", "Latest. And posts keep their",
                                  "thread numbering when")
    assert posts[6][3:5] == lines("saw some cool clouds today", "")


def test_every_line_is_tiles_the_console_has(reader):
    for post in reader.read(fixture("bsky_feed.json")):
        assert all(len(line) == COLUMNS for line in post)
        for line in post[1:]:
            assert all(0x20 <= ord(tile) <= 0x7E or tile in (REPLY, REPOST, LIKE)
                       for tile in line)
        assert all(0xA0 <= ord(tile) <= 0xFE for tile in post[0].rstrip())


def test_only_the_post_s_own_fields_are_taken(reader):
    posts = reader.read(feed_reply(item(text="mine", handle="me.example", name="Me")))
    assert posts == [[heading("Me")] + lines("@me.example", "", "mine", *[""] * 11)
                     + [when("1h", 1, 2, 3)]]


def test_a_post_with_no_name_has_its_handle_for_one(reader):
    post = reader.read(feed_reply(item(name=None, handle="nameless.bsky.social")))[0]
    assert post[0] == heading("nameless.bsky.social")
    post = reader.read(feed_reply(item(name="", handle="empty.bsky.social")))[0]
    assert post[0] == heading("empty.bsky.social")


@pytest.mark.parametrize("text,first", [
    ("caf\u00e9 \u201cquoted\u201d \u2014 done", 'cafe "quoted" - done'),
    ("emoji \U0001F600\U0001F44D\U0001F3FD here \u2764\ufe0f", "emoji here"),
    ("tab\there", "tab here"),
    ("\u4f60\u597d\u4e16\u754c ok", "? ok"),
    ("escaped \\\"slash/ \\\\", 'escaped \\"slash/ \\\\'),
])
def test_text_as_ascii(reader, text, first):
    post = reader.read(feed_reply(item(text=text)))[0]
    assert post[3].rstrip() == first


def test_text_that_does_not_fit_ends_with_dots(reader):
    post = reader.read(feed_reply(item(text=" ".join(["word"] * 200))))[0]
    assert post[3:15] == lines(*["word word word word word"] * 11, "word word word word word...")
    long_word = reader.read(feed_reply(item(text="x" * 70 + " end")))[0]
    assert long_word[3:7] == lines("x" * 28, "x" * 28, "x" * 14 + " end", "")


def test_ages_and_dates(stick):
    reader = Reader(stick)
    stick.set_time(NOW)
    whens = ["2026-10-18T09:59:30.000Z", "2026-10-18T09:15:00Z", "2026-10-17T07:00:00.000Z",
             "2026-10-12T10:00:00.000Z", "2026-10-01T10:00:00.000Z", "2026-10-19T00:00:00Z"]
    posts = reader.read(feed_reply(*[item(when=when) for when in whens]))
    assert [post[-1][:7].rstrip() for post in posts] == ["now", "45m", "1d", "6d", "Oct 1",
                                                         "Oct 19"]
    stick.set_time(None)
    posts = reader.read(feed_reply(item(when="2026-10-18T09:59:30.000Z")))
    assert posts[0][-1][:7].rstrip() == "Oct 18"


def test_posts_are_offered_as_they_come(reader):
    body = feed_reply(*[item(text="post %d" % number) for number in range(5)])
    assert reader.feed() == FETCHING
    middle = body.index(b"post 2")
    assert reader.stick.fetch_body(body[:middle])
    assert reader.feed(new=False) == FETCHING and reader.count == 2
    assert reader.line(1, 3).rstrip() == "post 1"
    assert reader.line(2, 3) is None
    assert reader.stick.fetch_body(body[middle:]) is False     # it has all it wants
    reader.stick.fetch_done(True)
    assert reader.feed(new=False) == READY and reader.count == 5


def test_no_more_than_the_room_for_them(reader):
    posts = reader.read(feed_reply(*[item(text=str(n)) for n in range(POSTS + 3)]))
    assert len(posts) == POSTS
    assert reader.line(POSTS, 0) is None
    assert reader.line(0, ROWS) is None


def test_a_feed_with_no_posts(reader):
    assert reader.read(feed_reply()) == []


def test_a_reply_cut_short_keeps_what_came_whole(reader):
    body = feed_reply(*[item(text="post %d" % number) for number in range(3)])
    assert reader.feed() == FETCHING
    reader.stick.fetch_body(body[:body.index(b"post 2")])
    reader.stick.fetch_done(False, b"THE CONNECTION DROPPED")
    assert reader.feed(new=False) == READY and reader.count == 2


# --- handles and failures --------------------------------------------------------------

@pytest.mark.parametrize("typed,asked", [
    (b"bsky.app", "bsky.app"), (b"@Bsky.App", "bsky.app"),
    (b"jeriellsworth", "jeriellsworth.bsky.social"),
    (b"adriansdigitalbasement.com", "adriansdigitalbasement.com"),
])
def test_a_handle_as_bluesky_has_it(reader, typed, asked):
    assert reader.feed(typed) == FETCHING
    assert reader.stick.fetch_url == FEED_URL % (POSTS, asked)


@pytest.mark.parametrize("typed", [b"", b"@", b"bad handle", b"x" * (HANDLE_MAX + 1),
                                   b".dot", b"dot.", b"a_b.com", b"q" * 20])
def test_what_cannot_be_a_handle(reader, typed):
    reply = reader.stick.ask(BSKY, p.NESP_BSKY_FEED, b"\x01" + typed)
    assert reply.status == p.NESP_ST_BAD_ARG
    assert not reader.stick.fetching


def test_no_one_by_that_handle(reader):
    assert reader.feed(b"nosuch12345") == FETCHING
    reader.stick.fetch_done(False, b"THE SITE SAID 400")
    assert reader.feed(b"nosuch12345", new=False) == NOT_FOUND
    assert reader.count == 0


def test_a_fetch_that_fails_says_why(reader):
    assert reader.feed() == FETCHING
    reader.stick.fetch_done(False, b"THE SITE SAID 503")
    assert reader.feed(new=False) == FAILED
    assert reader.why == b"THE SITE SAID 503".center(COLUMNS)


def test_the_same_choice_again_only_answers(reader):
    assert reader.feed() == FETCHING
    fetches = reader.stick.fetches
    assert reader.feed(new=False) == FETCHING
    assert reader.stick.fetches == fetches
    assert reader.feed() == FETCHING        # a new id is a new fetch
    assert reader.stick.fetches == fetches + 1


def test_an_old_fetch_adds_nothing(reader):
    assert reader.feed(b"old.bsky.social") == FETCHING
    old = reader.stick.fetch_id
    assert reader.feed(b"new.bsky.social") == FETCHING
    assert not reader.stick.fetch_body(feed_reply(item(text="old")), fetch=old)
    reader.stick.fetch_done(True, fetch=old)
    assert reader.feed(b"new.bsky.social", new=False) == FETCHING and reader.count == 0


def test_no_wifi(stick):
    reader = Reader(stick, online=False)
    assert reader.feed() == NO_WIFI
    assert not stick.fetching


def test_out_of_memory(stick):
    stick.alloc_most(1000)
    reader = Reader(stick)
    assert reader.feed() == FAILED
    assert reader.why == b"THE NESP32 IS OUT OF MEMORY".center(COLUMNS)


def test_a_hello_lets_the_posts_go(reader):
    reader.read(feed_reply(item()))
    assert reader.stick.allocated == 1
    assert reader.stick.hello(app=b"TEST", services=[]).ok
    assert reader.stick.allocated == 0


# --- favorites -------------------------------------------------------------------------

def test_the_favorites_a_nesp32_begins_with(reader):
    assert reader.favorites() == DEFAULTS
    assert reader.stick.favorites is None       # nothing is written until they change


def test_adding_and_removing_favorites_is_kept(stick):
    reader = Reader(stick)
    reply = stick.ask(BSKY, p.NESP_BSKY_ADD, b"@Bsky.App")
    assert reply.ok and reply.payload == bytes((5, 4))
    assert reader.favorites() == DEFAULTS + [b"bsky.app"]
    assert stick.favorites == DEFAULTS + [b"bsky.app"] and stick.favorites_keeps == 1
    reply = stick.ask(BSKY, p.NESP_BSKY_ADD, b"bsky.app")       # there already
    assert reply.payload == bytes((5, 4)) and stick.favorites_keeps == 1
    reply = stick.ask(BSKY, p.NESP_BSKY_REMOVE, b"\x01")
    assert reply.ok and reply.payload == bytes((4,))
    kept = [DEFAULTS[0]] + DEFAULTS[2:] + [b"bsky.app"]
    assert reader.favorites() == kept and stick.favorites == kept
    # Switched off and on: what was kept is what it begins with.
    assert stick.hello(app=b"BSKY", services=[BSKY]).ok
    assert reader.favorites() == kept


def test_a_nesp32_that_kept_its_favorites(stick):
    stick.favorites = [b"one.bsky.social", b"two.example"]
    reader = Reader(stick)
    assert reader.favorites() == [b"one.bsky.social", b"two.example"]
    stick.favorites = []
    assert stick.hello(app=b"BSKY", services=[BSKY]).ok
    assert reader.favorites() == []


def test_no_more_favorites_than_there_is_room_for(stick):
    stick.favorites = []
    reader = Reader(stick)
    for number in range(FAVORITES):
        reply = stick.ask(BSKY, p.NESP_BSKY_ADD, b"h%d.example" % number)
        assert reply.payload == bytes((number + 1, number))
    reply = stick.ask(BSKY, p.NESP_BSKY_ADD, b"more.example")
    assert reply.payload == bytes((FAVORITES, 0xFF))
    assert len(reader.favorites()) == FAVORITES
    reply = stick.ask(BSKY, p.NESP_BSKY_REMOVE, bytes((FAVORITES,)))   # no such one
    assert reply.payload == bytes((FAVORITES,))


def test_a_favorite_that_is_not_a_handle(reader):
    assert reader.stick.ask(BSKY, p.NESP_BSKY_ADD, b"no way").status == p.NESP_ST_BAD_ARG
    assert reader.favorites() == DEFAULTS


def test_a_repeated_remove_removes_one(stick):
    """The link answers a request it has answered, sent again, with the
    same reply, and does not act on it twice."""
    reader = Reader(stick)
    first = stick.ask(BSKY, p.NESP_BSKY_REMOVE, b"\x00", seq=7)
    again = stick.ask(BSKY, p.NESP_BSKY_REMOVE, b"\x00", seq=7)
    assert first.payload == again.payload == bytes((3,))
    assert reader.favorites() == DEFAULTS[1:]
