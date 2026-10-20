"""The Stick's firmware on a computer (host/nesp_host.c), from Python.

    stick = Stick(port)         port: read() -> bytes or None, write(bytes)
    stick.poll()                call often: answers the console if it asked

The link and the services are the firmware's own C, built for this machine
by `make host`; only the hardware under them is a stand-in, which the
caller sets (set_wifi, scan_add, ...) and looks into (joins, password, ...).
frame() and parse() are the console's side of a frame, for tests that have
no console.
"""

import ctypes
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.environ.get("NESP_BUILD", os.path.join(HERE, "..", "build"))
sys.path.insert(0, BUILD)

import nesp_proto as proto  # noqa: E402

LIBRARY = "libnesp_host.dylib" if sys.platform == "darwin" else "libnesp_host.so"

_u8p = ctypes.POINTER(ctypes.c_uint8)
# What the firmware asks of the line with framing off (nesp_hal_t's line_*).
_RATE = ctypes.CFUNCTYPE(None, ctypes.c_uint8)
_WRITE = ctypes.CFUNCTYPE(ctypes.c_size_t, _u8p, ctypes.c_size_t)
_IDLE = ctypes.CFUNCTYPE(ctypes.c_bool)
_lib = None


def library():
    global _lib
    if _lib is None:
        lib = ctypes.CDLL(os.path.join(BUILD, LIBRARY))
        lib.host_new.restype = ctypes.c_void_p
        lib.host_free.argtypes = [ctypes.c_void_p]
        lib.host_feed.restype = ctypes.c_size_t
        lib.host_feed.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t, _u8p]
        lib.host_event.argtypes = [ctypes.c_void_p, ctypes.c_uint8, ctypes.c_uint8]
        lib.host_note_turnaround.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        lib.host_set_wifi.argtypes = [ctypes.c_void_p, ctypes.c_uint8, ctypes.c_uint8,
                                      ctypes.c_int8, ctypes.c_char_p]
        lib.host_set_saved.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint8]
        lib.host_set_battery.argtypes = [ctypes.c_void_p, ctypes.c_uint8]
        lib.host_set_drive.argtypes = [ctypes.c_void_p, ctypes.c_uint8]
        lib.host_drive.restype = ctypes.c_uint8
        lib.host_drive.argtypes = [ctypes.c_void_p]
        lib.host_drive_stops.restype = ctypes.c_uint32
        lib.host_drive_stops.argtypes = [ctypes.c_void_p]
        lib.host_set_screen.argtypes = [ctypes.c_void_p, ctypes.c_uint8]
        lib.host_screen.restype = ctypes.c_uint8
        lib.host_screen.argtypes = [ctypes.c_void_p]
        lib.host_set_time.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_uint32]
        lib.host_scan_clear.argtypes = [ctypes.c_void_p]
        lib.host_scan_add.restype = ctypes.c_bool
        lib.host_scan_add.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint8,
                                      ctypes.c_int8, ctypes.c_uint8, ctypes.c_uint8]
        lib.host_scan_finish.argtypes = [ctypes.c_void_p, ctypes.c_uint8]
        for name in ("host_scan_state", "host_wifi_state", "host_app_version"):
            getattr(lib, name).restype = ctypes.c_uint8
            getattr(lib, name).argtypes = [ctypes.c_void_p]
        for name in ("host_scans", "host_joins", "host_forgets", "host_hellos"):
            getattr(lib, name).restype = ctypes.c_uint32
            getattr(lib, name).argtypes = [ctypes.c_void_p]
        for name in ("host_joined_name", "host_joined_password"):
            getattr(lib, name).restype = ctypes.c_uint8
            getattr(lib, name).argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.host_app.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.host_active.restype = ctypes.c_bool
        lib.host_active.argtypes = [ctypes.c_void_p, ctypes.c_uint8]
        lib.host_counter.restype = ctypes.c_uint32
        lib.host_counter.argtypes = [ctypes.c_void_p, ctypes.c_int]
        for name in ("host_fetches", "host_fetch_stops", "host_fetch_id", "host_allocated"):
            getattr(lib, name).restype = ctypes.c_uint32
            getattr(lib, name).argtypes = [ctypes.c_void_p]
        lib.host_fetching.restype = ctypes.c_bool
        lib.host_fetching.argtypes = [ctypes.c_void_p]
        for name in ("host_fetch_url", "host_fetch_agent"):
            getattr(lib, name).restype = ctypes.c_char_p
            getattr(lib, name).argtypes = [ctypes.c_void_p]
        lib.host_set_fetch_refused.argtypes = [ctypes.c_void_p, ctypes.c_bool]
        lib.host_set_alloc_most.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        lib.host_fetch_body.restype = ctypes.c_bool
        lib.host_fetch_body.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
                                        ctypes.c_size_t]
        lib.host_fetch_done.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_bool,
                                        ctypes.c_char_p]
        lib.host_to_ascii.restype = ctypes.c_int
        lib.host_to_ascii.argtypes = [ctypes.c_uint32, ctypes.c_char_p]
        lib.host_vgm_to_jbs.restype = ctypes.c_size_t
        lib.host_vgm_to_jbs.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p,
                                        ctypes.c_char_p, ctypes.c_size_t]
        lib.host_wiki_url.restype = ctypes.c_size_t
        lib.host_wiki_url.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p,
                                      ctypes.c_size_t]
        lib.host_wrap_new.restype = ctypes.c_void_p
        lib.host_wrap_new.argtypes = [ctypes.c_uint8]
        lib.host_wrap_free.argtypes = [ctypes.c_void_p]
        for name in ("host_wrap_title", "host_wrap_put"):
            getattr(lib, name).argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        lib.host_wrap_close.argtypes = [ctypes.c_void_p]
        for name in ("host_wrap_count", "host_wrap_held"):
            getattr(lib, name).restype = ctypes.c_size_t
            getattr(lib, name).argtypes = [ctypes.c_void_p]
        lib.host_wrap_lines.restype = ctypes.c_void_p
        lib.host_wrap_lines.argtypes = [ctypes.c_void_p]
        lib.host_extract_new.restype = ctypes.c_void_p
        lib.host_extract_free.argtypes = [ctypes.c_void_p]
        lib.host_extract_feed.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        lib.host_extract_titles.restype = ctypes.c_int
        lib.host_extract_titles.argtypes = [ctypes.c_void_p]
        lib.host_extract_title.restype = ctypes.c_size_t
        lib.host_extract_title.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.host_extract_text_len.restype = ctypes.c_size_t
        lib.host_extract_text_len.argtypes = [ctypes.c_void_p]
        lib.host_extract_text.restype = ctypes.c_void_p
        lib.host_extract_text.argtypes = [ctypes.c_void_p]
        for name in ("host_extract_found", "host_extract_done"):
            getattr(lib, name).restype = ctypes.c_bool
            getattr(lib, name).argtypes = [ctypes.c_void_p]
        lib.host_tick.restype = ctypes.c_bool
        lib.host_tick.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        lib.host_set_line.argtypes = [ctypes.c_void_p, _RATE, _WRITE, _IDLE]
        lib.host_track_add.restype = ctypes.c_bool
        lib.host_track_add.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        lib.host_track_cut.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_size_t]
        lib.host_juke_set.argtypes = [ctypes.c_void_p, ctypes.c_uint8, ctypes.c_bool]
        for name in ("host_track_reads", "host_juke_resent", "host_juke_underruns",
                     "host_tuner_held", "host_tuner_dropped", "host_tuner_dry",
                     "host_tuner_page"):
            getattr(lib, name).restype = ctypes.c_uint32
            getattr(lib, name).argtypes = [ctypes.c_void_p]
        lib.host_tuner_turn.restype = None
        lib.host_tuner_turn.argtypes = [ctypes.c_void_p]
        lib.host_watched.restype = ctypes.c_char_p
        lib.host_watched.argtypes = [ctypes.c_void_p]
        lib.host_shown.restype = ctypes.c_char_p
        lib.host_shown.argtypes = [ctypes.c_void_p, ctypes.c_uint8]
        lib.host_juke_index.restype = ctypes.c_uint16
        lib.host_juke_index.argtypes = [ctypes.c_void_p]
        lib.host_raw_state.restype = ctypes.c_uint8
        lib.host_raw_state.argtypes = [ctypes.c_void_p]
        for name in ("host_conn", "host_peer_lobby"):
            getattr(lib, name).restype = ctypes.c_uint8
            getattr(lib, name).argtypes = [ctypes.c_void_p]
        lib.host_conn_port.restype = ctypes.c_uint16
        lib.host_conn_port.argtypes = [ctypes.c_void_p]
        lib.host_conn_target.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.host_conn_set.argtypes = [ctypes.c_void_p, ctypes.c_uint8]
        lib.host_conn_refuse.argtypes = [ctypes.c_void_p, ctypes.c_bool]
        lib.host_conn_room.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        for name in ("host_listens", "host_calls", "host_closes", "host_keeps",
                     "host_peer_requests", "host_peer_repeats"):
            getattr(lib, name).restype = ctypes.c_uint32
            getattr(lib, name).argtypes = [ctypes.c_void_p]
        for name in ("host_meets", "host_punches"):
            getattr(lib, name).restype = ctypes.c_uint32
            getattr(lib, name).argtypes = [ctypes.c_void_p]
        lib.host_set_candidates.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint8]
        lib.host_punch.restype = ctypes.c_uint8
        lib.host_punch.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                   ctypes.POINTER(ctypes.c_bool), ctypes.POINTER(ctypes.c_uint32)]
        lib.host_set_rendezvous.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.host_conn_take.restype = ctypes.c_size_t
        lib.host_conn_take.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        lib.host_conn_give.restype = ctypes.c_size_t
        lib.host_conn_give.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        lib.host_set_last.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.host_conn_rtt.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        lib.host_conn_took.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
        lib.host_arq_rtt_count.restype = ctypes.c_uint32
        lib.host_arq_rtt_count.argtypes = [ctypes.c_void_p]
        lib.host_notes.restype = ctypes.c_uint32
        lib.host_notes.argtypes = [ctypes.c_void_p]
        lib.host_note_take.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.host_note_give.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.host_arq_new.restype = ctypes.c_void_p
        lib.host_arq_new.argtypes = [ctypes.c_uint32]
        lib.host_arq_free.argtypes = [ctypes.c_void_p]
        lib.host_arq_write.restype = ctypes.c_size_t
        lib.host_arq_write.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        lib.host_arq_read.restype = ctypes.c_size_t
        lib.host_arq_read.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        lib.host_arq_due.restype = ctypes.c_bool
        lib.host_arq_due.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        lib.host_arq_packet.restype = ctypes.c_size_t
        lib.host_arq_packet.argtypes = [ctypes.c_void_p, ctypes.c_uint8, ctypes.c_uint32,
                                        ctypes.c_char_p]
        lib.host_arq_take.restype = ctypes.c_int
        lib.host_arq_take.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
                                      ctypes.c_size_t]
        for name in ("host_arq_rtt", "host_arq_rtt_last", "host_arq_rtt_least"):
            getattr(lib, name).restype = ctypes.c_uint32
            getattr(lib, name).argtypes = [ctypes.c_void_p]
        lib.host_arq_last_at.restype = ctypes.c_uint32
        lib.host_arq_last_at.argtypes = [ctypes.c_void_p]
        lib.host_arq_unsaid.restype = ctypes.c_uint8
        lib.host_arq_unsaid.argtypes = [ctypes.c_void_p]
        lib.host_arq_note.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.host_arq_noted.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.nesp_stun_request.restype = ctypes.c_size_t
        lib.nesp_stun_request.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        lib.nesp_stun_mapped.restype = ctypes.c_bool
        lib.nesp_stun_mapped.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p,
                                         ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint16)]
        lib.host_set_airport.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int32,
                                         ctypes.c_int32]
        lib.host_airport.restype = ctypes.c_bool
        lib.host_airport.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                     ctypes.POINTER(ctypes.c_int32)]
        lib.host_airport_keeps.restype = ctypes.c_uint32
        lib.host_airport_keeps.argtypes = [ctypes.c_void_p]
        lib.host_set_zip.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int32,
                                     ctypes.c_int32, ctypes.c_char_p]
        lib.host_zip.restype = ctypes.c_bool
        lib.host_zip.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                 ctypes.POINTER(ctypes.c_int32), ctypes.c_char_p]
        lib.host_zip_keeps.restype = ctypes.c_uint32
        lib.host_zip_keeps.argtypes = [ctypes.c_void_p]
        lib.host_set_favorites.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint8]
        lib.host_favorites.restype = ctypes.c_int
        lib.host_favorites.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.host_favorites_keeps.restype = ctypes.c_uint32
        lib.host_favorites_keeps.argtypes = [ctypes.c_void_p]
        lib.host_last.restype = ctypes.c_bool
        lib.host_last.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.host_checks.argtypes = [ctypes.c_char_p, ctypes.c_size_t, _u8p]
        lib.host_pattern.argtypes = [ctypes.c_uint16, _u8p, ctypes.c_size_t]
        _lib = lib
    return _lib


