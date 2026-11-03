"""The keyboard sample on a simulated console, with a nesp32's firmware on
the line and the test as the Bluetooth keyboard: what the screen says of
the keyboard, and what is typed on it, in the field."""

import nesp_proto as p
import pytest
from console import Console
from nesp import Stick
from wire import link

KBD = p.NESP_SVC_KBD
ENTER, BACKSPACE, ESCAPE = p.NESP_KEY_ENTER, p.NESP_KEY_BACKSPACE, p.NESP_KEY_ESCAPE
COLUMNS = 28
PAIRED_ROW, STATE_ROW, NAME_ROW = 4, 5, 6
FIELD_ROW, FIELD_ROWS = 12, 6


class Table:
    """A console on the ROM, with its nesp32 on the line. `drop` sees every
    reply on its way to the console, and returns True to lose it."""

    def __init__(self, rom, drop=None):
        self.console = Console(*rom)
        self.drop = drop
        self.stick, _ = link(self.console, Stick, to_console=self._deliver)

    def _deliver(self, data):
        return None if self.drop is not None and self.drop(data) else data

    def run(self, frames):
        self.console.run(frames)

    def until(self, condition, frames=300):
        self.console.run_until(condition, frames)

    def row(self, number, column=2):
        return self.console.text(number, column, 32 - column).rstrip()

    def field(self):
        return [self.row(FIELD_ROW + index) for index in range(FIELD_ROWS)]

    def cursor(self):
        """(column, row) of the cursor in the field, or None while it blinks
        off. Its sprite's tile is the font's underscore."""
        for _ in range(40):
            sprite = self.console.sprite(0)
            if sprite is not None:
                x, y, tile = sprite
                assert tile == ord("_")
                return x // 8 - 2, y // 8 - FIELD_ROW
            self.run(1)
        return None

    def connect(self, name=b"MX KEYS MINI"):
        self.stick.kbd_paired(name)
        self.stick.kbd_state = p.NESP_KEYBOARD_CONNECTED
        self.until(lambda: self.row(STATE_ROW) == "STATE     CONNECTED"
                   and self.row(NAME_ROW) == "NAME      " + name.decode()[:18])

    def type(self, keys):
        self.stick.kbd_type(keys)
        self.run(20)


@pytest.fixture
def table(rom):
    table = Table(rom)
    table.until(lambda: table.stick.active(KBD))
    return table


def test_with_no_keyboard_paired(table):
    table.until(lambda: table.row(STATE_ROW) == "STATE     NOT PAIRED")
    assert table.row(PAIRED_ROW) == "PAIRED    NO"
    assert table.row(NAME_ROW) == "NAME"
    assert table.stick.kbd_on                       # the hello asked for KBD


def test_a_keyboard_paired_and_connected_is_named(table):
    table.connect()
    assert table.row(PAIRED_ROW) == "PAIRED    YES"
    assert table.row(NAME_ROW) == "NAME      MX KEYS MINI"
    table.stick.kbd_state = p.NESP_KEYBOARD_WAITING     # asleep: a key wakes it
    table.until(lambda: table.row(STATE_ROW) == "STATE     NOT CONNECTED")
    assert table.row(PAIRED_ROW) == "PAIRED    YES"


def test_a_long_name_is_cut_to_its_line(table):
    table.connect(b"Logitech MX Keys S Plus")      # 23 characters, of 24
    assert table.row(NAME_ROW) == "NAME      Logitech MX Keys S"


def test_what_is_typed_goes_in_the_field(table):
    table.connect()
    assert table.cursor() == (0, 0)
    table.type(b"Hello, NES!" + bytes((ENTER,)) + b"Second line")
    assert table.field()[:3] == ["Hello, NES!", "Second line", ""]
    assert table.cursor() == (11, 1)


def test_a_long_line_goes_on_on_the_next(table):
    table.connect()
    table.type(b"x" * 16)
    table.type(b"y" * 16)
    assert table.field()[:2] == ["x" * 16 + "y" * 12, "y" * 4]
    assert table.cursor() == (4, 1)


def test_backspace_deletes_and_goes_back_over_a_line_end(table):
    table.connect()
    table.type(b"abc" + bytes((ENTER,)) + b"de")
    table.type(bytes((BACKSPACE,)) * 3)
    assert table.field()[:2] == ["abc", ""]
    assert table.cursor() == (3, 0)                 # at the end of the line before
    table.type(bytes((BACKSPACE,)) + b"Z")
    assert table.field()[:2] == ["abZ", ""]


def test_escape_clears_the_field(table):
    table.connect()
    table.type(b"one" + bytes((ENTER,)) + b"two")
    table.type(bytes((ESCAPE,)) + b"new")
    assert table.field() == ["new"] + [""] * (FIELD_ROWS - 1)
    assert table.cursor() == (3, 0)


def test_a_full_field_takes_no_more(table):
    table.connect()
    for _ in range(-(-FIELD_ROWS * COLUMNS // 16)):     # 176 for its 168
        table.type(b"abcdefghijklmnop")
    table.type(b"more")
    assert table.field() == [("abcdefghijklmnop" * 11)[row * COLUMNS:][:COLUMNS]
                             for row in range(FIELD_ROWS)]
    assert table.cursor() is None


def test_a_lost_reply_loses_none_of_what_was_typed(rom):
    """The first KEYS reply with keys in it never reaches the console. It
    asks the same request again, and the nesp32 answers with the reply it
    held."""
    lost = []

    def drop(data):
        if not lost and data[1] == KBD and data[4] > 1 and data[5] == data[4] - 1:
            lost.append(data)
            return True
        return False

    table = Table(rom, drop)
    table.until(lambda: table.stick.active(KBD))
    table.connect()
    table.type(b"nothing lost")
    assert lost, "no reply was dropped"
    assert table.field()[0] == "nothing lost"
    assert table.stick.repeats >= 1                 # answered from what it held


def test_a_nesp32_with_no_bluetooth(rom):
    table = Table(rom)
    table.stick.kbd_absent()
    table.until(lambda: table.row(STATE_ROW) == "STATE     NO BLUETOOTH")
    assert table.row(PAIRED_ROW) == "PAIRED    NO"
