"""The Stick's main loop, with its hardware and the network faked.

device.py, board.py, ui.py and net.py only run on a Stick. This runs them on
a desktop against stand-ins for UIFlow's modules, far enough to catch what
a first run on hardware should not have to: a search over the UART is
fetched, laid out and served, and failures reach the console as messages.
"""

import os
import sys
import time
import types

import pytest
from conftest import FIXTURES

from neswiki import proto
from neswiki.linkrate import COLUMNS, REPLY_SIZE, baud


class Anything:
    """An object that takes any call, for the LCD."""

    def __getattr__(self, name):
        return Anything()

    def __call__(self, *args, **kwargs):
        return 0


class Button:
    def __init__(self):
        self.held = False

    def wasPressed(self):
        return False

    def pressedFor(self, duration):
        return self.held


class FakeUART:
    INV_TX, INV_RX = 4, 8
    last = None

    def __init__(self, port, **options):
        self.options = options
        self.incoming = []
        self.written = []
        FakeUART.last = self

    def any(self):
        return len(self.incoming[0]) if self.incoming else 0

    def readinto(self, buffer):
        data = self.incoming.pop(0)
        buffer[:len(data)] = data
        return len(data)

    def read(self):
        raise AssertionError("uart.read() allocates on every call: use any() and readinto()")

    def write(self, data):
        self.written.append(bytes(data))

    def replies(self):
        data = b"".join(self.written)
        assert len(data) % REPLY_SIZE == 0
        out = [proto.parse_reply(data[start:start + REPLY_SIZE])
               for start in range(0, len(data), REPLY_SIZE)]
        assert None not in out
        return out


class FakeStream:
    def __init__(self, body, on_read=None):
        self.body = body
        self.on_read = on_read
        self.closed = False

    def read(self, count):
        if self.on_read is not None:
            self.on_read()
        data, self.body = self.body[:count], self.body[count:]
        return data

    def close(self):
        self.closed = True


@pytest.fixture
def stick(monkeypatch):
    """The device module on stand-ins, and the things to steer it by."""
    m5 = types.ModuleType("M5")
    m5.Lcd = Anything()
    m5.BtnA, m5.BtnB = Button(), Button()
    m5.Power = Anything()
    m5.powered_off = []
    m5.Power.powerOff = lambda: m5.powered_off.append(True)
    m5.BOARD = types.SimpleNamespace(M5StickCPlus2=5, M5StickS3=6)
    m5.getBoard = lambda: 5
    m5.begin = m5.update = lambda: None
    machine = types.ModuleType("machine")
    machine.UART = FakeUART
    esp32 = types.ModuleType("esp32")
    saved = {"ssid0": "home", "pswd0": "secret"}

    class NVS:
        def __init__(self, name):
            assert name == "uiflow"

        def get_str(self, key):
            if key not in saved:
                raise OSError("not found")
            return saved[key]
    esp32.NVS = NVS
    network = types.ModuleType("network")
    for name, module in (("M5", m5), ("machine", machine), ("esp32", esp32), ("network", network)):
        monkeypatch.setitem(sys.modules, name, module)
    clock = [1000]

    def ticks_ms():
        clock[0] += 1               # time passes, so a loop that waits ends
        return clock[0]
    monkeypatch.setattr(time, "ticks_ms", ticks_ms, raising=False)
    monkeypatch.setattr(time, "ticks_us", lambda: clock[0] * 1000, raising=False)
    monkeypatch.setattr(time, "ticks_diff", lambda a, b: a - b, raising=False)
    monkeypatch.setattr(time, "ticks_add", lambda a, b: a + b, raising=False)
    monkeypatch.setattr(time, "sleep_ms", lambda ms: None, raising=False)
    monkeypatch.setattr(sys, "print_exception", lambda error: None, raising=False)
    import gc
    monkeypatch.setattr(gc, "mem_free", lambda: 1000000, raising=False)
    monkeypatch.setattr(gc, "mem_alloc", lambda: 300000, raising=False)
    monkeypatch.setattr(gc, "threshold", lambda *args: 0, raising=False)
    forget_hardware_modules()
    from neswiki import device, net
    joined = [True]
    monkeypatch.setattr(net, "connect", lambda *args, **kwargs: joined[0])
    monkeypatch.setattr(net, "is_connected", lambda: joined[0])
    monkeypatch.setattr(os, "stat", os.stat)
    monkeypatch.setattr(device, "CONFIG_PATH", "/nonexistent/config.json")
    yield types.SimpleNamespace(device=device, net=net, m5=m5, clock=clock, joined=joined,
                                saved=saved)
    forget_hardware_modules()


def forget_hardware_modules():
    """The modules that hold on to M5 and the rest: each test's stand-ins
    must be the ones they import."""
    import neswiki
    for name in ("device", "board", "ui", "net"):
        sys.modules.pop("neswiki." + name, None)
        if hasattr(neswiki, name):
            delattr(neswiki, name)


def recorded():
    with open(os.path.join(FIXTURES, "nes_trimmed.json"), "rb") as handle:
        return handle.read()


def start(stick):
    made = stick.device.Device()
    made.start()
    return made, FakeUART.last


