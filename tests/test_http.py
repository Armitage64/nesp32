"""HTTP, any address's reply as it came, with no console: requests in,
replies out, and the test in place of the Internet."""

import nesp_proto as p
import pytest

HTTP = p.NESP_SVC_HTTP
URL, GET, STATE, READ = p.NESP_HTTP_URL, p.NESP_HTTP_GET, p.NESP_HTTP_STATE, p.NESP_HTTP_READ
IDLE, NO_WIFI, ASKING = p.NESP_FETCH_IDLE, p.NESP_FETCH_NO_WIFI, p.NESP_FETCH_ASKING
READING, DONE, FAILED = p.NESP_FETCH_READING, p.NESP_FETCH_DONE, p.NESP_FETCH_FAILED
KEEP, UNKNOWN = p.NESP_HTTP_KEEP, p.NESP_HTTP_LENGTH_UNKNOWN
README = "https://raw.githubusercontent.com/Armitage64/nesp32/main/README.md"


class Reply:
    def __init__(self, payload):
        self.state, self.id = payload[0], payload[1]
        self.status = int.from_bytes(payload[2:4], "little")
        self.length = int.from_bytes(payload[4:8], "little")
        self.held = int.from_bytes(payload[8:10], "little")
        self.ms = int.from_bytes(payload[10:12], "little")
        self.text = payload[12:]


class Browser:
    """A console's side of the service."""

    def __init__(self, stick, online=True):
        self.stick = stick
        if online:
            stick.set_wifi(p.NESP_WIFI_JOINED, address=(10, 0, 0, 2))
        assert stick.hello(app=b"HTTP", services=[HTTP]).ok
        self.id = 0

    def url(self, address, at=0):
        return self.stick.ask(HTTP, URL, bytes((at,)) + address)

    def get(self, new=True):
        if new:
            self.id = (self.id + 1) & 0xFF
        reply = self.stick.ask(HTTP, GET, bytes((self.id,)))
        assert reply.ok and len(reply.payload) >= 12
        return Reply(reply.payload)

    def state(self):
        reply = self.stick.ask(HTTP, STATE)
        assert reply.ok
        return Reply(reply.payload)

    def read(self, offset, count=24):
        reply = self.stick.ask(HTTP, READ, bytes((offset & 0xFF, offset >> 8, count)))
        assert reply.ok and reply.payload[1] | reply.payload[2] << 8 == offset
        return reply.payload[0], reply.payload[3:]


@pytest.fixture
def browser(stick):
    browser = Browser(stick)
    assert browser.url(README.encode()).ok
    return browser


def test_it_answers_only_after_a_hello_asks_for_it(stick):
    assert stick.ask(HTTP, STATE).status == p.NESP_ST_INACTIVE
    assert stick.hello(services=[HTTP]).ok
    reply = Reply(stick.ask(HTTP, STATE).payload)
    assert (reply.state, reply.status, reply.length, reply.held) == (IDLE, 0, UNKNOWN, 0)


def test_a_get_fetches_the_address_and_hears_every_status(browser):
    stick = browser.stick
    reply = browser.get()
    assert (reply.state, reply.id) == (ASKING, 1)
    assert (stick.fetching, stick.fetch_url) == (True, README)
    assert stick.fetch_agent.startswith("nesp32")
    assert stick.fetch_wants_head
    stick.fetch_head(200, b"text/plain; charset=utf-8", 10855)
    reply = browser.state()
    assert (reply.state, reply.status, reply.length, reply.held) == (READING, 200, 10855, 0)
    assert reply.text == b"text/plain; charset=utf-8"
    assert stick.fetch_body(b"# NESP32\n\nAn inexpensive")
    stick.fetch_done()
    reply = browser.state()
    assert (reply.state, reply.held) == (DONE, 24)
    assert browser.read(0, 8) == (DONE, b"# NESP32")
    assert browser.read(10) == (DONE, b"An inexpensive")
    assert browser.read(24) == (DONE, b"")


