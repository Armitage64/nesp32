"""COMMONS, the Gallery's service, with no console: requests in, replies
out, and the test in place of Wikimedia Commons."""

import json
import os
from urllib.parse import parse_qs, urlparse

import nesp
import nesp_proto as p
import pytest

COMMONS = p.NESP_SVC_COMMONS
COLUMNS = p.NESP_COMMONS_COLUMNS
CHUNK = p.NESP_COMMONS_CHUNK
SIZE = p.NESP_COMMONS_SIZE
SPLIT_ROW = p.NESP_COMMONS_SPLIT_ROW
SPLIT_LINE = 8 * SPLIT_ROW - 1
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
A_IDLE, A_NO_WIFI, A_SEARCHING = p.NESP_ALBUM_IDLE, p.NESP_ALBUM_NO_WIFI, p.NESP_ALBUM_SEARCHING
A_READY, A_NOT_FOUND, A_FAILED = p.NESP_ALBUM_READY, p.NESP_ALBUM_NOT_FOUND, p.NESP_ALBUM_FAILED
P_IDLE, P_FETCHING, P_READY, P_FAILED = (p.NESP_PHOTO_IDLE, p.NESP_PHOTO_FETCHING,
                                         p.NESP_PHOTO_READY, p.NESP_PHOTO_FAILED)


def fixture(name):
    with open(os.path.join(FIXTURES, name), "rb") as handle:
        return handle.read()


def reply_of(pages):
    """A search's reply as Commons sends one, for these pages."""
    return json.dumps({"batchcomplete": True, "query": {"pages": pages}}).encode()


def page(index, title, url, artist="<a href=\"//x\">Someone</a>", licence="CC BY 4.0"):
    return {"pageid": 100 + index, "ns": 6, "title": title, "index": index,
            "imageinfo": [{"thumburl": url, "thumbwidth": 320, "thumbheight": 240,
                           "extmetadata": {"Artist": {"value": artist},
                                           "LicenseShortName": {"value": licence}}}]}


class Gallery:
    """A console's side of the service."""

    def __init__(self, stick, online=True):
        self.stick = stick
        if online:
            stick.set_wifi(p.NESP_WIFI_JOINED, address=(10, 0, 0, 2))
        assert stick.hello(app=b"GALL", services=[COMMONS]).ok
        self.id = 0
        self.open_id = 0

    def search(self, words, new=True):
        """(state, count, message) of a search: a new one, or the last again."""
        if new:
            self.id = (self.id + 1) & 0xFF
        reply = self.stick.ask(COMMONS, p.NESP_COMMONS_SEARCH, bytes((self.id,)) + words)
        assert reply.ok and reply.payload[1] == self.id
        return reply.payload[0], reply.payload[2], reply.payload[3:]

    def caption(self, index, line):
        reply = self.stick.ask(COMMONS, p.NESP_COMMONS_CAPTION, bytes((index, line)))
        assert reply.ok and tuple(reply.payload[1:3]) == (index, line)
        if reply.payload[0] & p.NESP_ALBUM_NO_LINE:
            assert len(reply.payload) == 3
            return None
        assert len(reply.payload) == 3 + COLUMNS
        return reply.payload[3:].decode("ascii").rstrip()

    def open(self, index, new=True):
        """(state, message) of a picture."""
        if new:
            self.open_id = (self.open_id + 1) & 0xFF
        reply = self.stick.ask(COMMONS, p.NESP_COMMONS_OPEN, bytes((self.open_id, index)))
        assert reply.ok and tuple(reply.payload[1:3]) == (self.open_id, index)
        return reply.payload[0], reply.payload[3:]

    def data(self, index, offset):
        """(state, bytes) of DATA."""
        reply = self.stick.ask(COMMONS, p.NESP_COMMONS_DATA,
                               bytes((index, offset & 0xFF, offset >> 8)))
        assert reply.ok
        assert tuple(reply.payload[1:4]) == (index, offset & 0xFF, offset >> 8)
        return reply.payload[0], reply.payload[4:]

    def picture(self, index):
        """The whole of a picture that is ready, by DATA."""
        out = bytearray()
        while len(out) < SIZE:
            state, chunk = self.data(index, len(out))
            assert state == P_READY and 0 < len(chunk) <= CHUNK
            out += chunk
        assert self.data(index, SIZE) == (P_READY | p.NESP_PHOTO_NO_DATA, b"")
        return bytes(out)

    def found(self, words=b"lighthouse", body=None):
        """A search answered with the recorded reply, or this one."""
        assert self.search(words)[0] == A_SEARCHING
        self.stick.fetch_body(fixture("commons_lighthouse.json") if body is None else body)
        self.stick.fetch_done()
        state, count, _ = self.search(words, new=False)
        return state, count


