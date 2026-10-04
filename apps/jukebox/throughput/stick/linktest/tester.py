"""The throughput test: blocks, the search for the fastest stable rate, and
what goes on the two screens.

Nothing here touches hardware. A *port* does that, and the same code runs on
the Stick (device.UartPort) and against the simulated console in the tests.
A port has:

    set_baud(baud)            after what was written has left the wire
    write(data)               returns once the bytes have been sent
    read(count, timeout_ms)   up to count bytes; returns early when it has them
    discard()                 drop what has been received and not read
    sleep_ms(ms), ticks_ms()

One direction is measured at a time, a block of 256 known bytes at a time:

- RX (Stick to NES): the Stick names a rate and a seed at the control rate,
  sends the block at the rate under test, and the console answers with the
  number of bytes that arrived wrong.
- TX (NES to Stick): the same command, and the console sends the block. The
  Stick counts the wrong and missing bytes.

find_fastest climbs the ladder a trial at a time until one fails, and backs
off to the rate before it.
"""

from linktest import proto, rates
from linktest.rates import BLOCK, CPU_HZ, baud

TRIAL_BLOCKS = 4                # a trial: 1024 bytes

# The console waits this long after a test command before it listens or
# sends, and again before it answers, so the Stick's UART can change rate
# with nothing on the wire. linktest.s's settle is 30.2 ms.
SETTLE_MS = 31
GUARD_MS = 9                    # the Stick's margin on top of a settle
SWITCH_MS = 10                  # after a rate change, before trusting what was received
SHOW_BYTES = 8                  # of a failed block from the console, for the log
PING_MS = 60
DRAW_MS = 100                   # the console waits for a vblank to draw
RX_REPLY_MS = 150               # settle, checking the block, and the reply
TX_MARGIN_MS = 60
COMMAND_TRIES = 3
BLOCK_TRIES = 2                 # for a block that got no answer at all

# A console that missed part of a block is still waiting for the rest, with
# no timeout. Zero bytes at the control rate are long lows that it takes
# for bytes at any rate, which gets it to the end of the block.
FILLER = bytes(64)
FILLER_ROUNDS = 6
FILLER_REPLY_MS = 80


