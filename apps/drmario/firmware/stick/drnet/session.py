"""A session's traffic: the console's frames on one side, the other Stick on
the other. Nothing here touches hardware or the network.

A *peer* is the connection to the other Stick: send(data), recv() returning
the bytes that have come (maybe none), and `lost`, true once it is gone.

Both consoles count ticks from 0 and use no buttons for the first
INPUT_DELAY of them, so each Stick's stream to the other is one byte a
tick, in order, starting with the buttons for tick INPUT_DELAY. Nothing
else crosses, and a byte's place in the stream is its tick.

The console says which ticks it sends and which it wants by their low 8
bits. It can never be more than a ring of ticks from what this side holds,
so that is enough to tell which is meant.
"""

from drnet.linkrate import (
    CHECKED,
    FRAME_SIZE,
    INPUT_DELAY,
    PEER_LOST,
    PEER_OK,
    PER_FRAME,
    REPLY_GAME,
    REQUEST_CONTROL,
    REQUEST_GAME,
    checks,
)

REQUESTS = (REQUEST_GAME, REQUEST_CONTROL)


def frame(data):
    """A frame from its first CHECKED bytes."""
    data = bytes(data)
    return data + bytes(checks(data))


def find_frames(buffer):
    """Take the requests out of what the UART has received. Returns them and
    the bytes that may still be the start of one. Anything else is passed
    over a byte at a time: the console's controller read is on this line
    too, and comes through as noise."""
    found = []
    start = 0
    while start + FRAME_SIZE <= len(buffer):
        candidate = bytes(buffer[start:start + FRAME_SIZE])
        if (candidate[0] in REQUESTS
                and tuple(candidate[CHECKED:]) == checks(candidate[:CHECKED])):
            found.append(candidate)
            start += FRAME_SIZE
        else:
            start += 1
    return found, bytes(buffer[start:])


class Session:
    def __init__(self, peer):
        self.peer = peer
        self.local_next = INPUT_DELAY   # this console's next tick to take
        self.remote = bytearray()       # the other's buttons, not yet taken
        self.remote_base = INPUT_DELAY  # the tick of remote[0]
        self.requests = 0
        self.repeats = 0                # requests that brought nothing new

    @property
    def lost(self):
        return self.peer.lost

    def pump(self):
        """Take what the other Stick has sent."""
        arrived = self.peer.recv()
        if arrived:
            self.remote += arrived

    def game(self, request):
        """The reply to a session's request."""
        first, count, wanted = request[1], request[2], request[5]
        self.requests += 1
        # Its buttons: those of them not seen before go to the other Stick.
        skip = (self.local_next - first) & 0xFF
        if skip < count <= PER_FRAME:
            fresh = request[3 + skip:3 + count]
            self.peer.send(fresh)
            self.local_next += len(fresh)
        else:
            self.repeats += 1
        # The other's: it has everything before the tick it asks for.
        taken = (wanted - self.remote_base) & 0xFF
        # (MicroPython has no `del` on a bytearray, and no ljust.)
        if 0 < taken <= len(self.remote):
            self.remote = self.remote[taken:]
            self.remote_base += taken
        ready = bytes(self.remote[:PER_FRAME])
        state = PEER_LOST if self.peer.lost and not ready else PEER_OK
        padded = ready + bytes(PER_FRAME - len(ready))
        return frame((REPLY_GAME, self.local_next & 0xFF, self.remote_base & 0xFF,
                      len(ready) | state) + tuple(padded))


def no_session(request):
    """The reply to a session's request when there is no session: the
    other console is gone."""
    return frame((REPLY_GAME, request[1], request[5], PEER_LOST, 0, 0))