@pytest.fixture
def gallery(stick):
    return Gallery(stick)


def test_it_answers_only_after_a_hello_asks_for_it(stick):
    assert stick.ask(COMMONS, p.NESP_COMMONS_DATA, b"\0\0\0").status == p.NESP_ST_INACTIVE
    assert stick.hello(services=[COMMONS]).ok
    reply = stick.ask(COMMONS, p.NESP_COMMONS_DATA, b"\0\0\0")
    assert reply.ok and reply.payload == bytes((P_IDLE | p.NESP_PHOTO_NO_DATA, 0, 0, 0))


def test_a_search_asks_commons_for_good_photographs_only(gallery):
    assert gallery.search(b"Red fox") == (A_SEARCHING, 0, b"")
    stick = gallery.stick
    assert stick.fetches == 1
    url = urlparse(stick.fetch_url)
    assert (url.scheme, url.netloc, url.path) == ("https", "commons.wikimedia.org", "/w/api.php")
    query = parse_qs(url.query)
    words = query["gsrsearch"][0].split(" ")
    assert words[:2] == ["Red", "fox"]
    assert "filemime:image/jpeg" in words
    assert "incategory:Quality_images|Featured_pictures_on_Wikimedia_Commons" in words
    assert {"-nude", "-naked", "-nudity", "-erotic", "-porn"} <= set(words)
    assert query["iiurlwidth"] == ["320"] and query["gsrlimit"] == ["20"]
    assert stick.fetch_agent.startswith("nesp32-Gallery/")    # Wikimedia asks to be told
    assert len(stick.fetch_url) < 1024                          # what the firmware's fetch takes


def test_the_longest_search_fits_in_an_address():
    words = bytes(range(0x21, 0x21 + p.NESP_COMMONS_QUERY_MAX))
    url = nesp.commons_url(words)
    assert url is not None and len(url) < 1024


def test_the_same_search_again_only_asks_how_it_is_going(gallery):
    gallery.search(b"Zelda")
    for _ in range(5):
        assert gallery.search(b"Zelda", new=False) == (A_SEARCHING, 0, b"")
    assert gallery.stick.fetches == 1
    gallery.search(b"Zelda")        # a new id: Start was pressed again
    assert gallery.stick.fetches == 2


@pytest.mark.parametrize("words", [b"nude", b"Naked mole", b"NSFW cats", b"sexy", b"porn star",
                                   b"bikini beach", b"nudist"])
def test_words_that_find_adult_pictures_are_not_searched_for(gallery, words):
    state, count, _ = gallery.search(words)
    assert (state, count) == (A_NOT_FOUND, 0)
    assert gallery.stick.fetches == 0
    assert nesp.commons_unsafe(words)


@pytest.mark.parametrize("words", [b"Sussex", b"glass", b"Essex", b"lighthouse", b"Breastplate"])
def test_words_that_only_look_like_them_are(words):
    # "Breastplate" is not "breast": whole words, or the beginnings listed.
    assert not nesp.commons_unsafe(words)


def test_the_recorded_reply_is_its_pictures_in_order_with_their_words(gallery):
    body = fixture("commons_lighthouse.json")
    pages = sorted(json.loads(body)["query"]["pages"], key=lambda each: each["index"])
    assert gallery.found(body=body) == (A_READY, len(pages))
    for index, each in enumerate(pages):
        lines = [gallery.caption(index, line) for line in range(p.NESP_COMMONS_LINES)]
        name = each["title"][len("File:"):].rsplit(".", 1)[0].replace("_", " ")
        assert (lines[0] + " " + lines[1]).strip().startswith(name[:20])
        assert all(len(line) <= COLUMNS and line.isascii() for line in lines)
        assert lines[2].startswith("By ") and "<" not in lines[2] and "&" not in lines[2]
        licence = each["imageinfo"][0]["extmetadata"]["LicenseShortName"]["value"]
        assert lines[3] == licence[:COLUMNS]
    assert gallery.caption(len(pages), 0) is None
    assert gallery.caption(0, p.NESP_COMMONS_LINES) is None