class Direction:
    """One way along the link: its ladder, and where it goes on the
    console's screen."""

    def __init__(self, name, title, periods, byte_cycles, work, top):
        self.name = name                # for the log and the Stick's screen
        self.title = title
        self.periods = periods          # cycles a bit, slowest first
        self.byte_cycles = byte_cycles  # period -> cycles a byte takes on the wire
        self.work = work                # period -> cycles of those the CPU needs
        self.top = top                  # first row of its part of the screen

    def bytes_per_second(self, period):
        """Payload rate with bytes sent back to back."""
        return CPU_HZ // self.byte_cycles(period)

    def cpu_percent(self, period):
        """The share of the console's CPU the routine needs during a block.
        The rest is padding between bits; at 100% the rate could go no
        higher whatever the wire did."""
        total = self.byte_cycles(period)
        return (100 * self.work(period) + total // 2) // total


# The console's screen, in tiles. Text is 28 columns wide from LEFT. Each
# direction has a title row and, under it, a row for each of ROWS.
LEFT = 2
WIDTH = 28
TITLE_ROW = 2
STATE_ROW = 4
NAMETABLE = 0x2000
COLUMNS = 32
ROWS = ("STATUS", "SPEED", "SENT", "BAD", "CPU", "FASTEST")
VALUE_COLUMN = LEFT + 9
VALUE_WIDTH = WIDTH - 9

RX = Direction("RX", "STICK TO NES", rates.TO_NES, rates.to_nes_byte, rates.to_nes_work, 7)
TX = Direction("TX", "NES TO STICK", rates.TO_STICK, rates.to_stick_byte, rates.to_stick_work, 16)


class LinkError(Exception):
    pass


class Link:
    """Commands to the console, and one block in each direction. A rate is
    an index into its direction's ladder."""

    def __init__(self, port, idle=None):
        self.port = port
        self.idle = idle or (lambda: None)  # called between blocks
        self.seq = 0
        self.seed = 0xACE1
        self.repeats = 0        # commands sent again for want of a reply
        self.stalls = 0         # blocks the console had to be helped out of
        self.tx_detail = ""     # what the last block from the console looked like

    def _send(self, op, payload=b""):
        self.seq = (self.seq + 1) & 0xFF
        self.port.discard()
        self.port.write(proto.command(self.seq, op, payload))
        return self.seq

    def _reply(self, seq, op, timeout_ms):
        port = self.port
        started = port.ticks_ms()
        data = b""
        want = proto.REPLY_SIZE
        while True:
            left = timeout_ms - (port.ticks_ms() - started)
            if left <= 0:
                return None
            data += port.read(want, left)
            value = proto.parse_reply(data, seq, op)
            if value is not None:
                return value
            want = 1

    def _exchange(self, op, payload, timeout_ms, tries=COMMAND_TRIES):
        for attempt in range(tries):
            if attempt:
                self.repeats += 1
            value = self._reply(self._send(op, payload), op, timeout_ms)
            if value is not None:
                return value
        return None

    def _next_seed(self):
        self.seed = (self.seed * 5 + 0x3611) & 0xFFFF or 0xACE1
        return self.seed

    def ping(self):
        """True if the test ROM answers, and it was built from these ladders."""
        self.port.set_baud(baud(rates.CONTROL))
        value = self._exchange(proto.OP_PING, b"", PING_MS, tries=1)
        if value is None:
            return False
        if value != (len(rates.TO_STICK) << 8 | len(rates.TO_NES)):
            raise LinkError("the ROM has other rates (%04X); rebuild and reflash" % value)
        return True

    def connect(self, attempts=None):
        """Ping until the console answers. It may have been left in the
        middle of a block by a Stick that was restarted, so every miss is
        followed by filler."""
        count = 0
        while attempts is None or count < attempts:
            if self.ping():
                return True
            count += 1
            self.port.write(FILLER)
            self.idle()
        return False

    def port_value(self):
        """What the console's $4017 reads with the line at rest, or None."""
        return self._exchange(proto.OP_PORT, b"", PING_MS)

    def draw(self, row, column, text):
        """Put text on the console's screen. True if it said it did."""
        text = text[:proto.DRAW_MAX]
        address = NAMETABLE + row * COLUMNS + column
        payload = bytes((address >> 8, address & 0xFF)) + text.encode()
        return self._exchange(proto.OP_DRAW, payload, DRAW_MS) == 0

    def rx_block(self, rate):
        """Send one block to the console at a rate. Returns the number of
        bytes it got wrong, BLOCK if it never answered."""
        port = self.port
        for _ in range(BLOCK_TRIES):
            seed = self._next_seed()
            data = proto.pattern(seed, BLOCK)
            if rates.tracked_receive(rates.TO_NES[rate]):
                # The tracking receiver settles on these, and does not count them.
                data = b"\xff" * rates.PREAMBLE + data[rates.PREAMBLE:]
            seq = self._send(proto.OP_RX, bytes((rate, seed & 0xFF, seed >> 8)))
            port.set_baud(baud(rates.TO_NES[rate]))
            port.sleep_ms(SETTLE_MS + GUARD_MS)
            port.write(data)
            port.set_baud(baud(rates.CONTROL))
            value = self._reply(seq, proto.OP_RX, RX_REPLY_MS)
            rounds = 0
            while value is None and rounds < FILLER_ROUNDS:
                rounds += 1
                port.write(FILLER)
                value = self._reply(seq, proto.OP_RX, FILLER_REPLY_MS)
            if value == proto.ERROR_VALUE:
                raise LinkError("the console refused rate %d" % rate)
            if value is not None:
                if rounds:
                    self.stalls += 1
                    value = max(value, 1)   # a block that needed filler is not clean
                return min(value, BLOCK)
            self.repeats += 1
        return BLOCK

    def tx_block(self, rate):
        """Have the console send one block at a rate. Returns the number of
        bytes that were wrong or never came."""
        port = self.port
        period = rates.TO_STICK[rate]
        block_ms = BLOCK * rates.to_stick_byte(period) * 1000 // CPU_HZ + 1
        timeout = SETTLE_MS + block_ms + TX_MARGIN_MS
        data = b""
        for _ in range(BLOCK_TRIES):
            seed = self._next_seed()
            expected = proto.pattern(seed, BLOCK)
            self._send(proto.OP_TX, bytes((rate, seed & 0xFF, seed >> 8)))
            port.set_baud(baud(period))
            # Changing rate can leave a byte of junk in the receiver, and one
            # byte ahead of the block puts every byte after it out of place.
            # The console is still in its settle, so drop whatever is there.
            port.sleep_ms(SWITCH_MS)
            port.discard()
            data = port.read(BLOCK, timeout)
            port.set_baud(baud(rates.CONTROL))
            if data:
                break
            self.repeats += 1       # silence: the command may have been lost
        bad = BLOCK - len(data)
        for index in range(len(data)):
            if data[index] != expected[index]:
                bad += 1
        self.tx_detail = "%d bytes came, first %s, expected %s" % (
            len(data), _hex(data[:SHOW_BYTES]), _hex(expected[:SHOW_BYTES]))
        return bad


def _hex(data):
    return " ".join("%02x" % byte for byte in data) or "none"


def find_fastest(run, count):
    """The highest rate that passes its trial, or None.

    run(rate) runs a trial and says whether it was clean. Rates are
    0 .. count - 1, slowest first. Each is tried once, in order, until one
    fails; the answer is the one before it. No rate is tried twice.
    """
    rate = 0
    while rate < count and run(rate):
        rate += 1
    return rate - 1 if rate else None


class Session:
    """One whole test: both directions, both screens, and the log.

    display is the Stick's own screen, anything with set(**rows); log takes
    a line of text. Either can be left out.

    The console's screen has the first direction on its upper half and the
    other on its lower. A half shows the trial that is running: the rate,
    the bytes sent and found bad so far, and the share of the CPU the rate
    takes. When a direction's search ends, its half goes back to the
    fastest rate that held, with that trial's figures.
    """

    def __init__(self, link, display=None, log=None, blocks=TRIAL_BLOCKS):
        self.link = link
        self.display = display
        self.log = log or (lambda line: None)
        self.blocks = blocks
        self.best = {}          # direction name -> period, or None
        self.trials = []        # (direction name, period, bytes sent, bytes bad)
        self.drawn = {}         # (row, column) -> text on the console's screen
        self.port_ok = True     # until check_port says otherwise

    # --- the screens ---------------------------------------------------------

    def _show(self, **rows):
        if self.display is not None:
            self.display.set(**rows)

    def _draw(self, row, column, text, width):
        text = text[:width]
        if self.drawn.get((row, column)) == text:
            return
        if self.link.draw(row, column, text + " " * (width - len(text))):
            self.drawn[row, column] = text

    def _state(self, text):
        self._show(state=text)
        self._draw(STATE_ROW, LEFT, text, WIDTH)

    def _value(self, direction, name, text):
        self._draw(direction.top + 1 + ROWS.index(name), VALUE_COLUMN, text, VALUE_WIDTH)

    def _figures(self, direction, period, sent, bad):
        self._value(direction, "SPEED", "%d BPS" % baud(period))
        self._value(direction, "SENT", "%d BYTES" % sent)
        self._value(direction, "BAD", "%d BYTES" % bad)
        self._value(direction, "CPU", "%d%%" % direction.cpu_percent(period))

    def paint(self):
        """The console's screen as a run starts from it."""
        self.drawn = {}
        self._draw(STATE_ROW, LEFT, "", WIDTH)
        for direction in (RX, TX):
            self._draw(direction.top, LEFT, direction.title, WIDTH)
            for index, name in enumerate(ROWS):
                self._draw(direction.top + 1 + index, LEFT, " " + name, WIDTH)
            self._value(direction, "STATUS", "WAITING")
        self._show(rx="", tx="", last="")

    # --- trials --------------------------------------------------------------

    def check_port(self):
        """The console's receivers count on what its port reads. Ask, and
        on a console that reads something else run nothing to it."""
        value = self.link.port_value()
        self.port_ok = value == rates.PORT_IDLE
        if not self.port_ok:
            self.log("the console's $4017 reads %s, not %02x: its receivers cannot work"
                     % ("nothing" if value is None else "%02x" % value, rates.PORT_IDLE))

    def rate_count(self, direction):
        """How far up its ladder a direction may go."""
        if direction is RX and not self.port_ok:
            return 0
        return len(direction.periods)

    def trial(self, direction, rate):
        """Blocks at one rate, stopping at the first that is not clean."""
        block = self.link.rx_block if direction is RX else self.link.tx_block
        period = direction.periods[rate]
        self._show(state="%s %d BPS" % (direction.name, baud(period)))
        self._value(direction, "STATUS", "CLIMBING")
        self._value(direction, "FASTEST", "")
        self._figures(direction, period, 0, 0)
        sent = bad = 0
        started = self.link.port.ticks_ms()
        for _ in range(self.blocks):
            bad += block(rate)
            sent += BLOCK
            self._value(direction, "SENT", "%d BYTES" % sent)
            self.link.idle()
            if bad:
                break
        self._value(direction, "BAD", "%d BYTES" % bad)
        self.trials.append((direction.name, period, sent, bad))
        # The time is the check that the rate is real: a block is 30 to 70 ms
        # of waiting plus its time on the wire, 0.3 s at the slowest rate
        # and under 0.02 s at the fastest.
        self.log("%s %6d bps: %d of %d bytes bad, cpu %d%%, %d ms" % (
            direction.name, baud(period), bad, sent,
            direction.cpu_percent(period), self.link.port.ticks_ms() - started))
        if bad and direction is TX:
            self.log("  last block: " + self.link.tx_detail)
        self._show(last="%s %d: %d/%d bad" % (direction.name, baud(period), bad, sent))
        return bad == 0

    def search(self, direction):
        """Find one direction's fastest stable rate; returns its period."""
        rate = find_fastest(lambda rate: self.trial(direction, rate),
                            self.rate_count(direction))
        period = None if rate is None else direction.periods[rate]
        self.best[direction.name] = period
        if period is None:
            text = "NO STABLE RATE"
            self._value(direction, "STATUS", "DONE")
            self._value(direction, "FASTEST", "NONE")
        else:
            text = "%d BPS %d B/S" % (baud(period), direction.bytes_per_second(period))
            # The last trial was usually the rate above failing; go back to
            # the figures of the one that held.
            sent = [trial[2] for trial in self.trials
                    if trial[:2] == (direction.name, period)][-1]
            self._value(direction, "STATUS", "DONE")
            self._figures(direction, period, sent, 0)
            self._value(direction, "FASTEST", "%d BYTES/S" % direction.bytes_per_second(period))
        self._show(**{direction.name.lower(): text})
        self.log("%s fastest stable: %s" % (direction.name, text.lower()))
        return period

    def run(self):
        """Connect, measure both directions, and leave the results up.
        Returns the two periods (RX, TX), None for no stable rate."""
        self._show(state="WAITING FOR NES")
        self.link.connect()
        self.check_port()
        self.paint()
        self._state("TESTING")
        rx = self.search(RX)
        tx = self.search(TX)
        self.log("%d commands repeated, %d blocks stalled"
                 % (self.link.repeats, self.link.stalls))
        self._state("DONE")
        return rx, tx
