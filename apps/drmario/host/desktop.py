"""The network and the stand-in opponent for a computer in place of a Stick.

DesktopNetwork is the *network* drnet.stick asks for, on ordinary sockets.
It is the Stick's own (firmware/stick/drnet/net.py) for CPython: the same
port, the same HELLO, so a computer and a Stick can be the two ends of a
session.

IdleNetwork needs no other console. Whatever is asked of it, it is
connected at once, to an opponent who never presses a button.
"""

import os
import socket
import time

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
ADDRESS_S = 2               # how often the computer's own address is looked at
LAST_PATH = os.path.expanduser("~/.drnet_last")


def own_address():
    """This computer's IPv4 address on its way out, as 4 bytes, or None.
    Nothing is sent: a UDP socket only has to pick a route."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        return socket.inet_aton(probe.getsockname()[0])
    except OSError:
        return None
    finally:
        probe.close()


def dotted(address):
    return ".".join(str(byte) for byte in address)


class SocketPeer:
    """A connection to the other end, as session.py wants a peer."""

    def __init__(self, sock):
        self.sock = sock
        self.lost = False
        self._unsent = b""
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setblocking(False)
        except OSError:
            self.lost = True    # it went away while HELLO was exchanged

    def send(self, data):
        if self.lost:
            return
        data = self._unsent + bytes(data)
        if not data:
            return
        try:
            written = self.sock.send(data)
        except BlockingIOError:
            written = 0
        except OSError:
            self.lost = True
            return
        self._unsent = data[written:]

    def recv(self):
        if self.lost:
            return b""
        if self._unsent:
            self.send(b"")
        try:
            data = self.sock.recv(64)
        except BlockingIOError:
            return b""          # nothing has come
        except OSError:
            self.lost = True
            return b""
        if not data:
            self.lost = True    # the other end closed
        return data

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
    sock.sendall(HELLO)
    theirs = b""
    while len(theirs) < len(HELLO):
        more = sock.recv(len(HELLO) - len(theirs))
        if not more:
            return False
        theirs += more
    return theirs == HELLO


class DesktopNetwork:
    def __init__(self, port=PORT, last_path=LAST_PATH):
        self.port = port
        self.last_path = last_path
        self.state = STATE_NO_WIFI
        self.address = None
        self.target = None
        self.peer = None
        self.error = ""
        self.last = self._load_last()
        self._server = None
        self._dial = False
        self._address_at = 0.0
        self.refresh()

    def _load_last(self):
        try:
            with open(self.last_path, "rb") as handle:
                data = handle.read()
        except OSError:
            return None
        return data if len(data) == 4 else None

    def _save_last(self, address):
        if address == self.last:
            return
        self.last = address
        try:
            with open(self.last_path, "wb") as handle:
                handle.write(address)
        except OSError as error:
            self.error = "address not saved: %s" % error

    def refresh(self):
        self._address_at = time.monotonic()
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
            server.bind(("0.0.0.0", self.port))
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
            self._server.close()
        self._server = None
        self._dial = False
        self.state = STATE_IDLE if self.address is not None else STATE_NO_WIFI

    def poll(self):
        if self._dial:
            self._dial = False
            self._connect()
        elif self._server is not None:
            self._accept()
        elif self.peer is not None:
            if self.peer.lost and self.state in (STATE_HOST, STATE_GUEST):
                self.state = STATE_FAILED
        elif time.monotonic() - self._address_at >= ADDRESS_S:
            self.refresh()

    def _accept(self):
        try:
            sock, _ = self._server.accept()
        except BlockingIOError:
            return              # nobody yet
        except OSError as error:
            self.error = "accept: %s" % error
            return
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
            sock.connect((dotted(self.target), self.port))
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


class IdlePeer:
    """An opponent who never presses a button: a tick of no buttons back
    for every tick of buttons sent."""

    def __init__(self):
        self.lost = False
        self._owed = 0

    def send(self, data):
        self._owed += len(data)

    def recv(self):
        owed, self._owed = self._owed, 0
        return bytes(owed)


class IdleNetwork:
    """HOST GAME and JOIN GAME both connect at once, to an IdlePeer."""

    def __init__(self):
        self.address = own_address() or bytes(4)
        self.state = STATE_IDLE
        self.target = None
        self.last = None
        self.peer = None
        self.error = ""

    def listen(self):
        self.peer = IdlePeer()
        self.state = STATE_HOST

    def connect(self, target):
        self.target = self.last = bytes(target)
        self.peer = IdlePeer()
        self.state = STATE_GUEST

    def close(self):
        self.peer = None
        self.state = STATE_IDLE

    def poll(self):
        pass
