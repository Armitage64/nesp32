"""WEATHER, with no console: requests in, replies out, and the test in place
of Zippopotam, of Open-Meteo and of the clock."""

import json
import os

import nesp_proto as p
import pytest

WEATHER = p.NESP_SVC_WEATHER
IDLE, NO_WIFI, LOOKING = p.NESP_SKY_IDLE, p.NESP_SKY_NO_WIFI, p.NESP_SKY_LOOKING
FETCHING, READY = p.NESP_SKY_FETCHING, p.NESP_SKY_READY
NOT_FOUND, FAILED = p.NESP_SKY_NOT_FOUND, p.NESP_SKY_FAILED
ROWS, COLUMNS, DAYS = p.NESP_WEATHER_ROWS, p.NESP_WEATHER_COLUMNS, p.NESP_WEATHER_DAYS
POLL, RETRY, UNASKED = (p.NESP_WEATHER_POLL_MS, p.NESP_WEATHER_RETRY_MS,
                        p.NESP_WEATHER_UNASKED_MS)
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
DEGREE = chr(p.NESP_WEATHER_DEGREE)
SUN, MOON, PARTLY, CLOUD = (p.NESP_PICTURE_SUN, p.NESP_PICTURE_MOON, p.NESP_PICTURE_PARTLY,
                            p.NESP_PICTURE_CLOUD)
FOG, RAIN, SNOW, STORM = (p.NESP_PICTURE_FOG, p.NESP_PICTURE_RAIN, p.NESP_PICTURE_SNOW,
                          p.NESP_PICTURE_STORM)
DAY_COLUMNS = (1, 7, 13, 19, 25)
WEATHER_URL = ("https://api.open-meteo.com/v1/forecast?latitude=%.4f&longitude=%.4f"
               "&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,is_day"
               "&daily=weather_code,temperature_2m_max,temperature_2m_min"
               "&forecast_days=5&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=auto")


def fixture(name):
    with open(os.path.join(FIXTURES, name), "rb") as handle:
        return handle.read()


def where_reply(name="Beverly Hills", state="CA", north="34.0901", east="-118.4065", **more):
    """Zippopotam's answer to where a zip code is."""
    place = {"place name": name, "longitude": east, "latitude": north, "state": "Somewhere",
             "state abbreviation": state}
    place.update(more)
    place = {key: value for key, value in place.items() if value is not None}
    return json.dumps({"country": "United States", "country abbreviation": "US",
                       "post code": "90210", "places": [place]}).encode("utf-8")


