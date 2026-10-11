"""RADAR, NES Radar's service, with no console: requests in, replies out,
and the test in place of Wikidata, of adsb.fi and of the clock.

What a scene is to hold is nes-radar's to say: where its server's own code
is here (the submodule in third_party), the service's scenes are held to
the bytes that code makes of the same reply."""

import json
import os
import random
import sys
import types

import nesp_proto as p
import pytest

RADAR = p.NESP_SVC_RADAR
IDLE, NO_WIFI, NOT_FOUND = p.NESP_SCOPE_IDLE, p.NESP_SCOPE_NO_WIFI, p.NESP_SCOPE_NOT_FOUND
WAITING, READY = p.NESP_SCOPE_WAITING, p.NESP_SCOPE_READY
LOOKING, NO_LOOKUP = p.NESP_SCOPE_LOOKING, p.NESP_SCOPE_NO_LOOKUP
STALE, TRUNCATED, DOWN = p.NESP_SCENE_STALE, p.NESP_SCENE_TRUNCATED, p.NESP_SCENE_DOWN
TARGETS, MOTION, NAMES = p.NESP_RADAR_TARGETS_MAX, p.NESP_RADAR_MOTION_LEN, p.NESP_RADAR_NAMES_LEN
POLL, STALE_MS, UNASKED = p.NESP_RADAR_POLL_MS, p.NESP_RADAR_STALE_MS, p.NESP_RADAR_UNASKED_MS
HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
SERVER = os.path.join(HERE, "..", "third_party", "nes-radar", "server", "src")
# Where Wikidata says a few airports are.
PLACES = {"KLAX": (33.942501, -118.407997), "KSBA": (34.4262, -119.8404),
          "EGLL": (51.4706, -0.461941), "NZSP": (-90.0, 0.0), "AAAA": (0.0, 179.999)}
BLANK = b" " * (NAMES - 1)


def klax():
    with open(os.path.join(FIXTURES, "klax_adsbfi.json"), "rb") as handle:
        return handle.read()


def plane(north, east, place=PLACES["KLAX"], **more):
    """An aircraft this many degrees north and east of a place."""
    item = {"hex": "abc123", "flight": "TEST1   ", "r": "N1", "t": "B738", "alt_baro": 5000,
            "gs": 250.0, "track": 90.0, "baro_rate": 0, "squawk": "1200", "category": "A3",
            "lat": place[0] + north, "lon": place[1] + east}
    item.update(more)
    return {key: value for key, value in item.items() if value is not ...}


def reply_of(aircraft):
    return json.dumps({"ac": aircraft, "msg": "No error", "now": 1, "total": len(aircraft)},
                      separators=(",", ":")).encode("utf-8")


def where_reply(place):
    """Wikidata's answer to where an airport is: the place, or nothing."""
    found = [] if place is None else [{"p": {
        "datatype": "http://www.opengis.net/ont/geosparql#wktLiteral", "type": "literal",
        "value": "Point(%r %r)" % (place[1], place[0])}}]
    return json.dumps({"head": {"vars": ["p"]}, "results": {"bindings": found}},
                      indent=2).encode("utf-8")


def where_url(code):
    return ("https://query.wikidata.org/sparql?format=json&query=SELECT%%20%%3Fp%%20WHERE%%20"
            "%%7B%%20%%3Fa%%20wdt%%3AP239%%20%%22%s%%22%%3B%%20wdt%%3AP625%%20%%3Fp%%20%%7D"
            "%%20LIMIT%%201" % code)


