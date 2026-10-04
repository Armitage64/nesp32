"""device.py off the Stick: its UART port and screen against stand-ins for
MicroPython's machine, M5 and time. This checks the calls it makes, not the
hardware, which only a Stick can."""

import sys
import time
import types

import pytest

from linktest.rates import CONTROL, baud


class FakeUart:
    INV_TX, INV_RX = 4, 8

    def __init__(self, uart_id, **settings):
        self.settings = dict(settings)
        self.inits = []
        self.written = b""
        self.incoming = b""

    def init(self, **settings):
        self.inits.append(settings)
        self.settings.update(settings)

    def write(self, data):
        self.written += bytes(data)

    def flush(self):
        pass

    def any(self):
        return len(self.incoming)

    def read(self, count=None):
        if not self.incoming:
            return None
        count = len(self.incoming) if count is None else count
        data, self.incoming = self.incoming[:count], self.incoming[count:]
        return data


class FakeLcd:
    FONTS = types.SimpleNamespace(Montserrat12=12, Montserrat14=14)

    def __init__(self):
        self.strings = []

    def drawString(self, text, x, y):
        self.strings.append((text, x, y))

    def __getattr__(self, name):    # the rest only paint
        return lambda *args: None


@pytest.fixture
def device(monkeypatch):
    clock = [0]

    def sleep_ms(duration):
        clock[0] += duration

    monkeypatch.setattr(time, "sleep_ms", sleep_ms, raising=False)
    monkeypatch.setattr(time, "ticks_ms", lambda: clock[0], raising=False)
    monkeypatch.setattr(time, "ticks_diff", lambda a, b: a - b, raising=False)
    monkeypatch.setitem(sys.modules, "machine", types.SimpleNamespace(UART=FakeUart))
    monkeypatch.setitem(sys.modules, "M5", types.SimpleNamespace(Lcd=FakeLcd()))
    monkeypatch.delitem(sys.modules, "linktest.device", raising=False)
    import linktest.device
    yield linktest.device
    del sys.modules["linktest.device"]


def test_the_port_opens_at_the_control_rate_inverted_with_two_stop_bits(device):
    port = device.UartPort(26, 36)
    settings = port.uart.settings
    assert (settings["baudrate"], settings["stop"], settings["tx"], settings["rx"]) == (
        baud(CONTROL), 2, 26, 36)
    assert settings["invert"] == FakeUart.INV_TX | FakeUart.INV_RX
    assert settings["rxbuf"] >= 256 and settings["txbuf"] >= 256
    assert device.UartPort(26, 36, invert=False).uart.settings["invert"] == 0


def test_a_rate_change_keeps_the_inversion_and_the_pins(device):
    port = device.UartPort(26, 36)
    port.set_baud(57735)
    assert port.uart.inits == [{"baudrate": 57735, "bits": 8, "parity": None, "stop": 2,
                                "timeout": 0, "invert": FakeUart.INV_TX | FakeUart.INV_RX}]
    port.set_baud(57735)            # no change, no init
    assert len(port.uart.inits) == 1


def test_write_waits_for_the_bytes_to_leave(device):
    port = device.UartPort(26, 36)
    before = port.ticks_ms()
    port.write(bytes(256))
    assert port.uart.written == bytes(256)
    assert port.ticks_ms() - before >= 256 * 11 * 1000 // baud(CONTROL)


def test_read_returns_early_with_all_it_asked_for_and_late_with_less(device):
    port = device.UartPort(26, 36)
    port.uart.incoming = b"abcdefgh"
    before = port.ticks_ms()
    assert port.read(7, 100) == b"abcdefg"
    assert port.ticks_ms() == before
    assert port.read(7, 100) == b"h"
    assert port.ticks_ms() - before >= 100
    port.uart.incoming = b"junk"
    port.discard()
    assert port.read(1, 5) == b""


def test_the_screen_paints_a_row_when_its_text_changes(device):
    screen = device.Screen()
    lcd = screen.lcd
    screen.set(state="RX RAMP 57735 BAUD", rx="")
    assert [text for text, _, _ in lcd.strings] == ["STATE", "RX RAMP 57735 BAUD"]
    screen.set(state="RX RAMP 57735 BAUD")
    assert len(lcd.strings) == 2
    screen.set(error="ValueError: no")          # a row with no label starts at the left
    assert lcd.strings[-1][:2] == ("ValueError: no", 4)