def test_the_same_get_again_only_says_how_it_stands(browser):
    browser.get()
    browser.get(new=False)
    assert browser.stick.fetches == 1
    browser.get()
    assert browser.stick.fetches == 2


def test_only_the_start_of_a_body_is_held(browser):
    stick = browser.stick
    browser.get()
    stick.fetch_head(200, b"text/plain", 10855)
    assert stick.fetch_body(bytes(KEEP - 100))
    assert not stick.fetch_body(b"x" * 1000)        # no more is read
    stick.fetch_done()
    reply = browser.state()
    assert (reply.state, reply.held, reply.length) == (DONE, KEEP, 10855)
    assert browser.read(KEEP - 1) == (DONE, b"x")


def test_a_404_is_a_reply_with_its_body(browser):
    stick = browser.stick
    browser.get()
    stick.fetch_head(404, b"text/plain; charset=utf-8", UNKNOWN)
    stick.fetch_body(b"404: Not Found")
    stick.fetch_done()
    reply = browser.state()
    assert (reply.state, reply.status, reply.length) == (DONE, 404, UNKNOWN)
    assert browser.read(0) == (DONE, b"404: Not Found")


def test_a_fetch_that_fails_says_why(browser):
    browser.get()
    browser.stick.fetch_done(ok=False, why=b"THE SITE DID NOT ANSWER")
    reply = browser.state()
    assert (reply.state, reply.text) == (FAILED, b"THE SITE DID NOT ANSWER")


def test_how_long_it_took(browser):
    stick = browser.stick
    stick.tick(1000)
    browser.get()
    stick.tick(1100)
    assert browser.state().ms == 100
    stick.fetch_head(200, b"text/plain", 3)
    stick.fetch_body(b"abc")
    stick.fetch_done()
    stick.tick(1250)
    stick.tick(5000)
    assert browser.state().ms == 250


def test_an_older_fetch_adds_nothing(browser):
    stick = browser.stick
    browser.get()
    old = stick.fetch_id
    browser.get()
    assert not stick.fetch_body(b"stale", fetch=old)
    stick.fetch_done(fetch=old)
    assert browser.state().state == ASKING


def test_off_the_network_nothing_is_fetched(stick):
    browser = Browser(stick, online=False)
    browser.url(README.encode())
    assert browser.get().state == NO_WIFI
    assert stick.fetches == 0


def test_an_address_goes_in_pieces(browser):
    stick = browser.stick
    head, tail = README[:100].encode(), README[100:].encode()
    assert browser.url(b"https://example.com/" + bytes(1)).status == p.NESP_ST_BAD_ARG
    assert browser.url(b"x", at=200).status == p.NESP_ST_BAD_ARG    # past the end
    assert browser.url(b"x" * 120).ok and browser.url(b"x" * 120, at=120).ok
    assert browser.url(b"x" * 20, at=240).status == p.NESP_ST_BAD_ARG  # past URL_MAX
    assert browser.url(b"x" * 15, at=240).ok
    assert browser.url(head).ok and browser.url(tail, at=len(head)).ok
    browser.get()
    assert stick.fetch_url == README


def test_a_get_needs_an_address(stick):
    browser = Browser(stick)
    assert stick.ask(HTTP, GET, b"\1").status == p.NESP_ST_BAD_ARG
    browser.url(README.encode())
    assert stick.hello(app=b"HTTP", services=[HTTP]).ok     # a hello forgets it
    assert stick.ask(HTTP, GET, b"\1").status == p.NESP_ST_BAD_ARG


def test_the_other_services_still_fail_on_a_status_but_200(stick):
    """WIKI's sink has no head: fetch.c turns its 404 into a failure, and
    the host stand-in has nothing to give it."""
    assert stick.hello(services=[p.NESP_SVC_WIKI]).ok
    stick.set_wifi(p.NESP_WIFI_JOINED, address=(10, 0, 0, 2))
    stick.ask(p.NESP_SVC_WIKI, p.NESP_WIKI_SEARCH, b"\1NES")
    assert not stick.fetch_wants_head
