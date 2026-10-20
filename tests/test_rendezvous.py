"""The rendezvous's requests and answers (server/rendezvous/src/index.js),
asked of host/rendezvous.py's stand-in for it.

With RENDEZVOUS_URL set, the same is asked of a real one instead:

    cd server/rendezvous && npx wrangler dev
    RENDEZVOUS_URL=http://localhost:8787 .venv/bin/python -m pytest tests/test_rendezvous.py

The tests that need the clock moved are the stand-in's alone."""

import os
import re
import urllib.error
import urllib.request

import pytest

from rendezvous import ALPHABET, HOST_QUIET_S, MET_S, FakeRendezvous

HOST = "192.168.1.20:6502,96.231.60.51:6502"
GUEST = "10.0.0.7:6502,172.56.33.198:41747"
REAL = os.environ.get("RENDEZVOUS_URL")
AGENT = "nesp32-tests"


@pytest.fixture
def server():
    if REAL:
        yield None
        return
    with FakeRendezvous() as fake:
        yield fake


@pytest.fixture
def ask(server):
    base = REAL or server.url

    def get(path):
        try:
            # Cloudflare turns away urllib's own agent (error 1010).
            request = urllib.request.Request(base + path, headers={"User-Agent": AGENT})
            with urllib.request.urlopen(request, timeout=10) as reply:
                return reply.status, reply.read().decode().strip()
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode().strip()
    return get


def opened(ask, app="DRMA", version=1, candidates=HOST):
    status, line = ask(f"/v1/host?app={app}&ver={version}&c={candidates}")
    assert status == 200, line
    word, code, session = line.split()
    assert word == "ROOM"
    return code, session


def fake_only(server):
    if server is None:
        pytest.skip("the clock of a real rendezvous cannot be moved")


def test_a_room_has_a_code_and_a_session(ask):
    code, session = opened(ask)
    assert len(code) == 4 and all(letter in ALPHABET for letter in code)
    assert re.fullmatch(r"[0-9A-F]{8}", session) and int(session, 16) & 1


def test_the_two_are_given_each_others_candidates(ask):
    code, session = opened(ask)
    assert ask(f"/v1/room/{code}?s={session}&c={HOST}") == (200, "WAIT")
    assert ask(f"/v1/join/{code}?app=DRMA&ver=1&c={GUEST}") == (200, f"HOST {session} {HOST}")
    assert ask(f"/v1/room/{code}?s={session}&c={HOST}") == (200, f"GUEST {GUEST}")


def test_a_code_is_taken_in_any_case(ask):
    code, session = opened(ask)
    assert ask(f"/v1/join/{code.lower()}?app=DRMA&ver=1&c={GUEST}")[1].startswith("HOST ")


def test_another_game_or_version_is_refused(ask):
    code, _ = opened(ask)
    assert ask(f"/v1/join/{code}?app=TTRS&ver=1&c={GUEST}") == (200, "MISMATCH")
    assert ask(f"/v1/join/{code}?app=DRMA&ver=2&c={GUEST}") == (200, "MISMATCH")


def test_a_join_asked_again_is_answered_again_and_a_third_is_not(ask):
    code, session = opened(ask)
    first = ask(f"/v1/join/{code}?app=DRMA&ver=1&c={GUEST}")
    assert ask(f"/v1/join/{code}?app=DRMA&ver=1&c={GUEST}") == first
    assert ask(f"/v1/join/{code}?app=DRMA&ver=1&c=8.8.8.8:1") == (200, "FULL")


def test_no_such_room(server, ask):
    fake_only(server)           # a real one may have the code open, one time in a million
    assert ask(f"/v1/join/ZZZZ?app=DRMA&ver=1&c={GUEST}") == (200, "NOROOM")


def test_only_the_hosts_session_may_ask_after_player_2(ask):
    code, session = opened(ask)
    other = "00000001" if session != "00000001" else "00000003"
    assert ask(f"/v1/room/{code}?s={other}&c={HOST}") == (200, "GONE")


def test_a_host_that_moved_is_found_where_it_went(ask):
    code, session = opened(ask)
    moved = "192.168.1.20:6502,96.231.60.51:7000"
    assert ask(f"/v1/room/{code}?s={session}&c={moved}") == (200, "WAIT")
    assert ask(f"/v1/join/{code}?app=DRMA&ver=1&c={GUEST}") == (200, f"HOST {session} {moved}")


@pytest.mark.parametrize("path", [
    "/v1/host?app=DRMA&ver=1",
    "/v1/host?app=DRMA&ver=1&c=1.2.3.4",
    "/v1/host?app=DRMA&ver=1&c=1.2.3.256:1",
    "/v1/host?app=drma&ver=1&c=1.2.3.4:5",
    "/v1/host?app=DRMA&ver=256&c=1.2.3.4:5",
    "/v1/host?app=DRMA&ver=1&c=" + ",".join(["1.2.3.4:5"] * 5),
    "/v1/join/K7Q0?app=DRMA&ver=1&c=1.2.3.4:5",
    "/v1/join/K7Q?app=DRMA&ver=1&c=1.2.3.4:5",
    "/v1/room/K7QF?s=nothex&c=1.2.3.4:5",
    "/v1/nothing/K7QF?c=1.2.3.4:5",
    "/v2/host?app=DRMA&ver=1&c=1.2.3.4:5",
])
def test_what_is_not_a_request_is_bad(ask, path):
    status, line = ask(path)
    assert line == "BAD" and status in (400, 404)


def test_a_room_whose_host_stops_asking_is_forgotten(server, ask):
    fake_only(server)
    code, session = opened(ask)
    server.now += HOST_QUIET_S + 1
    assert ask(f"/v1/join/{code}?app=DRMA&ver=1&c={GUEST}") == (200, "NOROOM")
    assert ask(f"/v1/room/{code}?s={session}&c={HOST}") == (200, "GONE")


def test_a_host_that_keeps_asking_keeps_its_room(server, ask):
    fake_only(server)
    code, session = opened(ask)
    for _ in range(4):
        server.now += HOST_QUIET_S - 1
        assert ask(f"/v1/room/{code}?s={session}&c={HOST}") == (200, "WAIT")
    assert ask(f"/v1/join/{code}?app=DRMA&ver=1&c={GUEST}")[1].startswith("HOST ")


def test_a_room_that_met_is_forgotten_a_minute_after(server, ask):
    fake_only(server)
    code, session = opened(ask)
    ask(f"/v1/join/{code}?app=DRMA&ver=1&c={GUEST}")
    server.now += MET_S + 1
    assert ask(f"/v1/room/{code}?s={session}&c={HOST}") == (200, "GONE")