def weather_reply(now=72.0, code=0, day=1, humidity=43, wind=9.2, dates=None, codes=None,
                  highs=None, lows=None):
    """Open-Meteo's answer to what the weather is."""
    at_once = {"time": "2026-10-13T14:00", "interval": 900, "temperature_2m": now,
               "relative_humidity_2m": humidity, "weather_code": code, "wind_speed_10m": wind,
               "is_day": day}
    daily = {"time": dates or ["2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16",
                               "2026-10-17"],
             "weather_code": codes or [3, 0, 0, 0, 0],
             "temperature_2m_max": highs or [73.7, 81.1, 85.9, 91.1, 90.0],
             "temperature_2m_min": lows or [55.0, 60.7, 65.7, 74.3, 75.8]}
    return json.dumps({"latitude": 34.08, "longitude": -118.4,
                       "current_units": {"temperature_2m": "°F"},
                       "current": {key: value for key, value in at_once.items()
                                   if value is not None},
                       "daily": daily}, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def picture(which):
    """A picture's two rows of tiles, as text."""
    first = p.NESP_WEATHER_PICTURE + 4 * which
    return chr(first) + chr(first + 1), chr(first + 2) + chr(first + 3)


class Sky:
    """A console's side of the service, and the clock."""

    def __init__(self, stick, online=True):
        self.stick = stick
        self.now = 1000
        if online:
            stick.set_wifi(p.NESP_WIFI_JOINED, address=(10, 0, 0, 2))
        assert stick.hello(app=b"WTHR", services=[WEATHER]).ok
        self.id = 0
        self.serial = 0
        self.why = b""

    def wait(self, ms=0):
        self.now += ms
        self.stick.tick(self.now)

    def zip(self, digits=b"90210", new=True):
        """The state of a zip code: a new choice, or the last again."""
        if new:
            self.id = (self.id + 1) & 0xFF
        reply = self.stick.ask(WEATHER, p.NESP_WEATHER_ZIP, bytes((self.id,)) + digits)
        assert reply.ok and len(reply.payload) >= 3 and reply.payload[1] == self.id
        self.serial, self.why = reply.payload[2], reply.payload[3:]
        assert (self.serial != 0) == (reply.payload[0] == READY)
        assert not self.why or reply.payload[0] == FAILED
        return reply.payload[0]

    def row(self, number):
        reply = self.stick.ask(WEATHER, p.NESP_WEATHER_ROW, bytes((self.id, number)))
        assert reply.ok and reply.payload[1] == self.id and reply.payload[3] == number
        if len(reply.payload) == 4:
            assert reply.payload[2] == 0
            return reply.payload[0], None
        assert reply.payload[0] == READY and len(reply.payload) == 4 + COLUMNS
        assert reply.payload[2] == self.serial
        return READY, reply.payload[4:].decode("latin-1")

    def rows(self):
        assert self.zip(new=False) == READY
        return [self.row(number)[1] for number in range(ROWS)]

    def land(self, body, pieces=None):
        """The fetch under way ends with this reply."""
        assert self.stick.fetching
        for at in range(0, len(body), pieces or len(body) or 1):
            assert self.stick.fetch_body(body[at:at + (pieces or len(body))])
        self.stick.fetch_done(True)
        self.wait()

    def fail(self, why=b"THE SITE DID NOT ANSWER"):
        assert self.stick.fetching
        self.stick.fetch_done(False, why)
        self.wait()

    def look(self, digits=b"90210"):
        """Choose a zip code nobody has asked after, and be at the fetch of
        where it is."""
        assert self.zip(digits) == LOOKING
        self.wait()
        assert self.stick.fetching
        assert self.stick.fetch_url == "https://api.zippopotam.us/us/" + digits.decode()

    def find(self, digits=b"90210", where=None):
        """Choose a zip code, be told where it is, and be at the fetch of
        its weather."""
        self.look(digits)
        self.land(where or where_reply())
        assert self.zip(digits, new=False) == FETCHING
        assert self.stick.fetching and "open-meteo" in self.stick.fetch_url

    def report(self, body=None, **weather):
        """A zip code's report, from a reply made of these."""
        self.find()
        self.land(body or weather_reply(**weather))
        return self.rows()


@pytest.fixture
def sky(stick):
    return Sky(stick)


# --- the report ----------------------------------------------------------------

def test_a_report_from_what_the_two_sites_really_sent(sky):
    sky.find(where=fixture("zip_90210.json"))
    assert sky.stick.fetch_url == WEATHER_URL % (34.0901, -118.4065)
    assert sky.stick.fetch_agent.startswith("nesp32-weather/")
    sky.land(fixture("openmeteo_90210.json"), pieces=100)
    sun, cloud = picture(SUN), picture(CLOUD)
    assert sky.rows() == [line.ljust(COLUMNS) for line in (
        "BEVERLY HILLS, CA      90210",
        "",
        sun[0] + "  72" + DEGREE + "F  CLEAR",
        sun[1] + "  HIGH 74" + DEGREE + "  LOW 55" + DEGREE,
        "    HUMIDITY 43%",
        "    WIND 9 MPH",
        "",
        "",
        " TUE   WED   THU   FRI   SAT",
        " " + "    ".join((cloud[0], sun[0], sun[0], sun[0], sun[0])),
        " " + "    ".join((cloud[1], sun[1], sun[1], sun[1], sun[1])),
        " 74    81    86    91    90",
        " 55    61    66    74    76",
    )]
    assert sky.stick.shown(0) == "90210: 72F"


def test_every_row_is_tiles_the_console_has(sky):
    rows = sky.report(now=-12.4, code=57, highs=[104.6, -3, 0, 9.5, 100],
                      lows=[-20.2, -40, -0.4, 5, 99.5])
    for row in rows:
        assert len(row) == COLUMNS
        assert all(0x20 <= ord(tile) <= 0x7F or tile == DEGREE for tile in row)
    assert rows[2][4:] == ("-12" + DEGREE + "F  FREEZING DRIZZLE").ljust(COLUMNS - 4)
    assert rows[3][4:] == ("HIGH 105" + DEGREE + "  LOW -20" + DEGREE).ljust(COLUMNS - 4)
    assert rows[11] == " 105   -3    0     10    100"
    assert rows[12] == " -20   -40   0     5     100"


@pytest.mark.parametrize("code,day,which,words", [
    (0, 1, SUN, "CLEAR"), (0, 0, MOON, "CLEAR"), (1, 1, SUN, "MOSTLY CLEAR"),
    (1, 0, MOON, "MOSTLY CLEAR"), (2, 1, PARTLY, "PARTLY CLOUDY"),
    (2, 0, CLOUD, "PARTLY CLOUDY"), (3, 1, CLOUD, "CLOUDY"), (45, 1, FOG, "FOG"),
    (48, 0, FOG, "FOG"), (51, 1, RAIN, "DRIZZLE"), (55, 1, RAIN, "DRIZZLE"),
    (56, 1, RAIN, "FREEZING DRIZZLE"), (61, 1, RAIN, "RAIN"), (65, 0, RAIN, "RAIN"),
    (67, 1, RAIN, "FREEZING RAIN"), (71, 1, SNOW, "SNOW"), (77, 1, SNOW, "SNOW"),
    (80, 1, RAIN, "SHOWERS"), (82, 1, RAIN, "SHOWERS"), (85, 1, SNOW, "SNOW SHOWERS"),
    (95, 1, STORM, "THUNDERSTORM"), (99, 0, STORM, "THUNDERSTORM"), (42, 1, CLOUD, ""),
])
def test_a_weather_code_is_a_picture_and_a_word_or_two(sky, code, day, which, words):
    rows = sky.report(code=code, day=day, codes=[code] * DAYS)
    assert (rows[2][:2], rows[3][:2]) == picture(which)
    assert rows[2][4:] == ("72" + DEGREE + "F  " + words).ljust(COLUMNS - 4)
    # A day's picture is the day's, whatever the hour is now.
    by_day = {MOON: SUN}.get(which, PARTLY if code == 2 else which)
    for column in DAY_COLUMNS:
        assert (rows[9][column:column + 2], rows[10][column:column + 2]) == picture(by_day)


def test_the_days_are_named_from_their_dates(sky):
    dates = ["2024-02-28", "2024-02-29", "2024-03-01", "2024-03-02", "2024-03-03"]
    assert sky.report(dates=dates)[8] == " WED   THU   FRI   SAT   SUN"


def test_a_century_that_is_no_leap_year(stick):
    sky = Sky(stick)
    dates = ["2100-02-28", "2100-03-01", "2000-02-29", "1999-12-31", "2026-10-12"]
    assert sky.report(dates=dates)[8] == " SUN   MON   TUE   FRI   MON"


def test_humidity_and_wind_are_left_out_when_the_site_has_none(sky):
    rows = sky.report(humidity=None, wind=None, day=None)
    assert rows[4].strip() == "" and rows[5].strip() == ""
    assert (rows[2][:2], rows[3][:2]) == picture(SUN)


def test_a_reply_laid_out_with_spaces_reads_the_same(sky):
    plain = sky.report()
    loose = json.dumps(json.loads(weather_reply().decode("utf-8")), indent=2).encode("utf-8")
    assert sky.zip() == FETCHING                # chosen again, for the weather again
    sky.wait()
    sky.land(loose, pieces=7)
    assert sky.rows() == plain


@pytest.mark.parametrize("name,state,shown", [
    ("Beverly Hills", "CA", "BEVERLY HILLS, CA"),
    ("Española", "NM", "ESPANOLA, NM"),
    ("St. Mary's \"Point\"", "MN", "ST. MARY'S \"POINT\", MN"),
    ("Rancho Santa Margarita", "CA", "RANCHO SANTA MARGA, CA"),
    ("Washington", None, "WASHINGTON"),
    (None, "DC", "DC"),
])
def test_a_place_is_its_name_and_its_state_in_capitals(sky, name, state, shown):
    sky.find(where=where_reply(name=name, state=state))
    sky.land(weather_reply())
    assert sky.rows()[0] == shown.ljust(COLUMNS - 5) + "90210"
    assert len(shown) <= p.NESP_WEATHER_PLACE_MAX


def test_a_name_with_its_letters_escaped(sky):
    where = where_reply(name="XXXX").replace(b"XXXX", b"Ca\\u00f1on\\tCity \\/ \\\\")
    sky.find(where=where)
    sky.land(weather_reply())
    assert sky.rows()[0].startswith("CANON CITY / \\, CA ")


# --- a zip code ----------------------------------------------------------------

def test_nothing_is_fetched_until_a_zip_code_is_chosen(sky):
    sky.wait(POLL)
    assert sky.stick.fetches == 0
    assert sky.row(0) == (IDLE, None)


def test_a_zip_code_is_five_digits(sky):
    for payload in (b"", b"\x01", b"\x019021", b"\x01902100", b"\x019021A", b"\x01 0210",
                    b"\x0190 10"):
        assert sky.stick.ask(WEATHER, p.NESP_WEATHER_ZIP, payload).status == p.NESP_ST_BAD_ARG
    assert sky.stick.fetches == 0
    assert sky.zip(b"00000") == LOOKING and sky.zip(b"99999") == LOOKING


def test_a_zip_code_there_is_none_of(sky):
    sky.look(b"00000")
    sky.fail(b"THE SITE SAID 404")
    assert sky.zip(b"00000", new=False) == NOT_FOUND and sky.why == b""
    sky.wait(POLL)
    assert not sky.stick.fetching               # and it is not asked after again
    assert sky.stick.zip is None
    sky.look(b"90210")                          # until another is chosen


def test_a_site_that_is_down_is_not_a_zip_code_there_is_none_of(sky):
    sky.look()
    sky.fail(b"THE SITE SAID 500")
    assert sky.zip(new=False) == FAILED and sky.why == b"THE SITE SAID 500"
    fetches = sky.stick.fetches
    sky.wait(POLL)
    assert sky.stick.fetches == fetches         # the console chooses it again
    sky.look()
    sky.fail(b"no route")
    assert sky.zip(new=False) == FAILED and sky.why == b"NO ROUTE"
    sky.look()
    sky.fail(b"")
    assert sky.zip(new=False) == FAILED and sky.why == b"THE FETCH FAILED"


@pytest.mark.parametrize("where", [
    b"", b"{}", b"[]", b'{"places": []}', b'{"places": [{}]}', b'{"places": "none"}',
    where_reply(north=None), where_reply(east="east"), where_reply(north="91"),
    where_reply(east="-180.5"), where_reply(north="nan"), where_reply()[:-20],
    b'{"places": [{"latitude": "34", "longitude": "-118"', b'{"places',
    b'{"places": [{"latitude": "34", "longitude": "-118"}', where_reply() + b"}",
])
def test_an_answer_with_no_place_in_it(sky, where):
    sky.look()
    sky.land(where)
    assert sky.zip(new=False) == FAILED and sky.why == b"THE SITE MADE NO SENSE"
    assert sky.stick.zip is None


def test_a_reply_longer_than_is_read(sky):
    sky.look()
    assert sky.stick.fetch_body(b" " * p.NESP_PAYLOAD_MAX)
    long = b"{" + b" " * 4096
    took = [sky.stick.fetch_body(long[at:at + 512]) for at in range(0, len(long), 512)]
    assert not all(took)
    sky.stick.fetch_done(True)
    sky.wait()
    assert sky.zip(new=False) == FAILED and sky.why == b"THE SITE MADE NO SENSE"


def test_with_no_network_nothing_is_asked(stick):
    sky = Sky(stick, online=False)
    assert sky.zip() == NO_WIFI
    sky.wait(1000)
    assert stick.fetches == 0
    stick.set_wifi(p.NESP_WIFI_JOINED, address=(10, 0, 0, 2))
    assert sky.zip(new=False) == LOOKING
    sky.wait()
    assert stick.fetching


def test_a_fetch_that_cannot_be_started(sky):
    sky.stick.refuse_fetches()
    assert sky.zip() == LOOKING
    sky.wait()
    assert sky.zip(new=False) == FAILED and sky.why == b"THE NESP32 IS BUSY"


def test_the_same_request_again_only_asks_how_it_stands(sky):
    sky.look()
    for _ in range(5):
        assert sky.zip(new=False) == LOOKING
        sky.wait(10)
    assert sky.stick.fetches == 1
    sky.land(where_reply())
    for _ in range(5):
        assert sky.zip(new=False) == FETCHING
        sky.wait(10)
    assert sky.stick.fetches == 2


def test_a_new_zip_code_drops_the_old_ones_report(sky):
    sky.report()
    assert sky.zip(b"10001") == LOOKING and sky.serial == 0
    assert sky.row(0) == (LOOKING, None)
    assert sky.stick.shown(0) == ""


def test_what_an_old_fetch_brings_is_dropped(sky):
    sky.look()
    old = sky.stick.fetch_id
    assert sky.zip(b"10001") == LOOKING
    sky.wait()
    assert not sky.stick.fetch_body(where_reply(), fetch=old)
    sky.stick.fetch_done(True, fetch=old)
    sky.wait()
    assert sky.zip(b"10001", new=False) == LOOKING
    sky.land(where_reply(name="New York", state="NY", north="40.7484", east="-73.9967"))
    sky.land(weather_reply())
    assert sky.zip(b"10001", new=False) == READY
    assert sky.row(0)[1] == "NEW YORK, NY           10001"


def test_a_row_of_another_zip_code_is_told_so(sky):
    sky.report()
    reply = sky.stick.ask(WEATHER, p.NESP_WEATHER_ROW, bytes((sky.id + 1, 0)))
    assert reply.ok and reply.payload == bytes((IDLE, sky.id + 1, 0, 0))


def test_a_row_there_is_none_of_and_a_console_with_no_room_for_one(stick):
    sky = Sky(stick)
    sky.report()
    for payload in (b"", bytes((sky.id,)), bytes((sky.id, ROWS)), bytes((sky.id, 0, 0))):
        assert stick.ask(WEATHER, p.NESP_WEATHER_ROW, payload).status == p.NESP_ST_BAD_ARG
    assert stick.ask(WEATHER, 0x7F).status == p.NESP_ST_NO_OP
    assert stick.hello(app=b"WTHR", services=[WEATHER], reply_max=31).ok
    assert stick.ask(WEATHER, p.NESP_WEATHER_ROW, b"\x01\x00").status == p.NESP_ST_BAD_ARG


# --- the weather, by the clock ---------------------------------------------------

def test_the_weather_is_fetched_again_while_the_console_goes_on_asking(sky):
    sky.report(now=72)
    first = sky.serial
    fetches = sky.stick.fetches
    for _ in range(POLL // 1000 - 1):
        assert sky.zip(new=False) == READY
        sky.wait(1000)
    assert sky.stick.fetches == fetches
    assert sky.zip(new=False) == READY
    sky.wait(1000)
    assert sky.stick.fetches == fetches + 1 and "open-meteo" in sky.stick.fetch_url
    assert sky.zip(new=False) == READY and sky.serial == first      # the old one, meanwhile
    sky.land(weather_reply(now=65))
    assert sky.zip(new=False) == READY and sky.serial not in (0, first)
    assert sky.row(2)[1][4:8] == "65" + DEGREE + "F"
    assert sky.stick.shown(0) == "90210: 65F"


def test_nothing_is_fetched_for_a_console_that_has_stopped_asking(sky):
    sky.report()
    fetches = sky.stick.fetches
    sky.wait(UNASKED)
    sky.wait(POLL)
    sky.wait(POLL)
    assert sky.stick.fetches == fetches
    assert sky.zip(new=False) == READY          # and it asks again: the report is old
    sky.wait()
    assert sky.stick.fetches == fetches + 1


def test_a_fetch_that_fails_with_no_report_says_why_and_is_tried_again(sky):
    sky.find()
    sky.fail(b"THE CONNECTION DROPPED")
    assert sky.zip(new=False) == FAILED and sky.why == b"THE CONNECTION DROPPED"
    fetches = sky.stick.fetches
    for _ in range(RETRY // 1000 - 1):
        assert sky.zip(new=False) == FAILED
        sky.wait(1000)
    assert sky.stick.fetches == fetches
    sky.zip(new=False)
    sky.wait(1000)
    assert sky.stick.fetches == fetches + 1
    assert sky.zip(new=False) == FAILED         # until something better has come
    sky.land(weather_reply())
    assert sky.zip(new=False) == READY and sky.why == b""


def test_a_fetch_that_fails_leaves_the_report_there_was(sky):
    rows = sky.report()
    serial = sky.serial
    sky.zip(new=False)
    sky.wait(POLL)
    sky.fail()
    assert sky.rows() == rows and sky.serial == serial
    fetches = sky.stick.fetches
    sky.zip(new=False)
    sky.wait(RETRY)                             # and the next try comes sooner
    assert sky.stick.fetches == fetches + 1


@pytest.mark.parametrize("body", [
    b"", b"{}", b'{"current": {}, "daily": {}}', weather_reply()[:-30],
    weather_reply(now=None), weather_reply(code=None),
    weather_reply(dates=["2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"]),
    weather_reply(dates=["2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16", "soon"]),
    weather_reply(dates=["2026-10-13", "2026-13-14", "2026-10-15", "2026-10-16", "2026-10-17"]),
    weather_reply(highs=[1, 2, 3, 4]), weather_reply(lows=[1, 2, None, 4, 5]),
    weather_reply(codes=[1, 2, 3, 4, "wet"]),
    b'{"error":true,"reason":"Latitude must be in range of -90 to 90"}',
])
def test_a_reply_that_is_not_the_weather(sky, body):
    sky.find()
    sky.land(body)
    assert sky.zip(new=False) == FAILED and sky.why == b"THE SITE MADE NO SENSE"
    assert sky.row(0) == (FAILED, None)


def test_a_console_that_is_reset_starts_again(sky):
    sky.report()
    assert sky.stick.hello(app=b"WTHR", services=[WEATHER]).ok
    assert sky.stick.shown(0) == ""
    assert sky.row(0) == (IDLE, None)
    assert sky.zip(new=False) == FETCHING       # where it is, is known still


# --- the zip code kept over power-off --------------------------------------------

def test_the_last_zip_code_found_is_kept_and_only_when_it_is_news(sky):
    stick = sky.stick
    assert stick.zip is None
    assert stick.ask(WEATHER, p.NESP_WEATHER_LAST).payload == b""
    sky.look(b"00000")
    sky.fail(b"THE SITE SAID 404")
    assert stick.zip is None and stick.zip_keeps == 0       # not one that is nowhere
    sky.find()
    assert stick.zip == (b"90210", 34090100, -118406500, b"BEVERLY HILLS, CA")
    assert stick.zip_keeps == 1
    assert stick.ask(WEATHER, p.NESP_WEATHER_LAST).payload == b"90210"
    assert sky.zip() == FETCHING                # chosen again: nothing to ask or to write
    sky.wait()
    assert stick.zip_keeps == 1 and "open-meteo" in stick.fetch_url
    sky.find(b"10001", where_reply(name="New York", state="NY", north="40.7484",
                                    east="-73.9967"))
    assert stick.zip == (b"10001", 40748400, -73996700, b"NEW YORK, NY")
    assert stick.zip_keeps == 2
    assert stick.ask(WEATHER, p.NESP_WEATHER_LAST).payload == b"10001"


def test_a_nesp32_switched_on_knows_the_zip_code_it_kept(stick):
    stick.zip = (b"90210", 34090100, -118406500, b"BEVERLY HILLS, CA")
    sky = Sky(stick)
    assert stick.ask(WEATHER, p.NESP_WEATHER_LAST).payload == b"90210"
    assert sky.zip() == FETCHING                # with nothing asked of Zippopotam
    sky.wait()
    assert stick.fetch_url == WEATHER_URL % (34.0901, -118.4065)
    sky.land(weather_reply())
    assert sky.rows()[0] == "BEVERLY HILLS, CA      90210"
    assert stick.zip_keeps == 0
    sky.look(b"10001")                          # another zip code is asked after


def test_asking_for_the_last_zip_code_does_not_start_anything(stick):
    stick.zip = (b"90210", 34090100, -118406500, b"BEVERLY HILLS, CA")
    sky = Sky(stick)
    for _ in range(5):
        assert stick.ask(WEATHER, p.NESP_WEATHER_LAST).ok
        sky.wait(POLL)
    assert stick.fetches == 0 and sky.row(0) == (IDLE, None)
    assert stick.ask(WEATHER, p.NESP_WEATHER_LAST, b"\x00").status == p.NESP_ST_BAD_ARG