def crc16(data):
    """CRC-16/CCITT-FALSE, a bit at a time: Python's own, so that the tests
    hold the firmware's and the console's to something."""
    crc = proto.NESP_CRC_INIT
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ proto.NESP_CRC_POLY) if crc & 0x8000 else crc << 1
        crc &= 0xFFFF
    return crc


def checks(data):
    """The two check bytes of a frame's bytes after its marker: their CRC,
    high byte first."""
    crc = crc16(data)
    return bytes((crc >> 8, crc & 0xFF))


def frame(svc, op, seq, payload=b""):
    """A request as the console sends it."""
    body = bytes((svc, op, seq, len(payload))) + bytes(payload)
    return bytes((proto.NESP_REQUEST_MARKER,)) + body + checks(body)


def reply_frame(svc, status, seq, payload=b""):
    """A reply as the Stick sends it."""
    body = bytes((svc, status, seq, len(payload))) + bytes(payload)
    return bytes((proto.NESP_REPLY_MARKER,)) + body + checks(body)


def short_frame(count, data=b""):
    """A short request as the console sends it: two bytes of data if its
    count is under 2, and three if not."""
    length = 2 if count < 2 else 3
    body = bytes((proto.NESP_SHORT_REQUEST | count,)) + bytes(data)[:length].ljust(length, b"\0")
    return body + checks(body)


