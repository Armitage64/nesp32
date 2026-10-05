"""Wi-Fi and the HTTPS request to Wikipedia (MicroPython only).

The way of it is nes-radar's (firmware/stick_s3/nesradar/net.py). The
request is HTTP/1.0 so the reply is never chunked, and it asks for no
compression, so the body can be read as it comes and handed straight to
wikitext.Extractor a piece at a time.

Certificate verification: MicroPython's ssl does not verify by default and
has no system trust store. If /flash/ca.der exists it is loaded and
verification is required; otherwise the connection is encrypted but the
server is not authenticated. What is fetched is public and only read, so
the unverified mode is the deliberate default.
"""

import socket
import ssl
import time

import network

from neswiki import wikitext

CA_PATH = "/flash/ca.der"
TIMEOUT_S = 15

_wlan = None


def wlan():
    global _wlan
    if _wlan is None:
        _wlan = network.WLAN(network.STA_IF)
        _wlan.active(True)
    return _wlan


def connect(ssid, password, timeout_ms=20000, on_wait=None):
    station = wlan()
    if station.isconnected():
        return True
    station.connect(ssid, password)
    started = time.ticks_ms()
    while not station.isconnected():
        if time.ticks_diff(time.ticks_ms(), started) >= timeout_ms:
            return False
        if on_wait is not None:
            on_wait()
        time.sleep_ms(100)
    return True


def is_connected():
    return _wlan is not None and _wlan.isconnected()


def _ssl_context():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        with open(CA_PATH, "rb") as handle:
            context.load_verify_locations(cadata=handle.read())
        context.verify_mode = ssl.CERT_REQUIRED
    except OSError:
        context.verify_mode = ssl.CERT_NONE
    return context


def open_search(query):
    """Ask Wikipedia for the article a search finds. Returns the stream,
    with the reply's headers read and its body next; the caller closes it.
    Raises OSError if the reply is not a 200."""
    if not is_connected():
        raise OSError("no Wi-Fi")
    host = wikitext.HOST
    address = socket.getaddrinfo(host, 443, 0, socket.SOCK_STREAM)[0][-1]
    raw = socket.socket()
    raw.settimeout(TIMEOUT_S)
    stream = None
    try:
        raw.connect(address)
        stream = _ssl_context().wrap_socket(raw, server_hostname=host)
        request = (
            "GET %s HTTP/1.0\r\n"
            "Host: %s\r\n"
            "User-Agent: %s\r\n"
            "Accept: application/json\r\n"
            "Accept-Encoding: identity\r\n"
            "Connection: close\r\n\r\n"
        ) % (wikitext.api_path(query), host, wikitext.USER_AGENT)
        stream.write(request.encode("ascii"))
        status = stream.readline().split(None, 2)
        if len(status) < 2 or status[1] != b"200":
            raise OSError("HTTP %s" % (status[1].decode() if len(status) > 1 else "?"))
        while True:
            line = stream.readline()
            if not line or line == b"\r\n":
                break
        return stream
    except Exception:
        (stream or raw).close()
        raise
