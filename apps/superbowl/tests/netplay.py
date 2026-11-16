"""Two consoles on the netplay ROM, each with a nesp32, and a network between
the nesp32s. It is River City Ransom's (apps/rcr/tests/netplay.py), with
Tecmo Super Bowl's tick: an NMI that runs the game's tasks.

The nesp32s are the firmware's own link and services, built for this
computer (nesp32's host/nesp.py), each on a simulated serial line
(wire.py). What the firmware asks of its hardware for a connection to
another nesp32 is answered here: Lan is the network, on which a call is
answered and bytes cross, each after a delay. It is the Internet too, as
far as rooms need one: the rendezvous is nesp32's stand-in for it, asked
directly, and two nesp32s that each punch toward the other meet.

The consoles have a clock each (console.py) and the table has one more,
which the network's delay is counted on. A slice at a time, each console is
run up to the table's clock and its nesp32 is polled.

What a test asks of a game is that it is the same on both consoles. They do
not take a tick at the same moment, so the states are compared tick by
tick: `traces` holds each console's digest of the game's memory as it stood
when each tick was taken, where the game's NMI goes on into its tasks
(TICK_AT).
"""

import nesp_proto as p
from console import FRAME_CYCLES, PAD_A, PAD_DOWN, PAD_RIGHT, PAD_START, Console
from nesp import CONN_ANSWERED, CONN_CALLED, CONN_CALLING, CONN_FAILED, CONN_LISTENING
from nesp import CONN_LOST, CONN_MEETING, CONN_MET, CONN_UP, Stick
from rendezvous import Rooms
from nesp_proto import NESP_CPU_HZ
from wire import SLICE, link, ms

APP = b"TSBO"
PEER = p.NESP_SVC_PEER
PLAYERS_STATES = (p.NESP_LOBBY_HOST, p.NESP_LOBBY_GUEST)
NET_MODE, NET_TICK, NET_DELAY = "net_mode", "net_tick", "net_delay"
TICK_AT = "NMI_UPDATE_RANDOM_NUMS"
# From the power on to the game's first screen. A session starts the game
# again from its reset in any case.
BOOT_FRAMES = 60

def guard_stack(console):
    """Fail if the NMI's exchange writes to the stack below the STACK_KEEP
    bytes net_nmi_read keeps and puts back: the first task's would be
    spoiled. From net_nmi_read to its call of net_sram_back."""
    keep = console.labels["STACK_KEEP"]
    entry = []                  # the stack at net_nmi_read, while in it

    def enter(console):
        entry[:] = [console.mpu.sp]
        console.watch_writes()

    def leave(console):
        # Its own call: a jsr from net_nmi_read's level.
        if not entry or console.mpu.sp != (entry[0] - 2) & 0xFF:
            return
        lowest = 0x100 + entry[0] - keep + 1
        under = [address for address in console.written() if 0x100 <= address < lowest]
        assert not under, "the exchange wrote the stack at $%04X, below the kept $%04X" % (
            min(under), lowest)
        entry.clear()
        console.bus.written = None

    console.watch("net_nmi_read", enter)
    console.watch("net_sram_back", leave)


TASKS = tuple(task for task, _ in Console.TASK_STACKS)


def guard_tasks(console):
    """Fail if the scheduler takes up a task that is none of the eight: the
    idle loop given back a wrong X, as by an NMI that broke into another's
    end (the menu's, before menu_nmi_on waited for the RTI)."""
    def taken(console):
        assert console.mpu.x in TASKS, "the scheduler took up a task at $%02X, frame %d" % (
            console.mpu.x, len(console.frames))
    console.watch("UPDATE_CURRENT_TASK", taken)