def parse_short(data, request):
    """A short reply's bytes as (count, its data). Its CRC begins with the
    first byte of data of the request it answers. Raises if they are not
    one whole good one."""
    data = bytes(data)
    if (len(data) not in (4, 5) or data[0] & proto.NESP_SHORT_MARK != proto.NESP_SHORT_REPLY
            or checks(request[1:2] + data[:-2]) != data[-2:]):
        raise ValueError("not a short reply: %r" % data)
    return data[0] & ~proto.NESP_SHORT_MARK & 0xFF, data[1:-2]


class Reply:
    def __init__(self, svc, status, seq, payload):
        self.svc = svc
        self.status = status & ~proto.NESP_ST_ATTENTION
        self.attention = bool(status & proto.NESP_ST_ATTENTION)
        self.seq = seq
        self.payload = payload

    @property
    def ok(self):
        return self.status == proto.NESP_ST_OK

    def __repr__(self):
        return "Reply(svc=%d, status=0x%02X, seq=%d, payload=%r)" % (
            self.svc, self.status, self.seq, self.payload)


def parse(data):
    """A reply's bytes as a Reply. Raises if they are not one whole good
    frame."""
    data = bytes(data)
    if len(data) < proto.NESP_OVERHEAD or data[0] != proto.NESP_REPLY_MARKER:
        raise ValueError("not a reply: %r" % data)
    length = data[4]
    if len(data) != proto.NESP_OVERHEAD + length:
        raise ValueError("a reply of the wrong length: %r" % data)
    if checks(data[1:-2]) != data[-2:]:
        raise ValueError("a reply with bad check bytes: %r" % data)
    return Reply(data[1], data[2], data[3], data[5:5 + length])


