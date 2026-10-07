"""The connection to another nesp32 (PEER), for a computer standing in for
one: what the firmware asks of its hardware (nesp_hal_t's peer_*), on this
computer's own sockets.

    network = SocketNetwork(stick)      stick: host/nesp.py's Stick
    network.poll()                      call often

The firmware's stand-in hardware (host/nesp_host.c) only notes what it is
asked: to listen, to call, to hang up, and the bytes to send. This does
what a nesp32's own task does about it (firmware/main/conn.c), the same
way: TCP, the port the firmware names, nothing round the bytes. So a
computer and a nesp32 can be the two ends of a game.

IdleNetwork needs no other end. Whatever is asked of it, it is connected at
once, to an opponent who never presses a button.
"""

import errno
import os
import select
import socket
import time

from nesp import (CONN_ANSWERED, CONN_CALLED, CONN_CALLING, CONN_FAILED, CONN_LISTENING,
                  CONN_LOST, CONN_UP)

CALL_S = 3                  # how long a call is given to be answered
LAST_PATH = os.path.expanduser("~/.nesp32_peer_last")
GREETING = 10               # bytes each end says first (nesp_services.h's NESP_PEER_GREETING)


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


class Orders:
    """What a nesp32 has been asked since it was last looked at: its
    stand-in hardware counts each kind."""

    def __init__(self, stick):
        self.stick = stick
        self.seen = self._counts()

    def _counts(self):
        return self.stick.listens, self.stick.calls, self.stick.closes

    def new(self):
        counts = self._counts()
        if counts == self.seen:
            return False
        self.seen = counts
        return True


class SocketNetwork:
    """port, if given, is used in place of the one the firmware names: for
    two ends on one machine that must not be mistaken for a real game.
    last_path is where the address last joined is kept."""

    def __init__(self, stick, port=None, last_path=LAST_PATH):
        self.stick = stick
        self.port = port
        self.last_path = last_path
        self.error = ""
        self._orders = Orders(stick)
        self._server = None
        self._sock = None
        self._dialing = None        # when the call was begun
        self._unsent = b""
        self._keeps = stick.keeps
        stick.last = self._load_last()

    def _load_last(self):
        try:
            with open(self.last_path, "rb") as handle:
                data = handle.read()
        except OSError:
            return None
        return data if len(data) == 4 else None

    def _save_last(self):
        try:
            with open(self.last_path, "wb") as handle:
                handle.write(self.stick.last)
        except OSError as error:
            self.error = "address not saved: %s" % error

    def close(self):
        for sock in (self._server, self._sock):
            if sock is not None:
                sock.close()
        self._server = self._sock = self._dialing = None
        self._unsent = b""

    def poll(self):
        stick = self.stick
        if self._orders.new():
            self.close()            # whatever there was is not wanted now
            if stick.conn == CONN_LISTENING:
                self._listen()
            elif stick.conn == CONN_CALLING:
                self._dial()
        if self._server is not None:
            self._accept()
        elif self._dialing is not None:
            self._answered()
        elif self._sock is not None:
            self._carry()
        if stick.keeps != self._keeps:
            self._keeps = stick.keeps
            self._save_last()

    def _port(self):
        return self.port or self.stick.conn_port

    def _fail(self, what, error):
        self.error = "%s: %s" % (what, error)
        self.close()
        self.stick.conn = CONN_FAILED

    def _listen(self):
        try:
            server = socket.socket()
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("0.0.0.0", self._port()))
            server.listen(1)
            server.setblocking(False)
        except OSError as error:
            self._fail("listen", error)
            return
        self._server = server

    def _accept(self):
        try:
            sock, _ = self._server.accept()
        except BlockingIOError:
            return                  # nobody yet
        except OSError as error:
            self._fail("accept", error)
            return
        self._server.close()
        self._server = None
        self._up(sock, CONN_ANSWERED)

    def _dial(self):
        sock = socket.socket()
        sock.setblocking(False)
        result = sock.connect_ex((dotted(self.stick.conn_target), self._port()))
        if result not in (0, errno.EINPROGRESS, errno.EWOULDBLOCK):
            sock.close()
            self._fail("connect", os.strerror(result))
            return
        self._sock = sock
        self._dialing = time.monotonic()

    def _answered(self):
        sock = self._sock
        if not select.select([], [sock], [], 0)[1]:
            if time.monotonic() - self._dialing >= CALL_S:
                self._fail("connect", "no answer")
            return
        error = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        if error:
            self._fail("connect", os.strerror(error))
            return
        self._dialing = None
        self._up(sock, CONN_CALLED)

    def _up(self, sock, state):
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setblocking(False)
        except OSError as error:
            self._fail("connect", error)
            return
        self._sock = sock
        self.stick.conn = state

    def _lost(self):
        self.close()
        if self.stick.conn in CONN_UP:
            self.stick.conn = CONN_LOST

    def _carry(self):
        sock = self._sock
        self._unsent += self.stick.conn_take()
        if self._unsent:
            try:
                self._unsent = self._unsent[sock.send(self._unsent):]
            except BlockingIOError:
                pass
            except OSError:
                self._lost()
                return
        try:
            data = sock.recv(64)
        except BlockingIOError:
            return                  # nothing has come
        except OSError:
            self._lost()
            return
        if not data:
            self._lost()            # the other end closed
            return
        self.stick.conn_give(data)


class IdleNetwork:
    """HOST and JOIN both connect at once, to an opponent who says what
    this nesp32 says of itself and then, for every tick of buttons sent,
    sends a tick of none."""

    def __init__(self, stick):
        self.stick = stick
        self.error = ""
        self._orders = Orders(stick)
        self._greeted = 0

    def close(self):
        pass

    def poll(self):
        stick = self.stick
        if self._orders.new():
            self._greeted = 0
            if stick.conn == CONN_LISTENING:
                stick.conn = CONN_ANSWERED
            elif stick.conn == CONN_CALLING:
                stick.conn = CONN_CALLED
        if stick.conn not in CONN_UP:
            return
        sent = stick.conn_take()
        greeting = sent[:GREETING - self._greeted]
        self._greeted += len(greeting)
        stick.conn_give(greeting + bytes(len(sent) - len(greeting)))
