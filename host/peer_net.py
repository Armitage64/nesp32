"""The connection to another nesp32 (PEER), for a computer standing in for
one: what the firmware asks of its hardware (nesp_hal_t's peer_*), on this
computer's own sockets.

    network = SocketNetwork(stick)      stick: host/nesp.py's Stick
    network.poll()                      call often

The firmware's stand-in hardware (host/nesp_host.c) only notes what it is
asked: to listen, to call, to hang up, and the bytes to send. This does
what a nesp32's own task does about it (firmware/main/conn.c), the same
way: datagrams to the port the firmware names, each repeating what the
other end has not said it has (the firmware's arq.c, which this uses). So
a computer and a nesp32 can be the two ends of a game.

IdleNetwork needs no other end. Whatever is asked of it, it is connected at
once, to an opponent who never presses a button.
"""

import errno
import os
import select
import socket
import time

from nesp import (ARQ_ANSWER, ARQ_BYE, ARQ_CALL, ARQ_DATA, CONN_ANSWERED, CONN_CALLED,
                  CONN_CALLING, CONN_FAILED, CONN_LISTENING, CONN_LOST, CONN_UP, Arq)

CALL_S = 3                  # how long a call is given to be answered
CALL_EVERY_S = 0.1          # between two sendings of it
GONE_S = 3                  # nothing heard for this long: the other end is gone
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
        self._sock = None
        self._arq = None            # the stream over the datagrams, once it has a name
        self._other = None          # where the other end is
        self._calling = None        # when the call was begun
        self._called_at = 0.0
        self._answering = False
        self._notes = stick.notes
        self._measured = 0
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
        if self._sock is not None:
            if self._arq is not None and self._other is not None and self._calling is None:
                for _ in range(3):      # goodbye, more than once
                    self._send(self._arq.packet(self._now(), ARQ_BYE))
            self._sock.close()
        self._sock = self._arq = self._other = self._calling = None

    @staticmethod
    def _now():
        return int(time.monotonic() * 1e6) & 0xFFFFFFFF     # as the nesp32's clock: it wraps

    def poll(self):
        stick = self.stick
        if self._orders.new():
            self.close()            # whatever there was is not wanted now
            if stick.conn == CONN_LISTENING:
                self._open(self._port())
            elif stick.conn == CONN_CALLING:
                self._dial()
        if self._sock is not None:
            if self._arq is None:
                self._hear_call()
            elif self._calling is not None:
                self._call()
            else:
                self._carry()
        if stick.keeps != self._keeps:
            self._keeps = stick.keeps
            self._save_last()

    def _port(self):
        return self.port or self.stick.conn_port

    def _fail(self, what, error):
        self.error = "%s: %s" % (what, error)
        self._arq = None            # nothing to say goodbye to
        self.close()
        self.stick.conn = CONN_FAILED

    def _open(self, port):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("0.0.0.0", port))
            sock.setblocking(False)
        except OSError as error:
            self._fail("listen", error)
            return False
        self._sock = sock
        return True

    def _send(self, packet):
        try:
            self._sock.sendto(packet, self._other)
        except OSError:
            pass                    # as a packet lost

    def _packets(self):
        """What has come, as (datagram, where from)."""
        while self._sock is not None:
            try:
                yield self._sock.recvfrom(256)
            except BlockingIOError:
                return
            except OSError:
                return              # nothing is listening at the other end

    def _hear_call(self):
        """The one that waits: the first call names the connection."""
        for packet, source in self._packets():
            if len(packet) < 24 or packet[:2] != b"NE" or packet[2] & 0x7F != ARQ_CALL:
                continue
            arq = Arq(int.from_bytes(packet[4:8], "little"))
            if arq.take(self._now(), packet) != ARQ_CALL:
                continue
            self._arq, self._other, self._answering = arq, source, True
            self.stick.conn = CONN_ANSWERED
            return

    def _dial(self):
        if not self._open(0):
            return
        self._arq = Arq(int.from_bytes(os.urandom(4), "little") | 1)
        self._other = (dotted(self.stick.conn_target), self._port())
        self._calling = time.monotonic()
        self._called_at = 0.0
        self._answering = False

    def _call(self):
        """The one that calls: again and again until it is answered."""
        now = time.monotonic()
        if now - self._calling >= CALL_S:
            self._fail("connect", "no answer")
            return
        if now - self._called_at >= CALL_EVERY_S:
            self._called_at = now
            self._send(self._arq.packet(self._now(), ARQ_CALL))
        for packet, _ in self._packets():
            if self._arq.take(self._now(), packet) == ARQ_ANSWER:
                self._calling = None
                self.stick.conn = CONN_CALLED
                return

    def _lost(self):
        self._arq = None
        self.close()
        if self.stick.conn in CONN_UP:
            self.stick.conn = CONN_LOST

    def _carry(self):
        arq, stick = self._arq, self.stick
        now = self._now()
        arq.write(stick.conn_take())
        if stick.notes != self._notes:
            self._notes = stick.notes
            arq.note(stick.note_take())
        for packet, source in self._packets():
            kind = arq.take(now, packet)
            if kind < 0:
                continue
            self._other = source
            if kind == ARQ_BYE:
                self._lost()
                return
            if kind == ARQ_DATA:
                self._answering = False
        if (now - arq.heard_at) & 0xFFFFFFFF >= GONE_S * 1e6:
            self._lost()
            return
        stick.conn_give(arq.read())
        stick.note_give(arq.noted)
        stick.rtt = arq.rtt
        if arq.rtt_count != self._measured:
            self._measured = arq.rtt_count
            stick.took(arq.rtt_last)
        if arq.due(now):
            self._send(arq.packet(now, ARQ_ANSWER if self._answering else ARQ_DATA))


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
