#!/usr/bin/env python3
"""A second player with no second console: this computer is the other
nesp32 and the console behind it, for trying a netplay ROM on one NES.

    host/peer_player.py JOIN K7QF               join the room the console opened
    host/peer_player.py HOST                    open a room, for the console to join
    host/peer_player.py JOIN 192.168.1.23       or meet by address: call the console's nesp32
    host/peer_player.py HOST --by-address       or wait for its call
    host/peer_player.py JOIN K7QF --app CNTR    another game (TMN2 by default)

The nesp32 is the firmware's own code (build/libnesp_host, from `make
host`) on this computer's sockets (peer_net.py), so a room is met at the
real rendezvous, across the Internet, as two nesp32s meet there. The
console is a few lines here: it says hello as the game, and once the two
are connected sends one byte of buttons a tick, as PEER's TICKS
(docs/PROTOCOL.md).

It keeps no game of its own, so it cannot work out the digest a console
sends in place of its buttons once in 256 ticks (CHECK_TICK). It sends
back the one it is sent, and the session goes on whatever the console's
game is. Its own ticks are paced by the console's: it sends LEAD ticks
ahead of what it has been sent, and the check tick only once it has the
console's.

What player 2 does (--play):

    copy     the console's buttons, half a second later, but Start and
             Select (the default): pick a turtle and the other follows
    still    nothing, but A tapped every two seconds, to pick
    random   a new move every 8 ticks
"""

import argparse
import random
import socket
import sys
import time

import nesp
import nesp_proto as p
import peer_net

PEER = p.NESP_SVC_PEER
CHECK_TICK = 0xFF               # of every 256, the one that carries the digest
LEAD = 4                        # ticks sent ahead of the console's
COPY_LAG = 30                   # ticks the copy is behind
STEP_S = 0.002
STATUS_S = 0.05                 # between two questions to the lobby
BTN_A, BTN_B, BTN_SELECT, BTN_START = 0x80, 0x40, 0x20, 0x10
BTN_UP, BTN_DOWN, BTN_LEFT, BTN_RIGHT = 0x08, 0x04, 0x02, 0x01
MOVES = (BTN_RIGHT, BTN_LEFT, BTN_RIGHT | BTN_B, BTN_LEFT | BTN_B, BTN_B, BTN_A,
         BTN_UP | BTN_RIGHT, BTN_DOWN | BTN_RIGHT, BTN_A | BTN_B, 0)
STATES = {p.NESP_LOBBY_NO_WIFI: "no network", p.NESP_LOBBY_IDLE: "idle",
          p.NESP_LOBBY_HOSTING: "waiting", p.NESP_LOBBY_CONNECTING: "calling",
          p.NESP_LOBBY_HOST: "connected, player 1", p.NESP_LOBBY_GUEST: "connected, player 2",
          p.NESP_LOBBY_FAILED: "failed", p.NESP_LOBBY_MEETING: "meeting"}
WHYS = {p.NESP_MEET_NO_SERVER: "the rendezvous could not be asked",
        p.NESP_MEET_NO_ROOM: "there is no room of that code",
        p.NESP_MEET_MISMATCH: "the room is another game's, or another version's",
        p.NESP_MEET_FULL: "player 2 is already in the room",
        p.NESP_MEET_UNREACHABLE: "the two could not reach each other",
        p.NESP_MEET_GONE: "the room was given up"}