def test_a_name_too_long_for_two_lines_is_cut_with_dots(gallery):
    name = "File:" + " ".join(["Lighthouse"] * 9) + ".jpg"
    assert gallery.found(body=reply_of([page(1, name, "https://t/a.jpg")])) == (A_READY, 1)
    first, second = gallery.caption(0, 0), gallery.caption(0, 1)
    assert first == "Lighthouse Lighthouse"
    assert second.endswith("...") and len(second) == COLUMNS


def test_an_author_is_plain_words(gallery):
    artist = '<bdi><a href="//commons.wikimedia.org/wiki/User:X">Ann &amp; Bo</a>\n</bdi>'
    gallery.found(body=reply_of([page(1, "File:A.jpg", "https://t/a.jpg", artist=artist)]))
    assert gallery.caption(0, 2) == "By Ann & Bo"


def test_pictures_named_for_adult_things_are_dropped(gallery):
    pages = [page(2, "File:Nude study.jpg", "https://t/1.jpg"),
             page(1, "File:Harbour light.jpg", "https://t/2.jpg"),
             page(3, "File:Old pier.jpg", "https://t/3.jpg")]
    assert gallery.found(body=reply_of(pages)) == (A_READY, 2)
    assert [gallery.caption(index, 0) for index in range(2)] == ["Harbour light", "Old pier"]


def test_a_search_that_finds_nothing_says_so(gallery):
    assert gallery.found(body=b'{"batchcomplete":true}') == (A_NOT_FOUND, 0)


def test_a_search_that_fails_says_why(gallery):
    gallery.search(b"x")
    gallery.stick.fetch_done(False, b"THE SITE SAID 429")
    state, count, why = gallery.search(b"x", new=False)
    assert (state, count) == (A_FAILED, 0)
    assert why.decode().strip() == "THE SITE SAID 429" and len(why) == COLUMNS


def test_with_no_wifi_nothing_is_fetched(stick):
    gallery = Gallery(stick, online=False)
    assert gallery.search(b"x")[0] == A_NO_WIFI
    assert stick.fetches == 0


def test_a_picture_is_fetched_made_and_served(gallery):
    jpeg = fixture("commons_tower.jpg")
    url = "https://upload.example/thumb/330px-Tower.jpg"
    gallery.found(body=reply_of([page(1, "File:Tower.jpg", url + "?utm_source=x")]))
    stick = gallery.stick
    assert gallery.data(0, 0)[0] == P_IDLE | p.NESP_PHOTO_NO_DATA
    assert gallery.open(0) == (P_FETCHING, b"")
    assert stick.fetch_url == url                   # less what is after the "?"
    assert gallery.open(0, new=False) == (P_FETCHING, b"")
    assert stick.fetches == 2
    stick.fetch_body(jpeg[:3000])
    stick.fetch_body(jpeg[3000:])
    stick.fetch_done()
    assert gallery.open(0, new=False) == (P_READY, b"")
    assert gallery.picture(0) == stick.picture(jpeg)
    # Another picture's number has none.
    assert gallery.data(1, 0)[0] == P_IDLE | p.NESP_PHOTO_NO_DATA


def test_opening_the_same_picture_again_fetches_it_again(gallery):
    gallery.found(body=reply_of([page(1, "File:A.jpg", "https://t/a.jpg")]))
    gallery.open(0)
    gallery.stick.fetch_done(False, b"THE CONNECTION DROPPED")
    state, why = gallery.open(0, new=False)
    assert state == P_FAILED and why.decode().strip() == "THE CONNECTION DROPPED"
    assert gallery.open(0) == (P_FETCHING, b"")     # a new id: shown again
    assert gallery.stick.fetches == 3


def test_a_file_that_is_not_a_picture_fails(gallery):
    gallery.found(body=reply_of([page(1, "File:A.jpg", "https://t/a.jpg")]))
    gallery.open(0)
    gallery.stick.fetch_body(b"<html>not found</html>")
    gallery.stick.fetch_done()
    state, why = gallery.open(0, new=False)
    assert state == P_FAILED and why.decode().strip() == "THE PICTURE CANNOT BE READ"


def test_a_picture_not_in_the_search_is_none(gallery):
    gallery.found(body=reply_of([page(1, "File:A.jpg", "https://t/a.jpg")]))
    assert gallery.open(5) == (P_IDLE, b"")
    assert gallery.stick.fetches == 1


def test_a_hello_gives_the_memory_back(gallery):
    gallery.found()
    stick = gallery.stick
    assert stick.allocated == 1
    assert stick.hello(app=b"TEST", services=[]).ok
    assert stick.allocated == 0