class Scope:
    """A console's side of the service, and the clock."""

    def __init__(self, stick, online=True, places=PLACES):
        self.stick = stick
        self.places = places
        self.now = 1000
        if online:
            stick.set_wifi(p.NESP_WIFI_JOINED, address=(10, 0, 0, 2))
        assert stick.hello(app=b"RADR", services=[RADAR]).ok
        self.id = 0

    def wait(self, ms=0):
        self.now += ms
        self.stick.tick(self.now)

    def airport(self, code, new=True):
        """The state of an airport: a new choice, or the last again."""
        if new:
            self.id = (self.id + 1) & 0xFF
        reply = self.stick.ask(RADAR, p.NESP_RADAR_AIRPORT, bytes((self.id,)) + code)
        assert reply.ok and len(reply.payload) == 2 and reply.payload[1] == self.id
        return reply.payload[0]

    def scene(self, have=0):
        """(state, serial, names' serial, flags, [motion]) with a scene the
        console has not; (state, serial, names' serial) with none."""
        reply = self.stick.ask(RADAR, p.NESP_RADAR_SCENE, bytes((self.id, have)))
        assert reply.ok and reply.payload[1] == self.id
        state, serial, names = reply.payload[0], reply.payload[2], reply.payload[3]
        if len(reply.payload) == 4:
            return state, serial, names
        flags, count = reply.payload[4], reply.payload[5]
        records = reply.payload[6:]
        assert state == READY and serial != 0 and names != 0
        assert count <= TARGETS and len(records) == count * MOTION
        motion = [records[at:at + MOTION] for at in range(0, len(records), MOTION)]
        assert [record[0] & 7 for record in motion] == list(range(count))
        return state, serial, names, flags, motion

    def names(self, slot):
        reply = self.stick.ask(RADAR, p.NESP_RADAR_IDENTITY, bytes((self.id, slot)))
        assert reply.ok and reply.payload[1] == self.id
        if len(reply.payload) == 3:
            return reply.payload[0], reply.payload[2], None
        assert len(reply.payload) == 3 + NAMES and reply.payload[3] == slot
        return reply.payload[0], reply.payload[2], reply.payload[4:]

    def all_names(self):
        return [self.names(slot)[2] for slot in range(TARGETS)]

    def land(self, body, pieces=None, ok=True):
        """The fetch under way ends with this reply."""
        assert self.stick.fetching
        for at in range(0, len(body), pieces or len(body) or 1):
            assert self.stick.fetch_body(body[at:at + (pieces or len(body))])
        self.stick.fetch_done(ok)
        self.wait()

    def fail(self):
        assert self.stick.fetching
        self.stick.fetch_done(False, b"no route")
        self.wait()

    def look(self, code):
        """Choose an airport nobody has asked after, and be at the fetch of
        where it is."""
        assert self.airport(code) == LOOKING
        self.wait()
        assert self.stick.fetching and self.stick.fetch_url == where_url(code.decode())

    def watch(self, code=b"KLAX"):
        """Choose an airport, be told where it is, and be at the fetch of
        its aircraft."""
        self.look(code)
        self.land(where_reply(self.places[code.decode()]))
        assert self.airport(code, new=False) == WAITING
        assert self.stick.fetching and "adsb.fi" in self.stick.fetch_url


@pytest.fixture
def scope(stick):
    return Scope(stick)


# --- nes-radar's own code, for what a scene should be --------------------------

@pytest.fixture(scope="module")
def theirs():
    """nes-radar's server, as a module. It is the scene's arithmetic that
    is wanted of it, so the two libraries it talks to the world with need
    not be here."""
    if not os.path.isfile(os.path.join(SERVER, "nes_radar_server.py")):
        pytest.skip("no nes-radar in third_party: git submodule update --init")
    stubs = {}
    for name in ("serial", "serial.tools", "serial.tools.list_ports", "certifi"):
        if name not in sys.modules:
            stubs[name] = sys.modules[name] = types.ModuleType(name)
    if "serial" in stubs:
        stubs["serial"].SerialException = OSError
        stubs["serial"].Serial = object
        stubs["serial"].tools = stubs["serial.tools"]
        stubs["serial.tools"].list_ports = stubs["serial.tools.list_ports"]
        stubs["serial.tools.list_ports"].comports = lambda: []
    if "certifi" in stubs:
        stubs["certifi"].where = lambda: os.devnull
    sys.path.insert(0, SERVER)
    dont = sys.dont_write_bytecode
    sys.dont_write_bytecode = True      # nothing of ours in the submodule
    try:
        import nes_radar_server
    finally:
        sys.dont_write_bytecode = dont
        sys.path.remove(SERVER)
        for name in stubs:
            del sys.modules[name]
    return nes_radar_server


