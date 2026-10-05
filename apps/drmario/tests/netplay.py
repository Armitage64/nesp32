"""Two consoles on the netplay ROM, each with a Stick, and a network between
the Sticks.

The Sticks are drnet.stick's own code on a simulated serial line (wire.py)
and a simulated network: Lan is the network, and each Stick's FakeNet is
its place on it, with an address.

The consoles have a clock each (console.py) and the table has one more,
which the network's delay is counted on. A slice at a time, each console is
run up to the table's clock and its Stick's code is polled.

What a test asks of a game is that it is the same on both consoles. They do
not take a tick at the same moment, so the states are compared tick by
tick: `trace` is each console's digest of the game's memory as it stood
before each tick.
"""

import hashlib

from console import FRAME_CYCLES
from drive import BOOT_FRAMES
from drnet.linkrate import (
    STATE_CONNECTING,
    STATE_FAILED,
    STATE_GUEST,
    STATE_HOST,
    STATE_HOSTING,
    STATE_IDLE,
    STATE_NO_WIFI,
)
from drnet.stick import Stick
from wire import SLICE, link, ms

NET_MODE, NET_TICK, NET_WAITING = "net_mode", "net_tick", "net_waiting"
# Memory that is not the game's: the stack page, the link's scratch and
# buffers, and the session's own numbers, which differ by design.
NOT_GAME = ((0x100, 0x200), (0x6A, 0x70), (0x330, 0x340), (0x742, 0x75B))


def game_state(console):
    ram = bytearray(console.ram)
    for start, end in NOT_GAME:
        ram[start:end] = bytes(end - start)
    return hashlib.sha1(ram).hexdigest()


class End:
    """One end of a connection: what it sends reaches the other end the
    Lan's delay later, in order."""

    def __init__(self, lan):
        self.lan = lan
        self.other = None
        self.arriving = []      # (cycle, data)
        self.last_due = 0.0
        self.lost = False
        self.sent = 0

    def drop(self):
        """The connection is gone, with whatever was on its way."""
        self.lost = True
        self.arriving.clear()

    def send(self, data):
        other = self.other
        if other.lost:
            return
        # A stream: nothing overtakes what was sent before it.
        due = max(self.lan.table.now + self.lan.latency(), other.last_due)
        other.last_due = due
        other.arriving.append((due, bytes(data)))
        self.sent += len(data)

    def recv(self):
        now = self.lan.table.now
        out = b""
        while self.arriving and self.arriving[0][0] <= now:
            out += self.arriving.pop(0)[1]
        return out


class Lan:
    """The network the Sticks are on. `delay` is how long anything takes to
    cross it, in cycles: a number or a function returning one."""

    def __init__(self, table, delay):
        self.table = table
        self.delay = delay
        self.nets = []

    def latency(self):
        return self.delay() if callable(self.delay) else self.delay

    def listening_at(self, address):
        for net in self.nets:
            if net.address == address and net.state == STATE_HOSTING:
                return net
        return None


class FakeNet:
    """A Stick's network, as drnet.stick asks for it."""

    def __init__(self, lan, address):
        self.lan = lan
        self.address = bytes(address) if address else None
        self.state = STATE_IDLE if address else STATE_NO_WIFI
        self.last = None
        self.target = None
        self.peer = None
        self._answer_at = None
        lan.nets.append(self)

    def listen(self):
        if self.address:
            self.state = STATE_HOSTING

    def connect(self, target):
        if not self.address:
            return
        self.target = bytes(target)
        self.state = STATE_CONNECTING
        self._answer_at = self.lan.table.now + 2 * self.lan.latency()

    def close(self):
        if self.peer is not None:
            self.peer.drop()
            self.peer.other.lost = True
        self.peer = None
        self._answer_at = None
        self.state = STATE_IDLE if self.address else STATE_NO_WIFI

    def poll(self):
        if self.state != STATE_CONNECTING or self.lan.table.now < self._answer_at:
            return
        host = self.lan.listening_at(self.target)
        if host is None:
            self.state = STATE_FAILED
            return
        self.peer, host.peer = End(self.lan), End(self.lan)
        self.peer.other, host.peer.other = host.peer, self.peer
        self.state, host.state = STATE_GUEST, STATE_HOST
        self.last = self.target


ADDRESSES = ((192, 168, 1, 23), (192, 168, 1, 42))


class Table:
    def __init__(self, make_console, delay=ms(10), drift=0.0, turnaround=ms(1.0),
                 port_options=None, addresses=ADDRESSES):
        self.now = 0.0
        self.consoles = (make_console(), make_console(frame_cycles=FRAME_CYCLES * (1 + drift)))
        self.lan = Lan(self, delay)
        self.nets = [FakeNet(self.lan, address) for address in addresses]
        self.sticks = []
        self.ports = []
        self.traces = ({}, {})
        port_options = port_options or ({}, {})
        for side, console in enumerate(self.consoles):
            options = dict(turnaround=turnaround)
            options.update(port_options[side])
            net = self.nets[side]
            stick, port = link(console, lambda port, net=net: Stick(port, net), **options)
            console.host = None         # the table polls, on its own clock
            self.sticks.append(stick)
            self.ports.append(port)
            console.on_vblank = lambda console, side=side: self._before_nmi(side, console)
        self.offsets = [0.0, 0.0]

    @property
    def sessions(self):
        return [stick.session for stick in self.sticks]

    def boot(self, apart=0.3):
        """Both consoles to the title. The second gets there `apart` of a
        frame after the first."""
        self.run(BOOT_FRAMES)
        self.offsets[1] = -apart * FRAME_CYCLES

    def start(self, apart=0.3):
        """Both consoles to the title, then straight into a session with no
        menu: the Sticks connect, and the first console is player 1."""
        self.boot(apart)
        self.nets[0].listen()
        self.nets[1].connect(self.nets[0].address)
        while self.nets[1].state == STATE_CONNECTING:
            self.run(1)
        assert self.nets[1].state == STATE_GUEST
        for side, console in enumerate(self.consoles):
            mpu = console.mpu
            mpu.a = side
            mpu.pc = console.labels["net_start_session"]
            console.in_nmi = False

    def _before_nmi(self, side, console):
        if console.byte(NET_MODE) and console.byte(NET_WAITING):
            self.traces[side].setdefault(self.ticks(side), game_state(console))

    def ticks(self, side):
        """Ticks a console has taken, past the 8 bits it keeps."""
        console = self.consoles[side]
        if not console.byte(NET_MODE):
            return getattr(console, "_ticks", 0)
        low = console.byte(NET_TICK)
        seen = getattr(console, "_ticks", 0)
        seen += (low - seen) & 0xFF
        console._ticks = seen
        return seen

    def run(self, frames, pads=(0, 0)):
        """Run for about this many frames of the table's clock, with these
        buttons held on each console's controller."""
        until = self.now + frames * FRAME_CYCLES
        while self.now < until:
            self.now += SLICE
            for side, console in enumerate(self.consoles):
                console.run_until(self.now + self.offsets[side], pads=(pads[side], 0))
                self.ticks(side)
                self.sticks[side].poll()

    def play(self, frames, moves):
        """Run with a new pair of buttons from `moves` every frame."""
        for _ in range(frames):
            self.run(1, next(moves))

    def same_game(self):
        """How many ticks both consoles have taken, having checked that the
        game was the same on both before each of them."""
        shared = sorted(set(self.traces[0]) & set(self.traces[1]))
        for tick in shared:
            assert self.traces[0][tick] == self.traces[1][tick], "the games differ at tick %d" % tick
        return len(shared)