# How a nesp32's connection to another stands (nesp_services.h's NESP_CONN_*).
(CONN_NONE, CONN_LISTENING, CONN_CALLING, CONN_ANSWERED, CONN_CALLED, CONN_FAILED,
 CONN_LOST, CONN_MEETING, CONN_MET) = range(9)
CONN_UP = (CONN_ANSWERED, CONN_CALLED)


class Line:
    """The line with framing off, for a nesp32 that has none: it keeps what
    a run of RAW's did with it.

        period      the UART's rate now, in CPU cycles a bit
        rates       every rate it was set to, in order
        sent        the bytes written, as they were
        room        if not None, the most the UART takes at one write
        busy        True: not everything written has left yet
    """

    def __init__(self):
        self.period = proto.NESP_PERIOD
        self.rates = []
        self.sent = bytearray()
        self.room = None
        self.busy = False

    def line_rate(self, period):
        self.period = period
        self.rates.append(period)

    def line_write(self, data):
        count = len(data) if self.room is None else min(len(data), self.room)
        self.sent += data[:count]
        return count

    def line_idle(self):
        return not self.busy


class Stick:
    """port, if given, has read() and write(). It may also be the line with
    framing off (line_rate, line_write, line_idle, as Line has them) and a
    clock (now_ms); without those the nesp32 has a Line of its own, `line`,
    and tick() is the caller's to call."""

    def __init__(self, port=None):
        self.port = port
        self._lib = library()
        self._host = ctypes.c_void_p(self._lib.host_new())
        self._out = (ctypes.c_uint8 * proto.NESP_FRAME_MAX)()
        self._seq = 0
        self.line = port if hasattr(port, "line_rate") else Line()
        line = self.line
        # Kept, or ctypes lets go of them while the library still calls.
        self._line = (_RATE(lambda period: line.line_rate(period)),
                      _WRITE(lambda data, count: line.line_write(bytes(data[:count]))),
                      _IDLE(lambda: line.line_idle()))
        self._lib.host_set_line(self._host, *self._line)

    def __del__(self):
        if getattr(self, "_host", None):
            # Its services are stopped as it goes, and one of them may give
            # the line back: not to a port that is itself being let go of.
            self._lib.host_set_line(self._host, _RATE(), _WRITE(), _IDLE())
            self._lib.host_free(self._host)
            self._host = None

    # --- the link ---------------------------------------------------------------

    def feed(self, data):
        """Bytes from the console. Returns the reply's bytes, b"" for none."""
        data = bytes(data)
        count = self._lib.host_feed(self._host, data, len(data), self._out)
        return bytes(self._out[:count])

    def poll(self):
        """Answer the console if it has asked, and let the services do what
        they do between requests, if the port has a clock. True if a reply
        went out."""
        heard = self.port.read()
        reply = self.feed(heard) if heard else b""
        if reply:
            self.port.write(reply)
        if hasattr(self.port, "now_ms"):
            self.tick(self.port.now_ms())
        return bool(reply)

    def tick(self, now_ms):
        """What the services do by the clock. True if they want another
        within a couple of milliseconds."""
        return self._lib.host_tick(self._host, int(now_ms) & 0xFFFFFFFF)

    def ask(self, svc, op, payload=b"", seq=None):
        """One request, as a console with no line would make it. Returns the
        Reply."""
        if seq is None:
            self._seq = (self._seq + 1) & 0xFF
            seq = self._seq
        return parse(self.feed(frame(svc, op, seq, payload)))

    def quick(self, count, data=b""):
        """One short request. Returns the reply's (count, data), or None if
        there was no reply."""
        request = short_frame(count, data)
        reply = self.feed(request)
        return parse_short(reply, request) if reply else None

    def hello(self, app=b"TEST", version=1, reply_max=proto.NESP_PAYLOAD_MAX, services=()):
        payload = bytes((proto.NESP_PROTOCOL,)) + app + bytes((version, reply_max))
        return self.ask(proto.NESP_SVC_SYS, proto.NESP_SYS_HELLO, payload + bytes(services))

    def event(self, code, arg=0):
        self._lib.host_event(self._host, code, arg)

    def note_turnaround(self, microseconds):
        self._lib.host_note_turnaround(self._host, microseconds)

    # --- the stand-in hardware ---------------------------------------------------

    def set_wifi(self, state, why=proto.NESP_WHY_NONE, rssi=0, address=(0, 0, 0, 0)):
        self._lib.host_set_wifi(self._host, state, why, rssi, bytes(address))

    def set_saved(self, name):
        self._lib.host_set_saved(self._host, name, len(name))

    def set_battery(self, percent):
        self._lib.host_set_battery(self._host, percent)

    def set_drive(self, state):
        """How the nesp32's files stand as a USB drive (NESP_DRIVE_*), as a
        computer taking it or letting it go would make it."""
        self._lib.host_set_drive(self._host, state)

    @property
    def drive(self):
        return self._lib.host_drive(self._host)

    @property
    def drive_stops(self):
        return self._lib.host_drive_stops(self._host)

    def set_screen(self, state):
        """Which way up the nesp32's screen is (NESP_SCREEN_*); NONE for a
        firmware that cannot turn it."""
        self._lib.host_set_screen(self._host, state)

    @property
    def screen(self):
        return self._lib.host_screen(self._host)

    def set_time(self, seconds):
        self._lib.host_set_time(self._host, seconds is not None, seconds or 0)

    def scan_set(self, networks):
        """What a scan finds: (name, rssi, auth) or (name, rssi, auth,
        channel) each."""
        self._lib.host_scan_clear(self._host)
        for network in networks:
            name, rssi, auth = network[:3]
            channel = network[3] if len(network) > 3 else 1
            if not self._lib.host_scan_add(self._host, name, len(name), rssi, auth, channel):
                raise ValueError("too many networks, or a name too long")

    def scan_finish(self, state=proto.NESP_SCAN_DONE):
        self._lib.host_scan_finish(self._host, state)

    def add_track(self, data):
        """A file among the nesp32's tracks, after those already there. A
        service finds it at its next hello."""
        data = bytes(data)
        if not self._lib.host_track_add(self._host, data, len(data)):
            raise ValueError("too many tracks")

    def cut_track(self, index, length):
        """A track's file has gone bad: it reads as only this long."""
        self._lib.host_track_cut(self._host, index, length)

    def set_juke(self, loops=2, repeat=True):
        self._lib.host_juke_set(self._host, loops, repeat)

    # --- the connection to another nesp32: the caller is the network ----------------

    @property
    def conn(self):
        """How the connection stands: one of CONN_*."""
        return self._lib.host_conn(self._host)

    @conn.setter
    def conn(self, state):
        self._lib.host_conn_set(self._host, state)

    @property
    def conn_target(self):
        """The address the nesp32 last called."""
        buffer = ctypes.create_string_buffer(4)
        self._lib.host_conn_target(self._host, buffer)
        return buffer.raw

    @property
    def conn_port(self):
        return self._lib.host_conn_port(self._host)

    def conn_take(self):
        """What the nesp32 has sent to the other since the last call."""
        buffer = ctypes.create_string_buffer(256)
        count = self._lib.host_conn_take(self._host, buffer, len(buffer))
        return buffer.raw[:count]

    def conn_give(self, data):
        """Bytes from the other nesp32. Returns how many there was room for."""
        data = bytes(data)
        return self._lib.host_conn_give(self._host, data, len(data))

    @property
    def rtt(self):
        raise AttributeError("the network's time is the caller's to set")

    @rtt.setter
    def rtt(self, microseconds):
        """How long the network takes there and back; 0 for not known."""
        self._lib.host_conn_rtt(self._host, int(microseconds))

    def took(self, microseconds, times=1):
        """A measurement of the network's time there and back, or several
        alike."""
        self._lib.host_conn_took(self._host, int(microseconds), times)

    @property
    def notes(self):
        """How many notes the service has left for the other nesp32."""
        return self._lib.host_notes(self._host)

    def note_take(self):
        """The latest of them."""
        buffer = ctypes.create_string_buffer(proto_note())
        self._lib.host_note_take(self._host, buffer)
        return buffer.raw

    def note_give(self, note):
        """The other nesp32's latest note."""
        self._lib.host_note_give(self._host, bytes(note))

    def refuse_conns(self, refused=True):
        self._lib.host_conn_refuse(self._host, refused)

    def conn_room(self, size):
        """The most the connection takes at one send; 0 for any."""
        self._lib.host_conn_room(self._host, size)

    @property
    def last(self):
        """The address the nesp32 keeps as the last it joined, or None."""
        buffer = ctypes.create_string_buffer(4)
        return buffer.raw if self._lib.host_last(self._host, buffer) else None

    @last.setter
    def last(self, address):
        self._lib.host_set_last(self._host, None if address is None else bytes(address))

    @property
    def airport(self):
        """The airport the nesp32 keeps over power-off: (its letters, its
        latitude, its longitude), the two in millionths of a degree. None
        if it keeps none."""
        code = ctypes.create_string_buffer(4)
        place = (ctypes.c_int32 * 2)()
        if not self._lib.host_airport(self._host, code, place):
            return None
        return code.raw, place[0], place[1]

    @airport.setter
    def airport(self, kept):
        if kept is None:
            self._lib.host_set_airport(self._host, None, 0, 0)
        else:
            self._lib.host_set_airport(self._host, bytes(kept[0]), kept[1], kept[2])

    @property
    def airport_keeps(self):
        return self._lib.host_airport_keeps(self._host)

    @property
    def zip(self):
        """The zip code the nesp32 keeps over power-off: (its digits, its
        latitude, its longitude, its place's name), the two in millionths
        of a degree and the name with no spaces after it. None if it keeps
        none."""
        digits = ctypes.create_string_buffer(proto.NESP_WEATHER_ZIP_LEN)
        place = (ctypes.c_int32 * 2)()
        name = ctypes.create_string_buffer(proto.NESP_WEATHER_PLACE_MAX)
        if not self._lib.host_zip(self._host, digits, place, name):
            return None
        return digits.raw, place[0], place[1], name.raw.rstrip(b" ")

    @zip.setter
    def zip(self, kept):
        if kept is None:
            self._lib.host_set_zip(self._host, None, 0, 0, None)
        else:
            self._lib.host_set_zip(self._host, bytes(kept[0]), kept[1], kept[2],
                                   bytes(kept[3]).ljust(proto.NESP_WEATHER_PLACE_MAX))

    @property
    def zip_keeps(self):
        return self._lib.host_zip_keeps(self._host)

    @property
    def favorites(self):
        """BSKY's favorites as the nesp32 keeps them over power-off: a list
        of handles, or None if it keeps none."""
        size = proto.NESP_BSKY_HANDLE_MAX
        handles = ctypes.create_string_buffer(proto.NESP_BSKY_FAVORITES * size)
        count = self._lib.host_favorites(self._host, handles)
        if count < 0:
            return None
        return [handles.raw[index * size:(index + 1) * size].rstrip(b"\0")
                for index in range(count)]

    @favorites.setter
    def favorites(self, kept):
        if kept is None:
            self._lib.host_set_favorites(self._host, None, 0)
        else:
            size = proto.NESP_BSKY_HANDLE_MAX
            self._lib.host_set_favorites(
                self._host, b"".join(bytes(handle).ljust(size, b"\0") for handle in kept),
                len(kept))

    @property
    def favorites_keeps(self):
        return self._lib.host_favorites_keeps(self._host)

    @property
    def listens(self):
        return self._lib.host_listens(self._host)

    @property
    def calls(self):
        return self._lib.host_calls(self._host)

    @property
    def closes(self):
        return self._lib.host_closes(self._host)

    @property
    def keeps(self):
        return self._lib.host_keeps(self._host)

    @property
    def meets(self):
        return self._lib.host_meets(self._host)

    @property
    def punches(self):
        return self._lib.host_punches(self._host)

    @property
    def candidates(self):
        raise AttributeError("the nesp32's addresses are set, not read")

    @candidates.setter
    def candidates(self, pairs):
        """The addresses the meeting's socket has: (4-byte address, port)
        each, its own on its network first."""
        data = b"".join(bytes(address) + port.to_bytes(2, "big") for address, port in pairs)
        self._lib.host_set_candidates(self._host, data, len(pairs))

    @property
    def punch(self):
        """What the nesp32 was told of the other at the rendezvous:
        (listen, session, [(address, port), ...])."""
        buffer = ctypes.create_string_buffer(6 * 4)
        listen = ctypes.c_bool()
        session = ctypes.c_uint32()
        count = self._lib.host_punch(self._host, buffer, ctypes.byref(listen),
                                     ctypes.byref(session))
        raw = buffer.raw
        return listen.value, session.value, [
            (raw[6 * index:6 * index + 4], int.from_bytes(raw[6 * index + 4:6 * index + 6], "big"))
            for index in range(count)]

    def set_rendezvous(self, url):
        self._url = url.encode()
        self._lib.host_set_rendezvous(self._host, self._url)

    @property
    def peer_requests(self):
        """PEER: TICKS requests in this session, and how many of them
        brought nothing new."""
        return self._lib.host_peer_requests(self._host)

    @property
    def peer_repeats(self):
        return self._lib.host_peer_repeats(self._host)

    @property
    def lobby(self):
        return self._lib.host_peer_lobby(self._host)

    # --- what happened -------------------------------------------------------------

    @property
    def track_reads(self):
        return self._lib.host_track_reads(self._host)

    def shown(self, row):
        """A line of the nesp32's screen that the application wrote."""
        return self._lib.host_shown(self._host, row).decode("ascii")

    @property
    def juke_index(self):
        return self._lib.host_juke_index(self._host)

    @property
    def juke_resent(self):
        return self._lib.host_juke_resent(self._host)

    @property
    def juke_underruns(self):
        return self._lib.host_juke_underruns(self._host)

    @property
    def raw_state(self):
        return self._lib.host_raw_state(self._host)

    @property
    def tuner_held(self):
        """Samples of the station held for the console."""
        return self._lib.host_tuner_held(self._host)

    @property
    def tuner_dropped(self):
        return self._lib.host_tuner_dropped(self._host)

    @property
    def tuner_dry(self):
        return self._lib.host_tuner_dry(self._host)

    @property
    def watched(self):
        """The last line a service gave for the nesp32's log."""
        return self._lib.host_watched(self._host).decode("ascii")

    @property
    def tuner_page(self):
        """The headline that is on the console's screen, or going there."""
        return self._lib.host_tuner_page(self._host)

    def tuner_turn(self):
        """Have the station send its next page of headlines now."""
        self._lib.host_tuner_turn(self._host)

    @property
    def scan_state(self):
        return self._lib.host_scan_state(self._host)

    @property
    def wifi_state(self):
        return self._lib.host_wifi_state(self._host)

    @property
    def scans(self):
        return self._lib.host_scans(self._host)

    @property
    def joins(self):
        return self._lib.host_joins(self._host)

    @property
    def forgets(self):
        return self._lib.host_forgets(self._host)

    @property
    def hellos(self):
        return self._lib.host_hellos(self._host)

    @property
    def joined_name(self):
        buffer = ctypes.create_string_buffer(proto.NESP_NAME_MAX)
        length = self._lib.host_joined_name(self._host, buffer)
        return buffer.raw[:length]

    @property
    def joined_password(self):
        buffer = ctypes.create_string_buffer(proto.NESP_PASSWORD_MAX)
        length = self._lib.host_joined_password(self._host, buffer)
        return buffer.raw[:length]

    @property
    def app(self):
        buffer = ctypes.create_string_buffer(proto.NESP_APP_ID)
        self._lib.host_app(self._host, buffer)
        return buffer.raw, self._lib.host_app_version(self._host)

    def active(self, service):
        return self._lib.host_active(self._host, service)

    # --- fetches: the caller is the Internet ----------------------------------------

    @property
    def fetches(self):
        return self._lib.host_fetches(self._host)

    @property
    def fetch_stops(self):
        return self._lib.host_fetch_stops(self._host)

    @property
    def fetch_id(self):
        """The id of the last fetch asked for."""
        return self._lib.host_fetch_id(self._host)

    @property
    def fetching(self):
        return self._lib.host_fetching(self._host)

    @property
    def fetch_url(self):
        return self._lib.host_fetch_url(self._host).decode("ascii")

    @property
    def fetch_agent(self):
        return self._lib.host_fetch_agent(self._host).decode("ascii")

    @property
    def allocated(self):
        """Big blocks of memory the services hold."""
        return self._lib.host_allocated(self._host)

    def refuse_fetches(self, refused=True):
        self._lib.host_set_fetch_refused(self._host, refused)

    def alloc_most(self, size):
        """The most memory a service can have in one piece; 0 for any."""
        self._lib.host_set_alloc_most(self._host, size)

    def fetch_body(self, data, fetch=None):
        """More of a fetch's reply: the last fetch's, or the one with this
        id. Returns whether more is wanted."""
        data = bytes(data)
        return self._lib.host_fetch_body(self._host, self.fetch_id if fetch is None else fetch,
                                         data, len(data))

    def fetch_done(self, ok=True, why=b"", fetch=None):
        self._lib.host_fetch_done(self._host, self.fetch_id if fetch is None else fetch,
                                  ok, why)

    @property
    def requests(self):
        return self._lib.host_counter(self._host, 0)

    @property
    def repeats(self):
        return self._lib.host_counter(self._host, 1)

    @property
    def dropped(self):
        return self._lib.host_counter(self._host, 2)

    @property
    def noise(self):
        return self._lib.host_counter(self._host, 3)


