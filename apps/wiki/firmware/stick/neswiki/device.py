"""Wire the Stick's hardware to the Server (UIFlow 2.0 firmware only).

The loop does one thing as often as it can: Server.poll(), which answers
the console. When a search comes in, the connection to Wikipedia is made
here, and during it and the TLS handshake nothing is polled: the console
waits. After that the article is read and laid out a piece at a time
(fetch.py), and only while the console is within a few pages of the end of
what is held, so most of the time the Stick has nothing to do but answer.

The buttons, the screen and garbage collection run right after a reply goes
out, when the console will not ask again before its next frame, or every
IDLE_CHORES_MS while it is not asking at all.

Wi-Fi is the network saved in UIFlow's settings (M5Burner's configure step,
or tools/set_wifi.py); it is not read from a file. /flash/config.json is
optional:

    board    "s3" or "plus2", if the board is not recognised
    tx, rx   link pins, for a hat wired differently from board.py's table
    invert   false for a non-inverting level shifter (default true)
"""

import gc
import json
import sys
import time

import esp32

from neswiki import VERSION, board, net, proto
from neswiki.fetch import Fetch
from neswiki.linkrate import COLUMNS, baud
from neswiki.server import Server
from neswiki.ui import StatusScreen
from neswiki.wrap import Article

CONFIG_PATH = "/flash/config.json"

# The article's buffer, biggest first: the first that the heap has room for.
BUFFER_BYTES = (256 * 1024, 128 * 1024, 64 * 1024, 32 * 1024)
# A collection takes some 70 ms on a Plus2, four of the console's frames:
# the collector reads through the whole of the article's buffer (it takes
# 7 ms without one). So the loop is written to make no garbage while it
# waits, and a collection is never run while the console is asking for
# lines: only once it has been quiet for GC_QUIET_MS, and then no more
# often than every GC_EVERY_MS.
GC_QUIET_MS = 150
GC_EVERY_MS = 3000
SLOW_US = 8000              # a turn of the loop longer than this is counted
# Laying out an article is done in the gaps between the console's requests.
# While it is asking every frame (16.6 ms), a piece of work is started only
# in the first WORK_US after a reply went out, so the Stick is listening
# again before the next request. When it has not asked for QUIET_US it is
# not asking every frame, and the work runs freely.
WORK_US = 7000
QUIET_US = 30000
IDLE_CHORES_MS = 50         # buttons and screen while the console is not asking
BUSY_CHORES_MS = 250        # and while it is: they take long enough to cost a frame
STATUS_MS = 500
LOG_MS = 5000
BATTERY_MS = 10000
WIFI_RETRY_MS = 15000
STATES = ("IDLE", "NO WI-FI", "FETCHING", "READY", "NOT FOUND", "ERROR")


class PowerOff(Exception):
    pass


class UartPort:
    """The link UART as the Server wants it."""

    def __init__(self, uart):
        self.uart = uart
        self.buffer = bytearray(board.RX_BUFFER)
        self.view = memoryview(self.buffer)

    def read(self):
        # Asked first, and read into a buffer kept for it. uart.read() makes
        # a new 256-byte buffer every time it is called, data or no data,
        # and the loop calls this hundreds of times a second: that was
        # 150 KB of garbage a second, and a 70 ms collection every 20 KB.
        if not self.uart.any():
            return None
        count = self.uart.readinto(self.buffer)
        if not count:
            return None
        return bytes(self.view[:count])

    def write(self, data):
        self.uart.write(data)


def uiflow_wifi():
    """(ssid, password) saved by M5Burner or UIFlow's setup; ("", "") if
    there is none."""
    nvs = esp32.NVS("uiflow")
    try:
        ssid = nvs.get_str("ssid0")
    except OSError:
        return "", ""
    try:
        password = nvs.get_str("pswd0")
    except OSError:
        password = ""
    return ssid, password


def load_config():
    try:
        with open(CONFIG_PATH) as handle:
            config = json.load(handle)
    except OSError:
        config = {}  # config.json is optional
    if not isinstance(config.get("invert", True), bool):
        raise ValueError("invert must be true (NPN shifter) or false")
    return config