def their_scene(theirs, body, place):
    """(flags, [motion], [names]) as nes-radar's server makes them."""
    spot = theirs.C64.Scope(place[0], place[1]).validated()
    targets = theirs.extract_targets_with_details(json.loads(body.decode("utf-8")), spot)
    assigned = theirs.SlotAllocator().assign(targets)
    flags = TRUNCATED if len(targets) > TARGETS else 0
    return (flags, [target.encode() for target in assigned.targets],
            [identity.encode()[1:] for identity in assigned.identities])


def our_scene(scope, body, pieces=None):
    scope.land(body, pieces)
    _, _, _, flags, motion = scope.scene()
    return flags, motion, scope.all_names()


def test_the_flags_are_nes_radars(theirs):
    assert (STALE, TRUNCATED, DOWN) == (theirs.SCENE_STALE, theirs.SCENE_TRUNCATED,
                                        theirs.SCENE_UPSTREAM_DOWN)
    assert (p.NESP_SCENE_BAD_DATA, p.NESP_SCENE_BAD_PLACE) == (0x08, 0x10)


def test_a_real_reply_makes_the_scene_nes_radar_makes_of_it(scope, theirs):
    scope.watch()
    body = klax()
    ours = our_scene(scope, body, pieces=1024)
    assert ours == their_scene(theirs, body, PLACES["KLAX"])
    assert len(ours[1]) == 7 and ours[0] == 0      # of the 43, the ones flying and near


@pytest.mark.parametrize("pieces", [1, 7, 333])
def test_however_the_reply_is_cut_up(scope, theirs, pieces):
    scope.watch()
    body = klax()
    assert our_scene(scope, body, pieces) == their_scene(theirs, body, PLACES["KLAX"])


def made_up(rng, place):
    """An aircraft with whatever a real one might have or lack."""
    def maybe(value, share=0.85):
        return value if rng.random() < share else ...

    def figure(low, high):
        value = rng.uniform(low, high)
        kind = rng.random()
        if kind < 0.1:
            return round(value)
        if kind < 0.15:
            return "%.1f" % value
        if kind < 0.2:
            return None
        return round(value, rng.choice((0, 1, 2, 6)))

    letters = "ABCXYZabc0189 -_/.é日😀\"\\\t"
    def text(most):
        return "".join(rng.choice(letters) for _ in range(rng.randint(0, most)))

    spread = rng.choice((0.02, 0.1, 0.2))
    altitude = rng.choice(("ground", "Ground", None, figure(-500, 45000), figure(0, 9000)))
    return plane(
        rng.uniform(-spread, spread), rng.uniform(-spread, spread), place,
        hex=maybe("%06x" % rng.getrandbits(24)), flight=maybe(text(10)), r=maybe(text(8)),
        t=maybe(text(5)), alt_baro=maybe(altitude), gs=maybe(figure(0, 600)),
        track=maybe(figure(0, 360)), true_heading=maybe(figure(0, 360), 0.3),
        baro_rate=maybe(figure(-12000, 12000), 0.6), geom_rate=maybe(figure(-6000, 6000), 0.6),
        squawk=maybe(text(5)), category=maybe(text(3)),
        lastPosition=maybe({"lat": 1.0, "lon": 2.0, "seen_pos": 3}, 0.2),
        mlat=maybe(["lat", "lon", {"gs": 1}], 0.3))