def finish(stick, made, uart, limit=200):
    """Turn the loop until the fetch is over, reading as the console would:
    the Stick only fetches a couple of pages ahead of what has been read."""
    for _ in range(limit):
        if not made.fetch.active:
            return
        reading = [proto.line_request(made.article.count - 1)] if made.article.count else []
        uart.incoming.extend(reading)
        turn(stick, made, uart)
    raise AssertionError("the fetch did not end")


def turn(stick, made, uart, data=None):
    if data is not None:
        uart.incoming.append(data)
    stick.clock[0] += 60
    made.step()


def test_the_uart_is_opened_at_the_links_rate_with_the_boards_pins(stick):
    made, uart = start(stick)
    assert uart.options["baudrate"] == baud() == 85227
    assert (uart.options["tx"], uart.options["rx"]) == (26, 36)    # a StickC Plus2
    assert uart.options["stop"] == 2 and uart.options["invert"] == 12
    assert made.server.online and made.article.capacity == 256 * 1024 // COLUMNS


def test_a_search_is_fetched_and_served(stick, monkeypatch):
    made, uart = start(stick)
    search = proto.search_request(1, b"Nintendo Entertainment System")
    asked = []
    polls = []

    def open_search(query):
        asked.append(query)
        # The console asks how it is going while the article arrives.
        return FakeStream(recorded(), on_read=lambda: (uart.incoming.append(search),
                                                       polls.append(1)))
    monkeypatch.setattr(stick.net, "open_search", open_search)
    turn(stick, made, uart, search)
    assert asked == ["Nintendo Entertainment System"]
    finish(stick, made, uart)
    replies = uart.replies()
    assert replies[0][:3] == (proto.FETCHING, 0xFF01, 0)
    # Fetching, and then the article on offer while the rest arrives.
    replies = [reply for reply in replies if reply[1] >> 8 == 0xFF]    # the search's own
    states = [reply[0] for reply in replies]
    assert states[0] == proto.FETCHING and states[-1] == proto.READY | proto.MORE
    assert states == sorted(states) and set(states) == {proto.FETCHING, proto.READY | proto.MORE}
    totals = [reply[2] for reply in replies]
    assert totals == sorted(totals) and totals[-1] >= 28
    assert made.article.title == b"Nintendo Entertainment System"
    uart.incoming.clear()           # the asking that came after the last piece
    turn(stick, made, uart, search)
    state, line, total, _ = uart.replies()[-1]
    assert (state, line, total) == (proto.READY, 0xFF01, made.article.count) and total > 50
    turn(stick, made, uart, proto.line_request(3))
    assert uart.replies()[-1] == (proto.READY, 3, total, b"The Nintendo Entertainment  ")
    assert asked == ["Nintendo Entertainment System"]


def test_a_search_that_finds_nothing(stick, monkeypatch):
    made, uart = start(stick)
    stream = FakeStream(b'{"batchcomplete":true}')
    monkeypatch.setattr(stick.net, "open_search", lambda query: stream)
    turn(stick, made, uart, proto.search_request(1, b"zzqqxx"))
    finish(stick, made, uart)
    turn(stick, made, uart, proto.search_request(1, b"zzqqxx"))
    assert uart.replies()[-1][0] == proto.NOT_FOUND
    assert stream.closed and made.article.count == 0


def test_a_fetch_that_fails_tells_the_console_why(stick, monkeypatch):
    made, uart = start(stick)

    def open_search(query):
        raise OSError("HTTP 503")
    monkeypatch.setattr(stick.net, "open_search", open_search)
    turn(stick, made, uart, proto.search_request(1, b"x"))
    turn(stick, made, uart, proto.search_request(1, b"x"))
    assert uart.replies()[-1] == (proto.ERROR, 0xFF01, 0, b"          HTTP 503          ")
    # The loop goes on, and the next search is tried.
    monkeypatch.setattr(stick.net, "open_search", lambda query: FakeStream(recorded()))
    turn(stick, made, uart, proto.search_request(2, b"x"))
    finish(stick, made, uart)
    turn(stick, made, uart, proto.search_request(2, b"x"))
    assert uart.replies()[-1][0] == proto.READY


def test_without_wifi_a_search_is_answered_at_once(stick, monkeypatch):
    stick.joined[0] = False
    made, uart = start(stick)
    monkeypatch.setattr(stick.net, "open_search", lambda query: pytest.fail("fetched"))
    turn(stick, made, uart, proto.search_request(1, b"x"))
    assert uart.replies()[-1][0] == proto.NO_WIFI
    # It keeps trying to join, and the search after it does goes through.
    stick.joined[0] = True
    stick.clock[0] += 20000
    turn(stick, made, uart)
    assert made.server.online
    monkeypatch.setattr(stick.net, "open_search", lambda query: FakeStream(recorded()))
    turn(stick, made, uart, proto.search_request(2, b"x"))
    assert uart.replies()[-1][0] == proto.FETCHING


def test_no_saved_network_is_not_fatal(stick):
    stick.saved.clear()
    stick.joined[0] = False
    made, uart = start(stick)
    assert not made.server.online
    turn(stick, made, uart, proto.search_request(1, b"x"))
    assert uart.replies()[-1][0] == proto.NO_WIFI


def test_holding_b_powers_off(stick):
    made = stick.device.Device()
    stick.m5.BtnB.held = True
    stick.clock[0] += 100
    made.run()
    assert stick.m5.powered_off == [True]