ARQ_NOTE = 4
ARQ_PACKET = 56
ARQ_CALL, ARQ_ANSWER, ARQ_DATA, ARQ_BYE = range(4)


def proto_note():
    return ARQ_NOTE


class Arq:
    """One end of a stream over datagrams (the firmware's arq.c), with no
    socket: the test is the network. Times are microseconds."""

    def __init__(self, session=0x1234ABCD):
        self._lib = library()
        self._arq = self._lib.host_arq_new(session)

    def __del__(self):
        if getattr(self, "_arq", None):
            self._lib.host_arq_free(self._arq)
            self._arq = None

    def write(self, data):
        data = bytes(data)
        return self._lib.host_arq_write(self._arq, data, len(data))

    def read(self, most=256):
        buffer = ctypes.create_string_buffer(most)
        count = self._lib.host_arq_read(self._arq, buffer, most)
        return buffer.raw[:count]

    def due(self, now):
        return self._lib.host_arq_due(self._arq, now & 0xFFFFFFFF)

    def packet(self, now, kind=ARQ_DATA):
        buffer = ctypes.create_string_buffer(ARQ_PACKET)
        count = self._lib.host_arq_packet(self._arq, kind, now & 0xFFFFFFFF, buffer)
        return buffer.raw[:count]

    def take(self, now, data):
        data = bytes(data)
        return self._lib.host_arq_take(self._arq, now & 0xFFFFFFFF, data, len(data))

    @property
    def rtt(self):
        return self._lib.host_arq_rtt(self._arq)

    @property
    def rtt_last(self):
        return self._lib.host_arq_rtt_last(self._arq)

    @property
    def rtt_least(self):
        return self._lib.host_arq_rtt_least(self._arq)

    @property
    def rtt_count(self):
        """How many times the network's time has been measured."""
        return self._lib.host_arq_rtt_count(self._arq)

    @property
    def heard_at(self):
        """When anything of the other end last came."""
        return self._lib.host_arq_last_at(self._arq)

    @property
    def unsaid(self):
        """Bytes written that the other end has not said it has."""
        return self._lib.host_arq_unsaid(self._arq)

    def note(self, note):
        self._lib.host_arq_note(self._arq, bytes(note))

    @property
    def noted(self):
        buffer = ctypes.create_string_buffer(ARQ_NOTE)
        self._lib.host_arq_noted(self._arq, buffer)
        return buffer.raw


