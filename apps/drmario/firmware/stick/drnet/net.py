"""Wi-Fi and the connection to the other Stick (MicroPython only).

SocketNetwork is the *network* drnet.stick asks for, on TCP: the Stick that
hosts listens on linkrate.PORT, and the one that joins connects to it. A
session is then one byte a tick each way (session.py), sent as it comes,
with Nagle's algorithm off.

Before either side calls the connection good, each sends HELLO and reads
the other's, so that something else that finds the port is not taken for a
console.

Connecting blocks, for CONNECT_S at most. The console's requests go
unanswered meanwhile, which its menu allows for: it asks again. Nothing
else here blocks, and nothing here makes garbage while it only waits:
reads go into a buffer kept for them, and a socket with nothing to give
returns None rather than raising.
"""

import socket
import time

import network

from drnet.linkrate import (
    PORT,
    STATE_CONNECTING,
    STATE_FAILED,
    STATE_GUEST,
    STATE_HOST,
    STATE_HOSTING,
    STATE_IDLE,
    STATE_NO_WIFI,
)

HELLO = b"DRM1"
CONNECT_S = 3
HELLO_S = 2
ACCEPT_MS = 50              # how often a hosting Stick looks for a caller
LAST_PATH = "/flash/drnet_last"

_wlan = None


def wlan():
    global _wlan
    if _wlan is None:
        _wlan = network.WLAN(network.STA_IF)
        _wlan.active(True)
        try:
            # Power saving holds received packets for the next beacon, up
            # to 100 ms: several frames of the other console's buttons.
            # The radio refuses (ESP_FAIL) while Bluetooth is on, which
            # needs the Wi-Fi to sleep between beacons; the game then
            # stalls more often, and still works.
            _wlan.config(pm=network.WLAN.PM_NONE)
        except (AttributeError, ValueError, TypeError, OSError) as error:
            print("Wi-Fi power saving not turned off:", error)
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


def own_address():
    """This Stick's IPv4 address as 4 bytes, or None off the network."""
    if not is_connected():
        return None
    try:
        return bytes(int(part) for part in _wlan.ifconfig()[0].split("."))
    except (ValueError, OSError):
        return None


def dotted(address):
    return ".".join(str(byte) for byte in address)


def _no_delay(sock):
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except (AttributeError, OSError) as error:
        print("TCP_NODELAY not set:", error)


class SocketPeer:
    """A connection to the other Stick, as session.py wants a peer."""

    def __init__(self, sock):
        self.sock = sock
        self.lost = False
        self._unsent = b""
        self._buffer = bytearray(64)
        self._view = memoryview(self._buffer)
        _no_delay(sock)
        sock.setblocking(False)

    def send(self, data):
        if self.lost:
            return
        data = self._unsent + bytes(data)
        try:
            written = self.sock.write(data)
        except OSError:
            self.lost = True
            return
        self._unsent = data[written or 0:]

    def recv(self):
        if self.lost:
            return b""
        if self._unsent:
            self.send(b"")
        try:
            count = self.sock.readinto(self._buffer)
        except OSError:
            self.lost = True
            return b""
        if count is None:
            return b""          # nothing has come
        if count == 0:
            self.lost = True    # the other end closed
            return b""
        return bytes(self._view[:count])

    def close(self):
        self.lost = True
        try:
            self.sock.close()
        except OSError:
            pass


def _greet(sock):
    """Exchange HELLO on a socket that still blocks. True if the other end
    is one of these."""
    sock.settimeout(HELLO_S)
    sock.write(HELLO)
    theirs = b""
    while len(theirs) < len(HELLO):
        more = sock.read(len(HELLO) - len(theirs))
        if not more:
            return False
        theirs += more
    return theirs == HELLO


class SocketNetwork:
    def __init__(self):
        self.state = STATE_NO_WIFI
        self.address = None
        self.target = None
        self.peer = None
        self.last = self._load_last()
        self._server = None
        self._accept_at = 0
        self._dial = False
        self.error = ""

    def _load_last(self):
        try:
            with open(LAST_PATH, "rb") as handle:
                data = handle.read()
        except OSError:
            return None
        return data if len(data) == 4 else None

    def _save_last(self, address):
        if address == self.last:
            return
        self.last = address
        try:
            with open(LAST_PATH, "wb") as handle:
                handle.write(address)
        except OSError as error:
            print("address not saved:", error)

    def refresh(self):
        """Look at the Wi-Fi again. Called now and then, not every poll."""
        self.address = own_address()
        if self.address is None:
            if self.state != STATE_NO_WIFI:
                self.close()
            self.state = STATE_NO_WIFI
        elif self.state == STATE_NO_WIFI:
            self.state = STATE_IDLE

    def listen(self):
        if self.address is None:
            return
        try:
            server = socket.socket()
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("0.0.0.0", PORT))
            server.listen(1)
            server.setblocking(False)
        except OSError as error:
            self.error = "listen: %s" % error
            self.state = STATE_FAILED
            return
        self._server = server
        self.state = STATE_HOSTING

    def connect(self, target):
        if self.address is None:
            return
        self.target = bytes(target)
        self.state = STATE_CONNECTING
        self._dial = True       # in the next poll: the reply to this goes first

    def close(self):
        if self.peer is not None:
            self.peer.close()
        self.peer = None
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
        self._server = None
        self._dial = False
        self.state = STATE_IDLE if self.address is not None else STATE_NO_WIFI

    def poll(self):
        if self._dial:
            self._dial = False
            self._connect()
        elif self._server is not None:
            now = time.ticks_ms()
            if time.ticks_diff(now, self._accept_at) >= ACCEPT_MS:
                self._accept_at = now
                self._accept()
        elif self.peer is not None and self.peer.lost and self.state in (STATE_HOST, STATE_GUEST):
            self.state = STATE_FAILED

    def _accept(self):
        try:
            sock, _ = self._server.accept()
        except OSError:
            return              # nobody yet
        try:
            good = _greet(sock)
        except OSError:
            good = False
        if not good:
            sock.close()
            return
        self._server.close()
        self._server = None
        self.peer = SocketPeer(sock)
        self.state = STATE_HOST

    def _connect(self):
        sock = socket.socket()
        try:
            sock.settimeout(CONNECT_S)
            sock.connect((dotted(self.target), PORT))
            good = _greet(sock)
        except OSError as error:
            self.error = "connect: %s" % error
            good = False
        if not good:
            sock.close()
            self.state = STATE_FAILED
            return
        self.peer = SocketPeer(sock)
        self.state = STATE_GUEST
        self._save_last(self.target)