@pytest.mark.parametrize("seed", range(40))
def test_made_up_replies_make_the_scenes_nes_radar_makes_of_them(stick, theirs, seed):
    rng = random.Random(seed)
    code = rng.choice(sorted(PLACES))
    scope = Scope(stick)
    scope.watch(code.encode())
    aircraft = [made_up(rng, PLACES[code]) for _ in range(rng.randint(0, 14))]
    body = json.dumps({"now": 1.5, "ac": aircraft, "msg": "No error"},
                      ensure_ascii=bool(seed & 1)).encode("utf-8")
    assert our_scene(scope, body, rng.choice((None, 64, 1000))) == their_scene(
        theirs, body, PLACES[code])


# --- the airport ---------------------------------------------------------------

def test_it_answers_only_after_a_hello_asks_for_it(stick):
    assert stick.ask(RADAR, p.NESP_RADAR_SCENE, b"\1\0").status == p.NESP_ST_INACTIVE
    assert stick.hello(services=[RADAR]).ok
    assert stick.ask(RADAR, p.NESP_RADAR_SCENE, b"\1\0").payload == bytes((IDLE, 1, 0, 0))
    assert stick.ask(RADAR, p.NESP_RADAR_IDENTITY, b"\1\0").payload == bytes((IDLE, 1, 0))
    assert stick.ask(RADAR, 0x7F).status == p.NESP_ST_NO_OP


@pytest.mark.parametrize("payload", [b"", b"\1KLA", b"\1KLAXX", b"\1klax", b"\1KL4X", b"\1K AX"])
def test_an_airport_is_an_id_and_four_capitals(scope, payload):
    assert scope.stick.ask(RADAR, p.NESP_RADAR_AIRPORT, payload).status == p.NESP_ST_BAD_ARG


def test_an_airport_nobody_has_heard_of(scope):
    scope.look(b"KZZZ")
    scope.land(where_reply(None))
    assert scope.airport(b"KZZZ", new=False) == NOT_FOUND
    scope.wait(POLL)
    assert scope.stick.fetches == 1 and not scope.stick.fetching
    assert scope.scene() == (NOT_FOUND, 0, 0)
    scope.watch(b"KLAX")


def test_where_an_airport_is_comes_however_it_is_cut_up(scope):
    scope.look(b"EGLL")
    scope.land(where_reply(PLACES["EGLL"]), pieces=3)
    assert scope.airport(b"EGLL", new=False) == WAITING
    assert scope.stick.fetch_url == "https://opendata.adsb.fi/api/v3/lat/51.470600/lon/-0.461941/dist/10"
    assert scope.stick.shown(0) == "EGLL"


@pytest.mark.parametrize("place", ["Point(1.5)", "Point(abc def)", "Point(1.5 2.5 3.5)",
                                   "Point(181.0 2.0)", "Point(2.0 -90.5)", "Point(1,2)",
                                   "Point(" + "1" * 60 + " 2)", "point(1.0 2.0)"])
def test_a_place_that_is_not_one_is_no_airport(scope, place):
    scope.look(b"KLAX")
    scope.land(json.dumps({"results": {"bindings": [{"p": {"value": place}}]}}).encode())
    assert scope.airport(b"KLAX", new=False) == NOT_FOUND


@pytest.mark.parametrize("place, url", [
    ("Point(-118.5 34)", "/lat/34.000000/lon/-118.500000/"),
    ("Point(1.76914166666E2 -37.920555555)", "/lat/-37.920556/lon/176.914167/"),
    ("PPoint(-180 90)", "/lat/90.000000/lon/-180.000000/")])
def test_a_place_is_a_longitude_and_a_latitude(scope, place, url):
    scope.look(b"KLAX")
    scope.land(json.dumps({"results": {"bindings": [{"p": {"value": place}}]}}).encode())
    assert scope.airport(b"KLAX", new=False) == WAITING and url in scope.stick.fetch_url


@pytest.mark.parametrize("body", [b"", b"<html>429 Too Many Requests</html>",
                                  b'{"results":{"bindings":[{"p":{"value":"Point(1.0 2.0)"}}]'])