# --- the picture itself -----------------------------------------------------------

def pixel(picture, x, y):
    """(colour 0-3, NES colour) of a pixel as the NES draws it, the top half
    from the first pattern table and the bottom from the second."""
    names = picture[p.NESP_COMMONS_NAMES:]
    table = 0x1000 if y // 8 >= SPLIT_ROW else 0
    tile = names[(y // 8) * 32 + x // 8]
    planes = picture[table + 16 * tile:table + 16 * tile + 16]
    bit = 7 - x % 8
    index = (planes[y % 8] >> bit) & 1 | ((planes[8 + y % 8] >> bit) & 1) << 1
    attribute = names[960 + (y // 32) * 8 + x // 32]
    which = (attribute >> (((y // 16) % 2) * 4 + ((x // 16) % 2) * 2)) & 3
    palette = picture[p.NESP_COMMONS_PALETTE:]
    return index, palette[0] if index == 0 else palette[4 * which + index]


@pytest.fixture(scope="module", params=["commons_tower.jpg", "commons_tower.png"])
def made(request):
    picture = nesp.Stick().picture(fixture(request.param))
    assert picture is not None and len(picture) == SIZE
    return picture


def test_black_is_behind_everything_and_sprite_0_is_never_seen(made):
    palette = made[p.NESP_COMMONS_PALETTE:p.NESP_COMMONS_PALETTE + 32]
    assert palette[0] == 0x0F and all(palette[4 * n] == 0x0F for n in range(4))
    assert set(palette[16:]) == {0x0F}
    assert all(code < 0x40 and code & 0x0F not in (0x0D, 0x0E) for code in palette)


def test_sprite_0_is_one_pixel_behind_a_lit_one_on_the_split_line(made):
    y, tile, attributes, x = made[p.NESP_COMMONS_SPRITE:p.NESP_COMMONS_SPRITE + 4]
    assert (y + 1, tile, attributes) == (SPLIT_LINE, 0xFF, 0x20)
    sprite = made[16 * 0xFF:16 * 0xFF + 16]
    assert sprite == b"\x80" + bytes(15)
    assert x <= 228 and pixel(made, x, SPLIT_LINE)[0] != 0
    assert made[p.NESP_COMMONS_DELAY] == nesp.split_delay(x)
    # No place on the screen shows the sprite's tile.
    names = made[p.NESP_COMMONS_NAMES:p.NESP_COMMONS_NAMES + 960]
    assert 0xFF not in names[:32 * SPLIT_ROW]


def test_the_picture_is_fitted_in_below_and_above_what_a_television_hides(made):
    # The tower is 330 x 248: 4:3, as wide as the screen, with black above
    # and below it.
    for x in range(0, 256, 7):
        assert pixel(made, x, 0)[0] == 0 and pixel(made, x, 239)[0] == 0
    lit = [y for y in range(240) if any(pixel(made, x, y)[0] for x in range(0, 256, 3))]
    assert 8 <= lit[0] <= 12 and 228 <= lit[-1] <= 231


def test_the_colours_are_near_the_image(made):
    def colour(x, y):
        return pixel(made, x, y)[1]
    # The tower's red and white, and the sun's yellow, somewhere about them.
    tower = {colour(x, y) for x in range(80, 100) for y in range(80, 180)}
    assert tower & {0x16, 0x06, 0x26, 0x15, 0x05, 0x27} and tower & {0x30, 0x20, 0x3D, 0x10}
    sun = {colour(x, y) for x in range(190, 210) for y in range(55, 65)}
    assert sun & {0x28, 0x38, 0x27, 0x37, 0x17}


@pytest.mark.parametrize("x", range(0, 229))
def test_the_split_lands_in_the_hblank_on_either_console(x):
    """viewer.inc's write to PPUCTRL, from the hit at dot x + 2 of the split
    line: 15 cycles with no delay, 13 + 5 a loop with some, and up to 11
    more for the look that sees it, then 4 more every 256th look. It must
    land after dot 240, the last tile of the line fetched, and before 321,
    the next line's first."""
    loops = nesp.split_delay(x)
    cycles = 15 if loops == 0 else 13 + 5 * loops
    for dots_per_cycle in (3, 3.2):
        first = x + 2 + cycles * dots_per_cycle
        last = x + 2 + (cycles + 11) * dots_per_cycle
        assert 240 < first and last < 321, (x, loops, first, last)
