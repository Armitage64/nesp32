"""What the Stick does for the console, less the hardware: it answers the
menu's commands, and in a session passes buttons to and from the other
Stick. Nothing here touches hardware or the network.

A *port* is the UART to the console: read() returns the bytes that have
come, or None, and write(data) sends.

A *network* makes the connection to the other Stick:

    state       one of linkrate's STATE_*
    address     this Stick's IPv4 address, 4 bytes, or None off the network
    last        the address last joined, 4 bytes, or None
    target      the address being joined, or joined
    peer        the connection, once state is STATE_HOST or STATE_GUEST
                (session.py says what a peer is); it stays, `lost`, after
                the other end has gone, until close()
    listen()    wait for the other Stick: STATE_HOSTING, then STATE_HOST
    connect(a)  join the Stick at an address: STATE_CONNECTING, then
                STATE_GUEST or STATE_FAILED
    close()     drop any of that: STATE_IDLE
    poll()      called often
"""

from drnet.linkrate import (
    CMD_CANCEL,
    CMD_HOST,
    CMD_JOIN,
    CMD_LAST,
    REPLY_CONTROL,
    REQUEST_GAME,
    STATE_CONNECTING,
    STATE_GUEST,
    STATE_HOST,
    STATE_HOSTING,
)
from drnet.session import Session, find_frames, frame, no_session

NO_ADDRESS = b"\0\0\0\0"


class Stick:
    def __init__(self, port, network):
        self.port = port
        self.network = network
        self.session = None
        self._heard = b""
        self.commands = 0           # control requests answered

    def poll(self):
        """Call often: answers the console if it has asked."""
        network = self.network
        network.poll()
        peer = network.peer
        if peer is None:
            self.session = None
        elif self.session is None or self.session.peer is not peer:
            self.session = Session(peer)
        if self.session is not None:
            self.session.pump()
        heard = self.port.read()
        if not heard:
            return
        requests, self._heard = find_frames(self._heard + heard)
        reply = None
        for request in requests:
            if request[0] == REQUEST_GAME:
                reply = self._game(request)
            else:
                reply = self._control(request)
        # Only the last is answered: the console has stopped listening for
        # the others.
        if reply is not None:
            self.port.write(reply)

    def _game(self, request):
        if self.session is None:
            return no_session(request)
        return self.session.game(request)

    def _control(self, request):
        """A command does nothing when it is what the Stick is already
        doing, so the console can send one again if it missed the reply."""
        network = self.network
        command = request[1]
        self.commands += 1
        if command == CMD_HOST:
            if network.state not in (STATE_HOSTING, STATE_HOST):
                network.close()
                network.listen()
        elif command == CMD_JOIN:
            target = bytes(request[2:6])
            if not (network.state in (STATE_CONNECTING, STATE_GUEST)
                    and network.target == target):
                network.close()
                network.connect(target)
        elif command == CMD_CANCEL:
            network.close()
            self.session = None
        elif command == CMD_LAST:
            return frame((REPLY_CONTROL, network.state) + tuple(network.last or NO_ADDRESS))
        return frame((REPLY_CONTROL, network.state) + tuple(network.address or NO_ADDRESS))
