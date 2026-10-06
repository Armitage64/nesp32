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


class Stick:
    def __init__(self, port=None):
        self.port = port
        self._lib = library()
        self._host = ctypes.c_void_p(self._lib.host_new())
        self._out = (ctypes.c_uint8 * proto.NESP_FRAME_MAX)()
        self._seq = 0

    def __del__(self):
        if getattr(self, "_host", None):
            self._lib.host_free(self._host)
            self._host = None

    # --- the link ---------------------------------------------------------------

    def feed(self, data):
        """Bytes from the console. Returns the reply's bytes, b"" for none."""
        data = bytes(data)
        count = self._lib.host_feed(self._host, data, len(data), self._out)
        return bytes(self._out[:count])

    def poll(self):
        """Answer the console if it has asked. True if a reply went out."""
        heard = self.port.read()
        if not heard:
            return False
        reply = self.feed(heard)
        if not reply:
            return False
        self.port.write(reply)
        return True

    def ask(self, svc, op, payload=b"", seq=None):
        """One request, as a console with no line would make it. Returns the
        Reply."""
        if seq is None:
            self._seq = (self._seq + 1) & 0xFF
            seq = self._seq
        return parse(self.feed(frame(svc, op, seq, payload)))

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

    # --- what happened -------------------------------------------------------------

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
