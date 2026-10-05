"""The Stick's main loop on UIFlow 2.0 firmware (MicroPython only).

It answers the console (drnet.stick), which asks once a frame in a session
and a few times a second from its menu, and in between sees to the screen
and the buttons. The way of it is nes-wiki's (firmware/stick/neswiki/
device.py).

The screen shows this Stick's address, which is what player 2 enters on the
other console, and what the Stick is doing. The console's menu chooses that;
the Stick's buttons do not. Hold button B for two seconds to switch off.

Wi-Fi is the network saved in UIFlow's settings (M5Burner's configure step,
or tools/set_wifi.py).

Garbage: UIFlow has the allocator collect whenever it has handed out 20 KB,
at a time of its choosing, and a collection is several ms in which a
request goes unanswered. So that is turned off, and collections are made
here just after a reply has gone out, when the console will not ask again
until its next frame.
"""

import gc
import json
import sys
import time

import esp32

from drnet import VERSION, board, net
from drnet.linkrate import (
    STATE_CONNECTING,
    STATE_FAILED,
    STATE_GUEST,
    STATE_HOST,
    STATE_HOSTING,
    STATE_IDLE,
    STATE_NO_WIFI,
    baud,
)
from drnet.stick import Stick
from drnet.ui import StatusScreen

CONFIG_PATH = "/flash/config.json"
GC_EVERY_ANSWERS = 30       # in a session: twice a second
GC_IDLE_MS = 2000
IDLE_CHORES_MS = 50         # buttons and screen while the console is not asking
BUSY_CHORES_MS = 250        # and while it is: they take long enough to cost a frame
STATUS_MS = 500
LOG_MS = 5000
BATTERY_MS = 10000
WIFI_MS = 2000              # how often the address is looked at
WIFI_RETRY_MS = 15000
STATES = {
    STATE_NO_WIFI: "NO WI-FI",
    STATE_IDLE: "IDLE",
    STATE_HOSTING: "HOSTING",
    STATE_CONNECTING: "CONNECTING",
    STATE_HOST: "PLAYER 1",
    STATE_GUEST: "PLAYER 2",
    STATE_FAILED: "NOT CONNECTED",
}


class PowerOff(Exception):
    pass


class UartPort:
    """The link UART as the Stick's code wants it."""

    def __init__(self, uart):
        self.uart = uart
        self.buffer = bytearray(board.RX_BUFFER)
        self.view = memoryview(self.buffer)
        self.wrote = False      # set by a reply; the loop clears it

    def read(self):
        # Asked first, and read into a buffer kept for it: uart.read()
        # makes a new buffer every time it is called, data or no data.
        if not self.uart.any():
            return None
        count = self.uart.readinto(self.buffer)
        if not count:
            return None
        return bytes(self.view[:count])

    def write(self, data):
        self.uart.write(data)
        self.wrote = True


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


