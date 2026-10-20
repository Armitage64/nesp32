"""A stand-in for the rendezvous (server/rendezvous), on this computer: the
same requests and the same answers, from a room kept in memory, with a
clock the test may set. So two nesp32s, or a nesp32 and a computer
standing in for one, can meet with nothing on the Internet.

    with FakeRendezvous() as server:
        server.url                      "http://127.0.0.1:PORT"
        server.now += 31                seconds, for rooms to expire

Rooms is the same with no server: a test that is the network itself asks
it directly, with answer(path).

The rules are server/rendezvous/src/room.js's, and tests/test_rendezvous.py
asks the same of both.
"""

import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 4
MAX_CANDIDATES = 4
HOST_QUIET_S = 30
LONGEST_S = 15 * 60
MET_S = 60
TRIES = 8

_CANDIDATE = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3}):(\d{1,5})$")


def parse_candidates(text):
    if not text:
        return None
    candidates = text.split(",")
    if len(candidates) > MAX_CANDIDATES:
        return None
    for each in candidates:
        parts = _CANDIDATE.match(each)
        if not parts:
            return None
        numbers = [int(part) for part in parts.groups()]
        if any(byte > 255 for byte in numbers[:4]) or not 1 <= numbers[4] <= 65535:
            return None
    return candidates


def parse_game(app, version):
    if not app or not re.fullmatch(r"[A-Z0-9]{4}", app) or not version \
            or not re.fullmatch(r"\d{1,3}", version) or int(version) > 255:
        return None
    return app, int(version)


class Room:
    def __init__(self, game, candidates, session, now):
        self.game = game
        self.session = session
        self.host = candidates
        self.guest = None
        self.made_at = now
        self.host_seen = now
        self.met_at = None

    def expired(self, now):
        if self.met_at is not None:
            return now - self.met_at > MET_S
        return now - self.host_seen > HOST_QUIET_S or now - self.made_at > LONGEST_S


class Rooms:
    def __init__(self):
        self.now = 0.0
        self.rooms = {}
        self.requests = []          # each path asked, for the tests
        self._lock = threading.Lock()

    def _room(self, code):
        room = self.rooms.get(code)
        if room is not None and room.expired(self.now):
            del self.rooms[code]
            room = None
        return room

    def answer(self, path):
        """(status, line) for a request's path and query."""
        with self._lock:
            self.requests.append(path)
            parts = urlsplit(path)
            query = {key: values[0] for key, values in parse_qs(parts.query).items()}
            steps = [step for step in parts.path.split("/") if step]
            if not steps or steps[0] != "v1":
                return 404, "BAD"
            candidates = parse_candidates(query.get("c"))
            if candidates is None:
                return 400, "BAD"
            if steps[1:] == ["host"]:
                game = parse_game(query.get("app"), query.get("ver"))
                if game is None:
                    return 400, "BAD"
                session = f"{secrets.randbits(32) | 1:08X}"
                for _ in range(TRIES):
                    code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
                    if self._room(code) is None:
                        self.rooms[code] = Room(game, candidates, session, self.now)
                        return 200, f"ROOM {code} {session}"
                return 503, "BUSY"
            if len(steps) != 3 or len(steps[2]) != CODE_LENGTH \
                    or any(letter not in ALPHABET for letter in steps[2].upper()):
                return 400, "BAD"
            code = steps[2].upper()
            room = self._room(code)
            if steps[1] == "room":
                session = query.get("s", "").upper()
                if not re.fullmatch(r"[0-9A-F]{8}", session):
                    return 400, "BAD"
                if room is None or room.session != session:
                    return 200, "GONE"
                room.host_seen = self.now
                room.host = candidates
                return 200, f"GUEST {','.join(room.guest)}" if room.guest else "WAIT"
            if steps[1] == "join":
                game = parse_game(query.get("app"), query.get("ver"))
                if game is None:
                    return 400, "BAD"
                if room is None:
                    return 200, "NOROOM"
                if room.game != game:
                    return 200, "MISMATCH"
                if room.guest is not None and room.guest != candidates:
                    return 200, "FULL"
                if room.guest is None:
                    room.guest = candidates
                    room.met_at = self.now
                return 200, f"HOST {room.session} {','.join(room.host)}"
            return 404, "BAD"


class FakeRendezvous(Rooms):
    """Rooms, answering over HTTP on this machine."""

    def __init__(self):
        super().__init__()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                status, text = fake.answer(self.path)
                body = (text + "\n").encode()
                self.send_response(status)
                self.send_header("content-type", "text/plain")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        kwargs={"poll_interval": 0.02}, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()