STUN_ID = 12
STUN_REQUEST = 20


def stun_request(ident):
    """A STUN Binding Request with this 12-byte id (the firmware's stun.c)."""
    buffer = ctypes.create_string_buffer(STUN_REQUEST)
    count = library().nesp_stun_request(bytes(ident), buffer)
    return buffer.raw[:count]


def stun_mapped(data, ident):
    """The (address, port) a STUN answer to the request with this id gives,
    the address as 4 bytes, or None if it is not one."""
    data = bytes(data)
    address = ctypes.create_string_buffer(4)
    port = ctypes.c_uint16()
    if not library().nesp_stun_mapped(data, len(data), bytes(ident), address,
                                      ctypes.byref(port)):
        return None
    return address.raw, port.value


def c_checks(data):
    """The firmware's check bytes for these bytes."""
    out = (ctypes.c_uint8 * 2)()
    library().host_checks(bytes(data), len(data), out)
    return bytes(out)


def pattern(seed, count):
    """The test pattern, from the firmware's code."""
    out = (ctypes.c_uint8 * count)()
    library().host_pattern(seed, out, count)
    return bytes(out)


# --- the text code, without a Stick round it ----------------------------------------

HEADING = 0x80                  # set on every character of a heading line


def to_ascii(code):
    """A Unicode character as ASCII bytes, maybe none; None if there is
    nothing like it."""
    out = ctypes.create_string_buffer(4)
    count = library().host_to_ascii(code, out)
    return None if count < 0 else out.raw[:count]