def new_article():
    for size in BUFFER_BYTES:
        try:
            return Article(size // COLUMNS)
        except MemoryError:
            gc.collect()
    raise MemoryError("no room for an article")


class Device:
    def __init__(self):
        board.init()
        self.screen = StatusScreen(VERSION)
        self.buttons = board.Buttons()
        self.article = None
        self.server = None
        self.fetch = None
        self.ssid = self.password = ""
        self.gc_us_max = 0
        self.fetch_ms = 0
        now = time.ticks_ms()
        self._chores_at = now
        self._status_at = now
        self._log_at = now
        self._battery_at = time.ticks_add(now, -BATTERY_MS)
        self._wifi_at = now
        self._gc_at = now
        self._request_at = now
        self._answered_us = 0
        # For the log: the longest of each thing the loop does, and how
        # often a turn of it took too long to answer a request in time.
        self._turn_us = time.ticks_us()
        self.poll_us_max = self.chore_us_max = self.work_us_max = self.turn_us_max = 0
        self.slow_turns = 0
        self.turns = 0
        self.answer_us = self.answers = 0       # time spent in polls that answered
        self.chore_us = self.chore_count = 0
        self.button_us_max = self.paint_us_max = 0
        # Requests found behind a newer one: was the loop away (the turn
        # before was long), or was it looking and the UART gave it two at
        # once?
        self.late_away = self.late_together = 0

    def chores(self, now):
        """Everything except the link. Called between requests; keep it short."""
        self._chores_at = now
        started = time.ticks_us()
        _, b_held = self.buttons.poll()
        elapsed = time.ticks_diff(time.ticks_us(), started)
        if elapsed > self.button_us_max:
            self.button_us_max = elapsed
        if b_held:
            raise PowerOff()
        if time.ticks_diff(now, self._battery_at) >= BATTERY_MS:
            self._battery_at = now
            self.screen.set(battery="%d%%" % board.battery_percent())
        if time.ticks_diff(now, self._status_at) >= STATUS_MS:
            self._status_at = now
            self.show_status()
        if time.ticks_diff(now, self._log_at) >= LOG_MS:
            self._log_at = now
            server = self.server
            print("req %d lines %d late %d noise %d held %d reached %d reopened %d "
                  "connect %d ms; max us: turn %d poll %d chore %d work %d gc %d; slow turns %d; "
                  "free %d threshold %d"
                  % (server.requests, server.line_requests, server.unanswered,
                     server.decoder.discarded, self.article.count, server.reached,
                     self.fetch.reopened, self.fetch_ms, self.turn_us_max, self.poll_us_max,
                     self.chore_us_max, self.work_us_max, self.gc_us_max, self.slow_turns,
                     gc.mem_free(), gc.threshold()))
            print("  turns %d; answers %d avg %d us; chores %d avg %d us, buttons max %d, "
                  "paint max %d; late: away %d, together %d"
                  % (self.turns, self.answers, self.answer_us // max(1, self.answers),
                     self.chore_count, self.chore_us // max(1, self.chore_count),
                     self.button_us_max, self.paint_us_max, self.late_away,
                     self.late_together))
            self.gc_us_max = self.poll_us_max = self.chore_us_max = 0
            self.work_us_max = self.turn_us_max = self.slow_turns = 0
            self.turns = self.answer_us = self.answers = 0
            self.chore_us = self.chore_count = 0
            self.button_us_max = self.paint_us_max = 0
            self.late_away = self.late_together = 0
        started = time.ticks_us()
        self.screen.refresh()
        elapsed = time.ticks_diff(time.ticks_us(), started)
        if elapsed > self.paint_us_max:
            self.paint_us_max = elapsed

    def show_status(self):
        server = self.server
        self.screen.set(
            state=STATES[server.state],
            wifi=self.ssid if net.is_connected() else "not joined",
            title=self.article.title.decode() if self.article.title else "",
            lines=("%d" % self.article.count if server.state == proto.READY
                   else "%d so far" % self.article.count if self.fetch.active else ""),
            link="%d req, %d lines, %d noise" % (
                server.requests, server.line_requests, server.decoder.discarded),
        )

    def collect(self):
        started = time.ticks_us()
        gc.collect()
        elapsed = time.ticks_diff(time.ticks_us(), started)
        if elapsed > self.gc_us_max:
            self.gc_us_max = elapsed

    def join_wifi(self, timeout_ms):
        if not self.ssid:
            return False
        joined = net.connect(self.ssid, self.password, timeout_ms=timeout_ms,
                             on_wait=self.screen.refresh)
        self.server.online = joined
        return joined

    def begin(self, query):
        """Start on a search: connect, and ask. The article comes in
        afterwards, a piece per work()."""
        server = self.server
        started = time.ticks_ms()
        self.screen.set(state="FETCHING", title=query.decode(), lines="", error="")
        self.screen.refresh(everything=True)
        try:
            if not net.is_connected() and not self.join_wifi(4000):
                raise OSError("no Wi-Fi")
            self.fetch.start(query.decode())
        except Exception as error:
            self.failed(error)
        self.fetch_ms = time.ticks_diff(time.ticks_ms(), started)
        print("search %r: connected in %d ms" % (query, self.fetch_ms))
        self.collect()
        self._gc_at = time.ticks_ms()

    def work(self):
        """Lay out a little more of the article."""
        server = self.server
        try:
            result = self.fetch.step()
        except Exception as error:
            self.failed(error)
            return
        if result is None:
            return
        if result == proto.NOT_FOUND:
            self.article.clear()
        server.finish(result)
        print("search over: %s, %d lines" % (STATES[server.state], self.article.count))
        self.show_status()

    def failed(self, error):
        sys.print_exception(error)
        self.fetch.close()
        self.article.clear()
        text = str(error) or type(error).__name__
        self.server.finish(proto.ERROR, text)
        self.screen.set(error=text)
        self.show_status()

    def serve(self):
        while True:
            self.step()

    def step(self):
        """One turn of the loop: answer the console, and see to whatever
        that leaves time for."""
        server = self.server
        started = time.ticks_us()
        last_turn = time.ticks_diff(started, self._turn_us)
        self._turn_us = started
        self.turns += 1
        if last_turn > self.turn_us_max:
            self.turn_us_max = last_turn
        if last_turn > SLOW_US:
            self.slow_turns += 1
        late = server.unanswered
        answered = server.poll()
        elapsed = time.ticks_diff(time.ticks_us(), started)
        if elapsed > self.poll_us_max:
            self.poll_us_max = elapsed
        if answered:
            self.answers += 1
            self.answer_us += elapsed
        if server.unanswered != late:
            if last_turn > SLOW_US:
                self.late_away += server.unanswered - late
            else:
                self.late_together += server.unanswered - late
        query = server.take_search()
        if query is not None:
            self.begin(query)
            self._turn_us = time.ticks_us()     # the connection is not a slow turn
            return
        now = time.ticks_ms()
        if answered:
            # The console will not ask again before its next frame.
            self._request_at = now
            self._answered_us = time.ticks_us()
            if self.fetch.active and server.hungry():
                # That time goes to the article; the screen can wait.
                while (self.fetch.active and server.hungry() and time.ticks_diff(
                        time.ticks_us(), self._answered_us) < WORK_US):
                    self.timed_work()
                return
            if time.ticks_diff(now, self._chores_at) >= BUSY_CHORES_MS:
                self.timed_chores(now)
        elif (time.ticks_diff(now, self._chores_at) >= IDLE_CHORES_MS
              and time.ticks_diff(now, self._request_at) >= 2 * IDLE_CHORES_MS):
            # Only once the console has stopped asking: a request that came
            # in the middle of these would go unanswered.
            self.timed_chores(now)
            if (time.ticks_diff(now, self._request_at) >= GC_QUIET_MS
                    and time.ticks_diff(now, self._gc_at) >= GC_EVERY_MS):
                self._gc_at = now
                self.collect()
                self._turn_us = time.ticks_us()
            # The network may come and go by itself; searches are answered
            # by how it is now.
            server.online = net.is_connected()
            if not server.online and time.ticks_diff(now, self._wifi_at) >= WIFI_RETRY_MS:
                self._wifi_at = now
                self.join_wifi(3000)
        if (self.fetch.active and server.hungry() and time.ticks_diff(
                time.ticks_us(), self._answered_us) > QUIET_US):
            self.timed_work()       # a piece; then the link is looked at again

    def timed_chores(self, now):
        started = time.ticks_us()
        self.chores(now)
        elapsed = time.ticks_diff(time.ticks_us(), started)
        self.chore_count += 1
        self.chore_us += elapsed
        if elapsed > self.chore_us_max:
            self.chore_us_max = elapsed

    def timed_work(self):
        started = time.ticks_us()
        self.work()
        elapsed = time.ticks_diff(time.ticks_us(), started)
        if elapsed > self.work_us_max:
            self.work_us_max = elapsed

    def start(self):
        config = load_config()
        label, tx, rx = board.detect(config.get("board"))
        tx = config.get("tx", tx)
        rx = config.get("rx", rx)
        self.screen.set(board=label, state="STARTING")
        self.screen.refresh(everything=True)
        # Open the UART before anything slow, so TX rests at mark.
        uart = board.open_link_uart(tx, rx, invert=config.get("invert", True))
        self.article = new_article()
        before = time.ticks_us()
        gc.collect()
        print("free %d, used %d, a collection takes %d us"
              % (gc.mem_free(), gc.mem_alloc(), time.ticks_diff(time.ticks_us(), before)))
        self.server = Server(self.article, UartPort(uart), online=False)
        self.fetch = Fetch(self.article, lambda query: net.open_search(query))
        print("NESpedia %s on %s: TX G%d, RX G%d, %d baud, room for %d lines"
              % (VERSION, label, tx, rx, baud(), self.article.capacity))
        self.ssid, self.password = uiflow_wifi()
        if not self.ssid:
            self.screen.set(error="No Wi-Fi saved. Use M5Burner.")
        else:
            self.screen.set(wifi="joining " + self.ssid)
            self.screen.refresh(everything=True)
            if not self.join_wifi(20000):
                self.screen.set(error="could not join Wi-Fi; will retry")
        self.collect()
        # UIFlow has the allocator collect after every 20 KB it hands out.
        # Collections are made here instead, when the console is quiet.
        try:
            gc.threshold(-1)
        except (AttributeError, TypeError) as error:
            print("gc threshold not set:", error)
        self.show_status()

    def run(self):
        try:
            self.start()
            self.serve()
        except PowerOff:
            # The UART stays open so TX rests at mark (D0 high at the NES).
            self.screen.off()
            board.power_off()
        except Exception as error:
            sys.print_exception(error)
            self.screen.set(state="ERROR", error="%s: %s" % (type(error).__name__, error))
            self.screen.refresh(everything=True)


def main():
    Device().run()