def test_an_asking_that_fails_is_not_no_such_airport(scope, body):
    scope.look(b"KLAX")
    scope.land(body)
    assert scope.airport(b"KLAX", new=False) == NO_LOOKUP
    assert scope.scene() == (NO_LOOKUP, 0, 0)
    scope.wait(POLL)
    assert scope.stick.fetches == 1         # nothing more until it is chosen again
    scope.watch(b"KLAX")


def test_a_site_that_does_not_answer(scope):
    scope.look(b"KLAX")
    scope.stick.fetch_done(False, b"no route")
    scope.wait()
    assert scope.airport(b"KLAX", new=False) == NO_LOOKUP
    scope.stick.refuse_fetches()
    assert scope.airport(b"KSBA") == LOOKING
    scope.wait()
    assert scope.airport(b"KSBA", new=False) == NO_LOOKUP


def test_the_last_airport_found_is_not_asked_after_again(scope):
    scope.watch(b"KSBA")
    scope.land(reply_of([plane(0.01, 0.0, PLACES["KSBA"])]))
    fetches = scope.stick.fetches
    assert scope.airport(b"KSBA") == WAITING            # chosen again: Select, and Start
    scope.wait()
    assert scope.stick.fetches == fetches + 1 and "adsb.fi" in scope.stick.fetch_url
    assert scope.stick.hello(app=b"RADR", services=[RADAR]).ok
    assert scope.airport(b"KSBA") == WAITING            # and by a console that was reset
    scope.look(b"KLAX")                                 # but another is


def test_the_fetch_is_the_one_nes_radar_makes(scope, theirs):
    scope.watch(b"KSBA")
    spot = theirs.C64.Scope(*PLACES["KSBA"]).validated()
    assert scope.stick.fetch_url == theirs.C64.provider_url(theirs.C64.ADSB_FI_BASE, spot)
    assert "nesp32" in scope.stick.fetch_agent


def test_with_no_wifi_it_says_so_and_fetches_nothing(stick):
    scope = Scope(stick, online=False)
    assert scope.airport(b"KLAX") == NO_WIFI
    scope.wait(POLL)
    assert stick.fetches == 0 and scope.scene() == (NO_WIFI, 0, 0)
    # When there is a network the asking begins.
    stick.set_wifi(p.NESP_WIFI_JOINED, address=(10, 0, 0, 2))
    assert scope.airport(b"KLAX", new=False) == LOOKING
    scope.wait()
    scope.land(where_reply(PLACES["KLAX"]))
    # A fetch of the aircraft that cannot be made is a failed one: the scene
    # that was, or one with nothing in it, and flags that say why.
    scope.land(reply_of([plane(0.01, 0.0)]))
    stick.set_wifi(p.NESP_WIFI_IDLE)
    scope.scene()
    scope.wait(POLL)
    assert stick.fetches == 2 and len(scope.scene()[4]) == 1 and scope.scene()[3] == DOWN


def test_the_same_airport_again_only_asks_how_it_stands(scope):
    scope.watch()
    scope.land(reply_of([plane(0.01, 0.01)]))
    assert scope.airport(b"KLAX", new=False) == READY
    scope.wait()
    assert scope.stick.fetches == 2 and scope.scene()[0] == READY     # where, and what
    # The same letters under a new id are a new choice, of an airport whose
    # place is known.
    assert scope.airport(b"KLAX") == WAITING
    assert scope.scene() == (WAITING, 0, 0)


def test_a_request_about_another_airport_is_told_so(scope):
    scope.watch()
    scope.land(reply_of([plane(0.01, 0.01)]))
    stick = scope.stick
    assert stick.ask(RADAR, p.NESP_RADAR_SCENE, b"\x09\0").payload == bytes((IDLE, 9, 0, 0))
    assert stick.ask(RADAR, p.NESP_RADAR_IDENTITY, b"\x09\0").payload == bytes((IDLE, 9, 0))
    assert stick.ask(RADAR, p.NESP_RADAR_IDENTITY, bytes((scope.id, 8))).status == p.NESP_ST_BAD_ARG
    assert stick.ask(RADAR, p.NESP_RADAR_SCENE, bytes((scope.id,))).status == p.NESP_ST_BAD_ARG