def vgm_to_jbs(data, name=None, room=1 << 20):
    """The .jbs file the firmware makes of an uncompressed .vgm, or None if
    it makes none. name is the title of a rip that has none of its own."""
    out = ctypes.create_string_buffer(room)
    name = name.encode("utf-8") if isinstance(name, str) else name
    length = library().host_vgm_to_jbs(bytes(data), len(data), name, out, room)
    return out.raw[:length] if length else None


def wiki_url(query):
    """The address a search is fetched from."""
    query = query.encode("utf-8") if isinstance(query, str) else bytes(query)
    out = ctypes.create_string_buffer(512)
    length = library().host_wiki_url(query, len(query), out, len(out))
    return out.raw[:length].decode("ascii")


class Wrap:
    """The firmware's wrapper: plain text in, lines of `width` out."""

    def __init__(self, width=proto.NESP_WIKI_COLUMNS):
        self.width = width
        self._lib = library()
        self._wrap = ctypes.c_void_p(self._lib.host_wrap_new(width))

    def __del__(self):
        if getattr(self, "_wrap", None):
            self._lib.host_wrap_free(self._wrap)
            self._wrap = None

    def title(self, text):
        self._lib.host_wrap_title(self._wrap, bytes(text), len(text))

    def put(self, data):
        self._lib.host_wrap_put(self._wrap, bytes(data), len(data))

    def close(self):
        self._lib.host_wrap_close(self._wrap)

    @property
    def held(self):
        """Bytes of a paragraph waiting for its end."""
        return self._lib.host_wrap_held(self._wrap)

    @property
    def lines(self):
        """The lines laid out so far, each `width` bytes: tile numbers."""
        count = self._lib.host_wrap_count(self._wrap)
        if not count:
            return []
        data = ctypes.string_at(self._lib.host_wrap_lines(self._wrap), count * self.width)
        return [data[start:start + self.width] for start in range(0, len(data), self.width)]


