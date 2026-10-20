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

A meeting across the Internet (HOST_ROOM, JOIN_ROOM) is the same: the
socket is opened at the port named, its addresses are found (with STUN,
unless told not to), and once PEER has been told the other's at the
rendezvous both ends send to each other's at once. The rendezvous is asked
over HTTP, as the nesp32's own fetch would (HttpFetches), and is the real
one unless the firmware is pointed at another (Stick.set_rendezvous).

IdleNetwork needs no other end. Whatever is asked of it, it is connected at
once, to an opponent who never presses a button.
"""

import errno
import os
import queue
import select
import socket
import threading
import time
import urllib.error
import urllib.request

from nesp import (ARQ_ANSWER, ARQ_BYE, ARQ_CALL, ARQ_DATA, CONN_ANSWERED, CONN_CALLED,
                  CONN_CALLING, CONN_FAILED, CONN_LISTENING, CONN_LOST, CONN_MEETING, CONN_MET,
                  CONN_UP, Arq, stun_mapped, stun_request)

CALL_S = 3                  # how long a call is given to be answered
CALL_EVERY_S = 0.1          # between two sendings of it
GONE_S = 3                  # nothing heard for this long: the other end is gone
LAST_PATH = os.path.expanduser("~/.nesp32_peer_last")
GREETING = 10               # bytes each end says first (nesp_services.h's NESP_PEER_GREETING)
MEET_CALL_S = 8             # a meeting's call, and the wait for it (conn.c's MEET_CALL_MS)
STUN_WAIT_S = 1.5           # a socket's addresses found as far as they will be, by then
STUN_SERVERS = (("stun.cloudflare.com", 3478), ("stun.l.google.com", 19302))
PUNCH = b"NE\x04" + bytes(21)  # arq.c's nesp_arq_punch: names no connection


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


class HttpFetches:
    """The nesp32's fetches, made over HTTP from this computer, each on a
    thread of its own; what comes is handed over at the next poll."""

    def __init__(self, stick):
        self.stick = stick
        self._seen = stick.fetches
        self._came = queue.Queue()

    def poll(self):
        stick = self.stick
        if stick.fetches != self._seen:
            self._seen = stick.fetches
            if stick.fetching:
                threading.Thread(target=self._fetch, daemon=True,
                                 args=(stick.fetch_id, stick.fetch_url,
                                       stick.fetch_agent)).start()
        while True:
            try:
                fetch, body, ok, why = self._came.get_nowait()
            except queue.Empty:
                return
            if body:
                stick.fetch_body(body, fetch=fetch)
            stick.fetch_done(ok=ok, why=why, fetch=fetch)

    def _fetch(self, fetch, url, agent):
        request = urllib.request.Request(url, headers={"User-Agent": agent})
        try:
            with urllib.request.urlopen(request, timeout=10) as reply:
                self._came.put((fetch, reply.read(), True, b""))
        except urllib.error.HTTPError as error:
            self._came.put((fetch, error.read(), True, b""))     # its answer says why
        except OSError as error:
            self._came.put((fetch, b"", False, str(error).encode()[:30]))


class Orders:
    """What a nesp32 has been asked since it was last looked at: its
    stand-in hardware counts each kind."""

    def __init__(self, stick):
        self.stick = stick
        self.seen = self._counts()

    def _counts(self):
        return self.stick.listens, self.stick.calls, self.stick.closes, self.stick.meets

    def new(self):
        counts = self._counts()
        if counts == self.seen:
            return False
        self.seen = counts
        return True


class SocketNetwork:
    """port, if given, is used in place of the one the firmware names: for
    two ends on one machine that must not be mistaken for a real game.
    last_path is where the address last joined is kept. stun: the STUN
    servers a meeting asks what the Internet sees of its socket, as (name,
    port); none for a test on one machine, which has no need to. meet_call_s: how long a meeting's
    call, or the wait for it, is kept up."""

    def __init__(self, stick, port=None, last_path=LAST_PATH, stun=STUN_SERVERS,
                 meet_call_s=MEET_CALL_S):
        self.stick = stick
        self.port = port
        self.last_path = last_path
        self.stun = stun
        self.meet_call_s = meet_call_s
        self.error = ""
        self._orders = Orders(stick)
        self._fetches = HttpFetches(stick)
        self._punches = stick.punches
        self._meeting = None        # when the meeting's socket was opened, while it waits
        self._asked = {}            # STUN: the id of each request out, by server
        self._mapped = {}           # and what each said
        self._targets = []          # where a meeting's call goes, or its punches
        self._session = None        # the one call a meeting's host takes
        self._until = None          # when a meeting's wait or call is given up
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
        self._meeting = self._session = self._until = None
        self._targets = []

    @staticmethod
    def _now():
        return int(time.monotonic() * 1e6) & 0xFFFFFFFF     # as the nesp32's clock: it wraps

    def poll(self):
        stick = self.stick
        self._fetches.poll()
        if self._orders.new():
            self.close()            # whatever there was is not wanted now
            if stick.conn == CONN_LISTENING:
                self._open(self._port())
            elif stick.conn == CONN_CALLING:
                self._dial()
            elif stick.conn == CONN_MEETING:
                self._meet()
        if stick.punches != self._punches:
            self._punches = stick.punches
            if self._sock is not None:
                self._punch()
        if self._sock is not None:
            if self._meeting is not None:
                self._wait_to_punch()
            elif self._arq is None:
                if self._targets:
                    self._send_punches()
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

    # --- a meeting -----------------------------------------------------------------

    def _meet(self):
        if not self._open(self._port()):
            return
        self._meeting = time.monotonic()
        self._mapped = {}
        self._asked = {}
        if self.stun:
            for server in self.stun:
                try:
                    where = (socket.gethostbyname(server[0]), server[1])
                except OSError:
                    continue
                ident = os.urandom(12)
                self._asked[server] = ident
                try:
                    self._sock.sendto(stun_request(ident), where)
                except OSError:
                    pass
        self._publish()

    def _publish(self):
        """The socket's addresses, for the firmware: its own on this
        network first, then what each server saw, if that is another."""
        port = self._sock.getsockname()[1]
        found = [(own_address() or bytes((127, 0, 0, 1)), port)]
        for mapped in self._mapped.values():
            if mapped not in found:
                found.append(mapped)
        self.stick.candidates = found[:4]

    def _wait_to_punch(self):
        for packet, _ in self._packets():
            for server, ident in self._asked.items():
                mapped = stun_mapped(packet, ident)
                if mapped is not None:
                    self._mapped[server] = mapped
                    self._publish()
        answered = len(self._mapped) == len(self._asked)
        if self.stick.conn == CONN_MEETING \
                and (answered or time.monotonic() - self._meeting >= STUN_WAIT_S):
            self.stick.conn = CONN_MET

    def _punch(self):
        """PEER has been told the other's addresses: call them, or wait
        for its call and send to them meanwhile."""
        listen, session, others = self.stick.punch
        self._meeting = None
        self._targets = [(dotted(address), port) for address, port in others]
        self._until = time.monotonic() + self.meet_call_s
        if listen:
            self._session = session
            self._sent_at = 0.0
        else:
            self._arq = Arq(session)
            self._calling = time.monotonic()
            self._called_at = 0.0
            self._answering = False

    def _send_punches(self):
        now = time.monotonic()
        if now >= self._until:
            self._fail("meet", "no call came")
            return
        if now - self._sent_at >= CALL_EVERY_S:
            self._sent_at = now
            for target in self._targets:
                self._send_to(PUNCH, target)

    def _send_to(self, packet, where):
        try:
            self._sock.sendto(packet, where)
        except OSError:
            pass                    # as a packet lost

    # --- waiting and calling ------------------------------------------------------

    def _hear_call(self):
        """The one that waits: the first call names the connection, or in
        a meeting, the first of the session the rendezvous named."""
        for packet, source in self._packets():
            if self._sock is None:
                return
            if len(packet) < 24 or packet[:2] != b"NE" or packet[2] & 0x7F != ARQ_CALL:
                continue
            session = int.from_bytes(packet[4:8], "little")
            if self._session is not None and session != self._session:
                continue
            arq = Arq(session)
            if arq.take(self._now(), packet) != ARQ_CALL:
                continue
            self._arq, self._other, self._answering = arq, source, True
            self._targets = []
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
        """The one that calls: again and again until it is answered. A
        meeting's call goes to each of the other's addresses, and the one
        that answers is the other end."""
        now = time.monotonic()
        if now - self._calling >= (self.meet_call_s if self._targets else CALL_S):
            self._fail("connect", "no answer")
            return
        if now - self._called_at >= CALL_EVERY_S:
            self._called_at = now
            packet = self._arq.packet(self._now(), ARQ_CALL)
            for target in self._targets or [self._other]:
                self._send_to(packet, target)
        for packet, source in self._packets():
            if self._arq.take(self._now(), packet) == ARQ_ANSWER:
                self._calling = None
                self._other = source
                self._targets = []
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
        self._punches = stick.punches
        self._fetches = stick.fetches

    def close(self):
        pass

    def _room(self):
        """The rendezvous, as far as the opponent needs one: every room is
        open, and the opponent in it at once."""
        stick = self.stick
        if stick.fetches == self._fetches or not stick.fetching:
            return
        self._fetches = stick.fetches
        path = stick.fetch_url.split("/v1/", 1)[-1]
        line = {"host": "ROOM ZZZZ 00000001", "room": "GUEST 127.0.0.2:6502",
                "join": "HOST 00000001 127.0.0.2:6502"}[path.split("/")[0].split("?")[0]]
        stick.fetch_body(line.encode() + b"\n")
        stick.fetch_done()

    def poll(self):
        stick = self.stick
        self._room()
        if self._orders.new():
            self._greeted = 0
            if stick.conn == CONN_LISTENING:
                stick.conn = CONN_ANSWERED
            elif stick.conn == CONN_CALLING:
                stick.conn = CONN_CALLED
            elif stick.conn == CONN_MEETING:
                stick.candidates = [(bytes((127, 0, 0, 1)), 6502)]
                stick.conn = CONN_MET
        if stick.punches != self._punches:
            self._punches = stick.punches
            stick.conn = CONN_ANSWERED if stick.punch[0] else CONN_CALLED
        if stick.conn not in CONN_UP:
            return
        sent = stick.conn_take()
        greeting = sent[:GREETING - self._greeted]
        self._greeted += len(greeting)
        stick.conn_give(greeting + bytes(len(sent) - len(greeting)))