class Lan:
    """The network the two nesp32s are on. `delay` is how long anything
    takes to cross it, in cycles: a number or a function returning one."""

    def __init__(self, table, delay):
        self.table = table
        self.delay = delay
        self.sticks = []
        self.addresses = []
        self.calls = []             # each one's calls, as last seen
        self.answer_at = []
        self.arriving = []          # for each: (cycle, data) on their way to it
        self.last_due = []
        self.noted = []             # how many notes each had left, as last seen
        self.notes = []             # for each: (cycle, note) on their way to it
        self.up = False
        self.rooms = Rooms()
        self.meets = []             # each one's meetings, fetches and punches, as last seen
        self.fetches = []
        self.punches = []
        self.punched = []           # each one's punch: (listen, session, addresses), or None
        self.reachable = True       # whether two that punch toward each other meet

    def add(self, stick, address):
        self.sticks.append(stick)
        self.addresses.append(bytes(address) if address else None)
        self.calls.append(stick.calls)
        self.answer_at.append(None)
        self.arriving.append([])
        self.last_due.append(0.0)
        self.noted.append(stick.notes)
        self.notes.append([])
        self.meets.append(stick.meets)
        self.fetches.append(stick.fetches)
        self.punches.append(stick.punches)
        self.punched.append(None)

    def latency(self):
        return self.delay() if callable(self.delay) else self.delay

    def cut(self):
        """The connection is gone, with whatever was on its way."""
        for side, stick in enumerate(self.sticks):
            if stick.conn in CONN_UP:
                stick.conn = CONN_LOST
            self.arriving[side].clear()
        self.up = False

    def _meet(self):
        """Rooms: each socket's address is found at once, the rendezvous
        answers at once, and two that punch toward each other with one
        session are connected a trip there and back later."""
        now = self.table.now
        for side, stick in enumerate(self.sticks):
            if stick.meets != self.meets[side]:
                self.meets[side] = stick.meets
                self.punched[side] = None
                if stick.conn == CONN_MEETING:
                    stick.candidates = [(self.addresses[side], 6502)]
                    stick.conn = CONN_MET
            if stick.fetches != self.fetches[side]:
                self.fetches[side] = stick.fetches
                if stick.fetching:
                    _, line = self.rooms.answer("/v1/" + stick.fetch_url.split("/v1/", 1)[1])
                    stick.fetch_body(line.encode() + b"\n")
                    stick.fetch_done()
            if stick.punches != self.punches[side]:
                self.punches[side] = stick.punches
                listen, session, others = stick.punch
                self.punched[side] = (listen, session, [address for address, _ in others])
                self.answer_at[side] = now + 2 * self.latency()
        caller = next((side for side, punch in enumerate(self.punched)
                       if punch and not punch[0] and self.sticks[side].conn == CONN_CALLING), None)
        if caller is None or now < self.answer_at[caller]:
            return
        host = 1 - caller
        theirs = self.punched[host]
        if (self.reachable and theirs and theirs[0] and theirs[1] == self.punched[caller][1]
                and self.sticks[host].conn == CONN_LISTENING
                and self.addresses[host] in self.punched[caller][2]):
            self.sticks[caller].conn, self.sticks[host].conn = CONN_CALLED, CONN_ANSWERED
            self.punched = [None, None]
            self.up = True
        elif not self.reachable:
            # Routers neither of which lets the other in: the call is given
            # up (after seconds, on a nesp32: no matter here).
            self.sticks[caller].conn = CONN_FAILED
            self.punched[caller] = None

    def poll(self):
        now = self.table.now
        self._meet()
        for side, stick in enumerate(self.sticks):
            if stick.conn != CONN_CALLING or self.punched[side] is not None:
                continue
            if stick.calls != self.calls[side]:     # a new call: there and back
                self.calls[side] = stick.calls
                self.answer_at[side] = now + 2 * self.latency()
            elif now >= self.answer_at[side]:
                self._answer(side)
        if not self.up:
            return
        if any(stick.conn not in CONN_UP for stick in self.sticks):
            self.cut()              # one of them hung up
            return
        for side, stick in enumerate(self.sticks):
            other = 1 - side
            # What a nesp32 knows of the network: how long it takes there
            # and back, now and as every packet has found it. And its notes
            # for the other, of which only the latest matters.
            there_and_back = 2 * self.latency() * 1e6 / NESP_CPU_HZ
            stick.rtt = there_and_back
            if self.up:
                stick.took(there_and_back)      # every packet measures it
            if stick.notes != self.noted[side]:
                self.noted[side] = stick.notes
                self.notes[other].append((now + self.latency(), stick.note_take()))
            notes = self.notes[side]
            while notes and notes[0][0] <= now:
                stick.note_give(notes.pop(0)[1])
            data = stick.conn_take()
            if data:
                # A stream: nothing overtakes what was sent before it.
                due = max(now + self.latency(), self.last_due[other])
                self.last_due[other] = due
                self.arriving[other].append((due, data))
            arriving = self.arriving[side]
            while arriving and arriving[0][0] <= now:
                # As much as the nesp32 has room for: the rest waits, as
                # the stream's window does (a save is more than its room).
                due, data = arriving[0]
                taken = stick.conn_give(data)
                if taken < len(data):
                    arriving[0] = (due, data[taken:])
                    break
                arriving.pop(0)

    def _answer(self, side):
        caller, other = self.sticks[side], self.sticks[1 - side]
        if (other.conn == CONN_LISTENING and self.addresses[1 - side] is not None
                and caller.conn_target == self.addresses[1 - side]):
            caller.conn, other.conn = CONN_CALLED, CONN_ANSWERED
            self.up = True
        else:
            caller.conn = CONN_FAILED