class Device:
    def __init__(self):
        board.init()
        self.screen = StatusScreen(VERSION)
        self.buttons = board.Buttons()
        self.network = None
        self.port = None
        self.stick = None
        self.ssid = self.password = ""
        self.gc_us_max = 0
        self.answers = 0
        self._since_gc = 0
        now = time.ticks_ms()
        self._chores_at = now
        self._status_at = now
        self._log_at = now
        self._gc_at = now
        self._answer_at = now
        self._battery_at = time.ticks_add(now, -BATTERY_MS)
        self._wifi_at = time.ticks_add(now, -WIFI_MS)
        self._retry_at = now

    def chores(self, now):
        """Everything except the link. Called between requests; keep it short."""
        self._chores_at = now
        _, b_held = self.buttons.poll()
        if b_held:
            raise PowerOff()
        if time.ticks_diff(now, self._battery_at) >= BATTERY_MS:
            self._battery_at = now
            self.screen.set(battery="%d%%" % board.battery_percent())
        if time.ticks_diff(now, self._wifi_at) >= WIFI_MS:
            self._wifi_at = now
            self.network.refresh()
        if time.ticks_diff(now, self._status_at) >= STATUS_MS:
            self._status_at = now
            self.show_status()
        if time.ticks_diff(now, self._log_at) >= LOG_MS:
            self._log_at = now
            session = self.stick.session
            print("state %s, commands %d, answers %d, session %s, gc max %d us, free %d"
                  % (STATES[self.network.state], self.stick.commands, self.answers,
                     "%d requests %d repeats" % (session.requests, session.repeats)
                     if session else "none", self.gc_us_max, gc.mem_free()))
            self.gc_us_max = 0
        self.screen.refresh()

    def show_status(self):
        network = self.network
        session = self.stick.session
        self.screen.set(
            address=net.dotted(network.address) if network.address else "no address",
            state=STATES[network.state],
            wifi=self.ssid if network.address else "not joined",
            peer=net.dotted(network.target) if network.target and network.state in (
                STATE_CONNECTING, STATE_GUEST) else "",
            link="%d ticks, %d repeats" % (session.requests, session.repeats) if session else "",
            error=network.error,
        )

    def collect(self):
        started = time.ticks_us()
        gc.collect()
        elapsed = time.ticks_diff(time.ticks_us(), started)
        if elapsed > self.gc_us_max:
            self.gc_us_max = elapsed
        self._since_gc = 0
        self._gc_at = time.ticks_ms()

    def join_wifi(self, timeout_ms):
        if not self.ssid:
            return False
        return net.connect(self.ssid, self.password, timeout_ms=timeout_ms,
                           on_wait=self.screen.refresh)

    def step(self):
        """One turn of the loop: answer the console, and see to whatever
        that leaves time for."""
        port = self.port
        self.stick.poll()
        now = time.ticks_ms()
        if port.wrote:
            # The console will not ask again before its next frame.
            port.wrote = False
            self.answers += 1
            self._answer_at = now
            self._since_gc += 1
            if self._since_gc >= GC_EVERY_ANSWERS:
                self.collect()
            elif time.ticks_diff(now, self._chores_at) >= BUSY_CHORES_MS:
                self.chores(now)
        elif (time.ticks_diff(now, self._chores_at) >= IDLE_CHORES_MS
              and time.ticks_diff(now, self._answer_at) >= 2 * IDLE_CHORES_MS):
            # Only once the console has stopped asking: a request that came
            # in the middle of these would go unanswered.
            self.chores(now)
            if time.ticks_diff(now, self._gc_at) >= GC_IDLE_MS:
                self.collect()
            if (self.network.address is None
                    and time.ticks_diff(now, self._retry_at) >= WIFI_RETRY_MS):
                self._retry_at = now
                self.join_wifi(3000)

    def start(self):
        config = load_config()
        label, tx, rx = board.detect(config.get("board"))
        tx = config.get("tx", tx)
        rx = config.get("rx", rx)
        self.screen.set(board=label, state="STARTING")
        self.screen.refresh(everything=True)
        # Open the UART before anything slow, so TX rests at mark.
        uart = board.open_link_uart(tx, rx, invert=config.get("invert", True))
        self.port = UartPort(uart)
        self.network = net.SocketNetwork()
        self.stick = Stick(self.port, self.network)
        print("Dr. Mario netplay %s on %s: TX G%d, RX G%d, %d baud"
              % (VERSION, label, tx, rx, baud()))
        self.ssid, self.password = uiflow_wifi()
        if not self.ssid:
            self.network.error = "No Wi-Fi saved. Use M5Burner."
        else:
            self.screen.set(wifi="joining " + self.ssid)
            self.screen.refresh(everything=True)
            if not self.join_wifi(20000):
                self.network.error = "could not join Wi-Fi; will retry"
        self.network.refresh()
        self.collect()
        try:
            gc.threshold(-1)
        except (AttributeError, TypeError) as error:
            print("gc threshold not set:", error)
        self.show_status()

    def run(self):
        try:
            self.start()
            while True:
                self.step()
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