def test_a_console_that_takes_short_replies_is_refused_a_scene(stick):
    assert stick.hello(app=b"RADR", reply_max=63, services=[RADAR]).ok
    assert stick.ask(RADAR, p.NESP_RADAR_AIRPORT, b"\1KLAX").ok
    assert stick.ask(RADAR, p.NESP_RADAR_SCENE, b"\1\0").status == p.NESP_ST_BAD_ARG


# --- the scene -----------------------------------------------------------------

def test_a_scene_is_sent_only_to_a_console_that_has_not_got_it(scope):
    scope.watch()
    assert scope.scene() == (WAITING, 0, 0)
    scope.land(reply_of([plane(0.05, 0.0), plane(0.01, 0.0, flight="NEAR")]))
    state, serial, names, flags, motion = scope.scene()
    assert (state, flags, len(motion)) == (READY, 0, 2)
    assert motion[0][8] < motion[1][8]             # the nearest first
    assert motion[0][1] == 72 and motion[0][2] < 72 < 144   # due north of the middle
    assert scope.scene(have=serial) == (READY, serial, names)
    assert scope.names(0)[2][:8] == b"NEAR    " and scope.names(1)[2][:8] == b"TEST1   "
    assert scope.names(2) == (READY, names, BLANK)


def test_every_fetch_is_a_new_scene_and_new_names_only_if_they_changed(scope):
    scope.watch()
    scope.land(reply_of([plane(0.01, 0.0)]))
    _, serial, names, _, first = scope.scene()
    scope.wait(POLL)
    scope.land(reply_of([plane(0.02, 0.0)]))
    _, serial2, names2, _, second = scope.scene(serial)
    assert serial2 != serial and names2 == names and second != first
    scope.wait(POLL)
    scope.land(reply_of([plane(0.02, 0.0, squawk="7700")]))
    _, serial3, names3, _, _ = scope.scene(serial2)
    assert serial3 != serial2 and names3 != names
    assert scope.names(0)[2][18:22] == b"7700"


def test_a_serial_is_never_the_one_a_console_with_nothing_has(scope):
    scope.watch()
    seen = set()
    for number in range(600):
        scope.land(reply_of([plane(0.01, 0.0, squawk="%04d" % number)]))
        state, serial, names, _, _ = scope.scene()
        seen.update((serial, names))
        scope.wait(POLL)
    assert 0 not in seen and len(seen) == 255


def test_more_than_eight_and_the_scene_says_so(scope):
    scope.watch()
    near = [plane(0.001 * (number + 1), 0.0, flight="N%d" % number) for number in range(9)]
    far = [plane(0.5, 0.0), plane(0.0, 0.01, alt_baro="ground"), plane(0.0, 0.01, gs=39.9)]
    scope.land(reply_of(list(reversed(near)) + far))
    _, _, _, flags, motion = scope.scene()
    assert flags == TRUNCATED and len(motion) == 8
    assert [scope.names(slot)[2][:2] for slot in range(8)] == [b"N%d" % n for n in range(8)]
    scope.wait(POLL)
    scope.land(reply_of(near[:8] + far))
    assert scope.scene()[3] == 0


def test_a_fetch_that_fails_keeps_the_scene_and_flags_it(scope):
    scope.watch()
    scope.land(reply_of([plane(0.01, 0.0)]))
    _, serial, names, _, motion = scope.scene()
    scope.wait(POLL)
    scope.fail()
    state, serial2, names2, flags, kept = scope.scene(serial)
    assert (state, flags, kept, names2) == (READY, DOWN, motion, names) and serial2 != serial
    # Stale once nothing good has come for long enough.
    while scope.now < 1000 + STALE_MS:
        scope.scene()
        scope.wait(POLL)
        scope.fail()
    assert scope.scene()[3:] == (STALE | DOWN, motion)
    scope.wait(POLL)
    scope.land(reply_of([]))
    assert scope.scene()[3:] == (0, [])
    assert scope.names(0)[2] == BLANK