ADDRESSES = ((192, 168, 1, 23), (192, 168, 1, 42))


class Table:
    def __init__(self, make_console, delay=ms(10), drift=0.0, turnaround=ms(0.2),
                 port_options=None, addresses=ADDRESSES, input_delay=None,
                 console_options=({}, {})):
        self.now = 0.0
        # The delay each console begins a session with: its nesp32's advice,
        # as the menu takes it, unless a test says otherwise.
        self.input_delay = input_delay
        self.consoles = (make_console(**console_options[0]),
                         make_console(frame_cycles=FRAME_CYCLES * (1 + drift),
                                      **console_options[1]))
        self.lan = Lan(self, delay)
        self.sticks = []
        self.ports = []
        self.traces = ({}, {})
        port_options = port_options or ({}, {})
        for side, console in enumerate(self.consoles):
            options = dict(turnaround=turnaround)
            options.update(port_options[side])
            stick, port = link(console, Stick, **options)
            console.host = None         # the table polls, on its own clock
            if addresses[side]:
                stick.set_wifi(p.NESP_WIFI_JOINED, rssi=-50, address=addresses[side])
            self.lan.add(stick, addresses[side])
            self.sticks.append(stick)
            self.ports.append(port)
            # A tick's game as it stands at its start: where the game's NMI
            # goes on into its tasks, once the exchange has put back the
            # stack and the zero page it worked in.
            console.watch(TICK_AT, lambda console, side=side: self._taken(side, console))
            guard_stack(console)
            guard_tasks(console)
        self.offsets = [0.0, 0.0]
        self.changes = {}           # tick: what to do to each console's memory before it
        # What to do to each console's memory before every tick from one to
        # another (every_tick): (first, last or None, change).
        self.each_tick = None

    def every_tick(self, change):
        """Change each console's memory before every tick from the next one
        neither has taken, as a change the game made itself would be: it
        must depend on the game alone. None stops it, from the next such
        tick on. (The two are some ticks apart: a change from the tick each
        is at would be one tick's on one and another's on the other.)"""
        next_tick = max(self.ticks(0), self.ticks(1)) + 2
        if change is None:
            if self.each_tick is not None:
                self.each_tick = (self.each_tick[0], next_tick, self.each_tick[2])
        else:
            self.each_tick = (next_tick, None, change)

    def at_tick(self, tick, change, sides=(0, 1)):
        """Change each console's memory as it takes this tick: both alike, as
        a change the game made itself would be, unless `sides` says one."""
        self.changes[tick] = (change, sides)

    def restart(self, side):
        """A console's nesp32 is switched off and on: it is on the network
        again, and knows of no hello."""
        stick = Stick(self.ports[side])
        address = self.lan.addresses[side]
        if address:
            stick.set_wifi(p.NESP_WIFI_JOINED, rssi=-50, address=address)
        self.lan.cut()
        self.lan.sticks[side] = self.sticks[side] = stick
        self.lan.calls[side] = stick.calls
        self.lan.meets[side] = stick.meets
        self.lan.fetches[side] = stick.fetches
        self.lan.punches[side] = stick.punches
        self.lan.punched[side] = None
        return stick

    def boot(self, apart=0.3):
        """Both consoles to the first screen. The second gets there `apart`
        of a frame after the first."""
        self.run(BOOT_FRAMES)
        self.offsets[1] = -apart * FRAME_CYCLES

    def start(self, apart=0.3):
        """Both consoles to the first screen, then straight into a session
        with no menu: the nesp32s are told what the menu would tell them,
        and the first console is player 1. `apart` is how far into the
        first console's frame the second one's begins."""
        self.boot(apart)
        host, guest = self.sticks
        for stick in self.sticks:
            assert stick.hello(app=APP, services=[PEER]).ok
        assert host.ask(PEER, p.NESP_PEER_HOST).ok
        assert guest.ask(PEER, p.NESP_PEER_JOIN, self.lan.addresses[0]).ok
        for _ in range(120):
            if (host.lobby, guest.lobby) == PLAYERS_STATES:
                break
            self.run(1)
        assert (host.lobby, guest.lobby) == PLAYERS_STATES
        for side, console in enumerate(self.consoles):
            mpu = console.mpu
            mpu.a = side
            advice = self.sticks[side].ask(PEER, p.NESP_PEER_STATUS).payload[5]
            mpu.x = self.input_delay or advice
            # The netplay's bank at $A000, as the menu has it when it calls.
            console.write_mapper(0x8000, 0x07)
            console.write_mapper(0x8001, console.labels["NET_BANK"])
            mpu.pc = console.labels["net_start_session"]
            console.interrupts = []
        self.begun()

    def begun(self):
        """A session has just begun on both consoles: what frames() and
        stalls() count from, and the ticks compared: any taken before it
        were named by where the table began counting, not the session."""
        self.started = [len(console.frames) for console in self.consoles]
        self.traces = ({}, {})
        for console in self.consoles:
            console.count_calls("net_late_stall")

    def to_game(self):
        """From a session's start, at the main menu (net_intro), to the
        kickoff of a preseason game, MAN VS MAN, Buffalo against Cleveland:
        player 1 presses on the first console, player 2 on the second. The
        frames it took."""
        start = self.frames()
        script = [(90, 0, PAD_A),           # PRESEASON: a session begins at the main menu
                  (100, 0, PAD_DOWN),       # MAN VS MAN
                  (40, 0, PAD_A),
                  (150, 0, PAD_A),          # player 1's team: Buffalo
                  (60, 1, PAD_RIGHT),       # player 2's: Cleveland
                  (40, 1, PAD_A)]
        for wait, side, button in script:
            self.run(wait)
            pads = [0, 0]
            pads[side] = button
            self.run(3, tuple(pads))
        return self.frames() - start

    def _taken(self, side, console):
        """A tick taken: the game as it stands at the read."""
        tick = self.ticks(side)
        if tick in self.traces[side]:
            return
        if tick in self.changes and side in self.changes[tick][1]:
            self.changes[tick][0](console)
        if self.each_tick is not None:
            first, last, change = self.each_tick
            if tick >= first and (last is None or tick < last):
                change(console)
        self.traces[side][tick] = console.state()

    def ticks(self, side):
        """The tick a console is at, past the 8 bits it keeps. A session
        begins a few ticks before 0, by the delay the console began with."""
        console = self.consoles[side]
        if not console.byte(NET_MODE):
            console._ticks = None
            return 0
        low = console.byte(NET_TICK)
        seen = getattr(console, "_ticks", None)
        if seen is None:
            seen = low - 256 if low >= 0x80 else low
        seen += (low - seen) & 0xFF
        console._ticks = seen
        return seen

    def delays(self):
        return tuple(console.byte(NET_DELAY) for console in self.consoles)

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
            self.lan.poll()

    def play(self, frames, moves):
        """Run with a new pair of buttons from `moves` every frame."""
        for _ in range(frames):
            self.run(1, next(moves))

    def same_game(self):
        """How many ticks both consoles have taken, having checked that the
        game was the same on both at each of them."""
        shared = sorted(set(self.traces[0]) & set(self.traces[1]))
        for tick in shared:
            assert self.traces[0][tick] == self.traces[1][tick], "the games differ at tick %d" % tick
        return len(shared)

    def frames(self, side=0):
        """Frames a console has had since its session began."""
        return len(self.consoles[side].frames) - self.started[side]

    def waits(self, side=0):
        """Tries of a console's session that found the other console's
        buttons not yet there."""
        return self.consoles[side].calls_of("net_late_stall")