def text_of(line):
    """A line's (text, is a heading), having checked that it is all one or
    all the other."""
    heading = bool(line[0] & HEADING) if line.strip() else False
    text = bytes(char & 0x7F for char in line).rstrip()
    if any(bool(char & HEADING) != heading for char in line[:len(text)]):
        raise AssertionError("a line that is part heading: %r" % line)
    return text, heading


class Extract:
    """The firmware's extractor: an API reply in, title and text out."""

    def __init__(self):
        self._lib = library()
        self._extract = ctypes.c_void_p(self._lib.host_extract_new())

    def __del__(self):
        if getattr(self, "_extract", None):
            self._lib.host_extract_free(self._extract)
            self._extract = None

    def feed(self, data):
        self._lib.host_extract_feed(self._extract, bytes(data), len(data))

    @property
    def title(self):
        """The page's title, or None if none has been seen."""
        count = self._lib.host_extract_titles(self._extract)
        if count > 1:
            raise AssertionError("the title was given %d times" % count)
        if not count:
            return None
        out = ctypes.create_string_buffer(256)
        length = self._lib.host_extract_title(self._extract, out)
        return out.raw[:length]

    @property
    def text(self):
        length = self._lib.host_extract_text_len(self._extract)
        if not length:
            return b""
        return ctypes.string_at(self._lib.host_extract_text(self._extract), length)

    @property
    def found(self):
        return self._lib.host_extract_found(self._extract)

    @property
    def done(self):
        return self._lib.host_extract_done(self._extract)