def test_a_first_fetch_that_fails_is_a_scene_with_nothing_in_it(scope):
    scope.watch()
    scope.fail()
    state, serial, names, flags, motion = scope.scene()
    assert (state, flags, motion) == (READY, STALE | DOWN, [])
    assert scope.all_names() == [BLANK] * 8


@pytest.mark.parametrize("body", [
    b"", b"<html>502 Bad Gateway</html>", b'{"ac":[{"lat":33.95,"lon":-118.4}',
    b'{"ac":[{"lat":33.95,"lon":-118.4}]', b"[]"])
def test_a_reply_that_is_not_a_whole_one_is_a_failed_fetch(scope, body):
    scope.watch()
    scope.land(body)
    assert scope.scene()[3:] == (STALE | DOWN, [])


def test_a_fetch_that_cannot_start_is_a_failed_one(scope):
    scope.look(b"KLAX")
    scope.stick.refuse_fetches()
    scope.land(where_reply(PLACES["KLAX"]))
    assert scope.scene()[3:] == (STALE | DOWN, [])


def test_an_aircraft_too_long_to_read_is_passed_over(scope):
    scope.watch()
    long = plane(0.01, 0.0, flight="LONG", desc="x" * 3000)
    scope.land(reply_of([long, plane(0.02, 0.0, flight="SHORT"), long]), pieces=500)
    _, _, _, flags, motion = scope.scene()
    assert len(motion) == 1 and scope.names(0)[2][:8] == b"SHORT   "


def test_a_reply_with_other_lists_in_it(scope):
    scope.watch()
    body = json.dumps({"other": [plane(0.01, 0.0, flight="NOT")], "nested": {"ac": [plane(0.01, 0)]},
                       "aircraft": [plane(0.01, 0.0, flight="YES")], "ac ": [plane(0.01, 0.0)]})
    scope.land(body.encode())
    assert len(scope.scene()[4]) == 1 and scope.names(0)[2][:8] == b"YES     "


# --- the clock -----------------------------------------------------------------

def test_a_fetch_every_few_seconds_while_the_console_asks(scope):
    scope.watch()
    stick = scope.stick
    scope.land(reply_of([]))
    first = stick.fetches
    for fetch in range(first + 1, first + 5):
        scope.scene()
        scope.wait(POLL - 1)
        assert stick.fetches == fetch - 1 and not stick.fetching
        scope.wait(1)
        assert stick.fetches == fetch and stick.fetching
        scope.land(reply_of([]))


def test_a_slow_fetch_is_not_replaced_and_the_next_follows_it(scope):
    scope.watch()
    for _ in range(3):
        scope.scene()
        scope.wait(POLL)
    assert scope.stick.fetches == 2
    scope.land(reply_of([]))
    assert scope.stick.fetches == 3 and scope.stick.fetching


def test_no_fetch_for_a_console_that_has_stopped_asking(scope):
    scope.watch()
    scope.land(reply_of([]))
    scope.wait(UNASKED - 1)
    fetches = scope.stick.fetches
    scope.land(reply_of([]))
    for _ in range(10):
        scope.wait(POLL)
    assert scope.stick.fetches == fetches and not scope.stick.fetching
    scope.scene()
    scope.wait()
    assert scope.stick.fetching


def test_the_clock_may_wrap(stick):
    scope = Scope(stick)
    scope.now = 0xFFFFFFFF - POLL - 5
    scope.watch()
    scope.land(reply_of([plane(0.01, 0.0)]))
    for _ in range(4):
        scope.scene()
        scope.wait(POLL)
        scope.land(reply_of([plane(0.01, 0.0)]))
        assert scope.scene()[3] == 0


# --- one airport, then another ------------------------------------------------