class Player:
    """The console's side of a session: its ticks of buttons out, the
    other's in, by PEER's TICKS on `stick`."""

    def __init__(self, play="copy", seed=None):
        self.play = play
        self.random = random.Random(seed)
        self.mine = bytearray()     # this side's buttons, by tick
        self.theirs = bytearray()   # the console's
        self.acked = 0              # the first of mine the nesp32 does not hold
        self.move = 0

    def buttons(self, tick):
        if self.play == "copy":
            back = tick - COPY_LAG
            if back < 0:
                return 0
            if back % 256 == CHECK_TICK:
                back -= 1
            return self.theirs[back] & ~(BTN_START | BTN_SELECT)
        if self.play == "still":
            return BTN_A if tick % 120 < 4 else 0
        if tick % 8 == 0:
            self.move = self.random.choice(MOVES)
        return self.move

    def _fill(self):
        while len(self.mine) < len(self.theirs) + LEAD:
            tick = len(self.mine)
            if tick % 256 == CHECK_TICK:
                if len(self.theirs) <= tick:
                    return
                self.mine.append(self.theirs[tick])
            else:
                self.mine.append(self.buttons(tick))

    def exchange(self, stick):
        """One exchange. False once the other console is gone."""
        self._fill()
        sending = bytes(self.mine[self.acked:self.acked + 2])
        wanted = len(self.theirs)
        reply = stick.ask(PEER, p.NESP_PEER_TICKS,
                          bytes((self.acked & 0xFF, wanted & 0xFF)) + sending)
        if not reply.ok or len(reply.payload) < 3:
            return True
        after, start, lost = reply.payload[:3]
        if lost:
            return False
        self.acked += (after - self.acked) & 0xFF
        if start == wanted & 0xFF:
            self.theirs += reply.payload[3:]
        return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("order", choices=("HOST", "JOIN"))
    parser.add_argument("where", nargs="?",
                        help="JOIN: the room's code, or the console's nesp32's address")
    parser.add_argument("--by-address", action="store_true",
                        help="HOST: wait for a call to this computer's address, not in a room")
    parser.add_argument("--app", default="TMN2", help="the game's id (TMN2, CNTR, DRMA, TTRS)")
    parser.add_argument("--version", type=int, default=1, help="the game's version (DRMA is 2)")
    parser.add_argument("--play", choices=("copy", "still", "random"), default="copy")
    parser.add_argument("--rendezvous", metavar="URL",
                        help="where rooms are met in place of the firmware's own")
    parser.add_argument("--port", type=int,
                        help="the UDP port in place of 6502: for two of these on one computer")
    args = parser.parse_args(argv)
    if args.order == "JOIN" and not args.where:
        parser.error("JOIN needs a room's code or an address")
    address = peer_net.own_address()
    if address is None:
        parser.error("this computer is on no network")

    stick = nesp.Stick()
    stick.set_saved(b"This computer")
    stick.set_wifi(p.NESP_WIFI_JOINED, rssi=-50, address=address)
    network = peer_net.SocketNetwork(stick, port=args.port)
    if args.rendezvous:
        stick.set_rendezvous(args.rendezvous)
    app = args.app.upper().encode("ascii")
    if not stick.hello(app=app, version=args.version, services=[PEER]).ok:
        parser.error("the nesp32's code would not take the hello")

    room = not (args.by_address or (args.where and "." in args.where))
    if args.order == "HOST":
        order, payload = (p.NESP_PEER_HOST_ROOM, b"") if room else (p.NESP_PEER_HOST, b"")
    elif room:
        code = args.where.upper()
        if len(code) != 4 or any(letter not in "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
                                 for letter in code):
            parser.error("a room's code is four of ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
        order, payload = p.NESP_PEER_JOIN_ROOM, code.encode("ascii")
    else:
        order, payload = p.NESP_PEER_JOIN, socket.inet_aton(args.where)
    status = p.NESP_PEER_ROOM if room else p.NESP_PEER_STATUS
    print("%s v%d at %s, as %s" % (args.app.upper(), args.version, socket.inet_ntoa(address),
                                   "a room" if room else "an address"))

    player = Player(args.play)
    said = None
    asked = 0.0
    shown = 0.0
    playing = False
    try:
        reply = stick.ask(PEER, order, payload)
        while True:
            network.poll()
            stick.tick(time.monotonic() * 1000.0)
            now = time.monotonic()
            if not playing:
                if now - asked >= STATUS_S:
                    asked = now
                    reply = stick.ask(PEER, status)
                state = reply.payload[0]
                line = STATES.get(state, str(state))
                if room and reply.payload[6:10].strip():
                    line += "  room code %s" % reply.payload[6:10].decode("ascii")
                if state == p.NESP_LOBBY_FAILED:
                    why = reply.payload[10] if room else 0
                    print("failed: %s" % WHYS.get(why, network.error or "no answer"))
                    return 1
                if line != said:
                    said = line
                    print(line)
                playing = state in (p.NESP_LOBBY_HOST, p.NESP_LOBBY_GUEST)
            else:
                if not player.exchange(stick):
                    print("\nthe other console is gone, after %d ticks" % len(player.theirs))
                    return 0
                if now - shown >= 1.0:
                    shown = now
                    print("\rtick %d, sent %d ahead; console's buttons %02x   "
                          % (len(player.theirs), len(player.mine) - len(player.theirs),
                             player.theirs[-1] if player.theirs else 0), end="", flush=True)
            time.sleep(STEP_S)
    except KeyboardInterrupt:
        print()
        return 0
    finally:
        network.close()


if __name__ == "__main__":
    sys.exit(main())