def test_an_old_airports_aircraft_never_reach_a_new_ones_scene(scope):
    scope.watch()
    old = scope.stick.fetch_id
    assert scope.stick.fetch_body(b'{"ac":[' + json.dumps(plane(0.01, 0.0)).encode(), fetch=old)
    assert scope.airport(b"KSBA") == LOOKING
    assert scope.stick.fetch_stops >= 1
    assert not scope.stick.fetch_body(b"]}", fetch=old)
    scope.stick.fetch_done(True, fetch=old)
    scope.wait()
    assert scope.scene() == (LOOKING, 0, 0)
    # Nor does where the old one is, if that is what was still on its way.
    late = scope.stick.fetch_id
    assert scope.airport(b"EGLL") == LOOKING
    scope.stick.fetch_body(where_reply(PLACES["KSBA"]), fetch=late)
    scope.stick.fetch_done(True, fetch=late)
    scope.wait()
    assert scope.airport(b"EGLL", new=False) == LOOKING
    assert scope.airport(b"KSBA") == LOOKING
    scope.wait()
    scope.land(where_reply(PLACES["KSBA"]))
    assert scope.stick.fetching and "34.426200" in scope.stick.fetch_url
    scope.land(reply_of([plane(0.01, 0.0, PLACES["KSBA"], flight="SBA")]))
    assert scope.names(0)[2][:8] == b"SBA     "


def test_a_new_hello_forgets_the_airport(scope):
    scope.watch()
    scope.land(reply_of([plane(0.01, 0.0)]))
    assert scope.stick.shown(0) == "KLAX: 1 aircraft"
    assert scope.stick.hello(app=b"RADR", services=[RADAR]).ok
    assert scope.scene() == (IDLE, 0, 0)
    scope.wait(POLL)
    assert scope.stick.fetches == 2
    assert scope.stick.hello(app=b"WIKI", services=[]).ok
    assert scope.stick.shown(0) == ""


# --- the airport kept over power-off -------------------------------------------

def test_the_last_airport_found_is_kept_and_only_when_it_is_news(scope):
    stick = scope.stick
    assert stick.airport is None
    assert stick.ask(RADAR, p.NESP_RADAR_LAST).payload == b""
    scope.look(b"KZZZ")
    scope.land(where_reply(None))
    assert stick.airport is None and stick.airport_keeps == 0     # not one that is nowhere
    scope.watch(b"KSBA")
    assert stick.airport == (b"KSBA", 34426200, -119840400) and stick.airport_keeps == 1
    assert stick.ask(RADAR, p.NESP_RADAR_LAST).payload == b"KSBA"
    assert scope.airport(b"KSBA") == WAITING            # chosen again: nothing to write
    scope.wait()
    assert stick.airport_keeps == 1
    scope.watch(b"EGLL")
    assert stick.airport == (b"EGLL", 51470600, -461941) and stick.airport_keeps == 2
    assert stick.ask(RADAR, p.NESP_RADAR_LAST).payload == b"EGLL"
    assert stick.ask(RADAR, p.NESP_RADAR_LAST, b"\0").status == p.NESP_ST_BAD_ARG


def test_a_nesp32_switched_on_knows_the_airport_it_kept(stick):
    stick.airport = (b"KLAX", 33942501, -118407997)
    scope = Scope(stick)
    assert stick.ask(RADAR, p.NESP_RADAR_LAST).payload == b"KLAX"
    assert scope.airport(b"KLAX") == WAITING            # with nothing asked of Wikidata
    scope.wait()
    assert stick.fetch_url == "https://opendata.adsb.fi/api/v3/lat/33.942501/lon/-118.407997/dist/10"
    assert stick.airport_keeps == 0
    scope.look(b"KSBA")                                 # another airport is asked after


def test_asking_for_the_last_airport_does_not_start_anything(stick):
    stick.airport = (b"KLAX", 33942501, -118407997)
    scope = Scope(stick)
    for _ in range(5):
        assert stick.ask(RADAR, p.NESP_RADAR_LAST).ok
        scope.wait(POLL)
    assert stick.fetches == 0 and scope.scene() == (IDLE, 0, 0)
