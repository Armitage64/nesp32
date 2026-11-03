"""The HTTPS sample on a simulated console, with a nesp32's firmware on the
line and the test as the web site: what the screen says of a fetch, and
the body wrapped to it a screenful at a time."""

import os

import nesp_proto as p
import pytest
from console import PAD_A, PAD_DOWN, PAD_SELECT, PAD_UP, Console
from nesp import Stick
from wire import link

README_URL = "https://raw.githubusercontent.com/Armitage64/nesp32/main/README.md"
MISSING_URL = "https://raw.githubusercontent.com/Armitage64/nesp32/main/NO-SUCH-FILE"
README = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "README.md")
COLUMNS = 28
STATE_ROW, STATUS_ROW, LENGTH_ROW, HELD_ROW, TIME_ROW, TYPE_ROW = range(8, 14)
BODY_ROW, BODY_ROWS = 15, 12


def wrap(body):
    """The body as the ROM lays it out: (rows, the offset each starts at).
    A line ends at LF, or at the last space before it is too long."""
    rows, starts = [], []
    line, start = "", 0
    for offset, byte in enumerate(body):
        char = chr(byte)
        if char == "\r":
            continue
        if char == "\n":
            rows.append(line), starts.append(start)
            line, start = "", offset + 1
            continue
        if char == "\t":
            char = " "
        if not " " <= char < "\x7f":
            char = "?"
        if len(line) < COLUMNS:
            line += char
        elif char == " ":
            rows.append(line), starts.append(start)
            line, start = "", offset + 1
        elif " " in line:
            space = line.rindex(" ")
            rows.append(line[:space]), starts.append(start)
            line, start = line[space + 1:] + char, offset - (COLUMNS - space - 1)
        else:
            rows.append(line), starts.append(start)
            line, start = char, offset
    rows.append(line), starts.append(start)
    return rows, starts


class Table:
    """A console on the ROM, with its nesp32 on the line."""

    def __init__(self, rom):
        self.console = Console(*rom)
        self.stick, _ = link(self.console, Stick)
        self.stick.set_wifi(p.NESP_WIFI_JOINED, rssi=-50, address=(192, 168, 1, 23))

    def run(self, frames, pad=0):
        self.console.run(frames, pad=pad)

    def tap(self, pad):
        self.run(2, pad)
        self.run(2)

    def until(self, condition, frames=300):
        self.console.run_until(condition, frames)

    def row(self, number):
        return self.console.text(number, 2, COLUMNS).rstrip()

    def body(self):
        return [self.row(BODY_ROW + index) for index in range(BODY_ROWS)]


@pytest.fixture
def table(rom):
    table = Table(rom)
    table.until(lambda: table.stick.fetching)
    return table


def test_it_sends_the_address_and_fetches_it(table):
    assert table.stick.fetch_url == README_URL
    table.until(lambda: table.row(STATE_ROW) == "STATE   ASKING")
    assert [table.row(row) for row in (4, 5, 6)] == [
        README_URL[:28], README_URL[28:56], README_URL[56:]]


def test_a_200_and_the_start_of_its_body(table):
    stick = table.stick
    with open(README, "rb") as handle:
        body = handle.read()
    stick.fetch_head(200, b"text/plain; charset=utf-8", len(body))
    for at in range(0, len(body), 1024):
        if not stick.fetch_body(body[at:at + 1024]):
            break
    stick.fetch_done()
    table.until(lambda: table.row(STATE_ROW) == "STATE   DONE")
    rows, starts = wrap(body[:p.NESP_HTTP_KEEP])
    table.until(lambda: table.body() == rows[:BODY_ROWS])
    assert table.row(STATUS_ROW) == "STATUS  200"
    assert table.row(LENGTH_ROW) == "LENGTH  %d BYTES" % len(body)
    assert table.row(HELD_ROW) == "HELD    %d BYTES" % p.NESP_HTTP_KEEP
    assert table.row(TYPE_ROW) == "TYPE    text/plain; charset="
    assert table.row(TIME_ROW).startswith("TIME    ") and table.row(TIME_ROW).endswith(" MS")
    assert rows[0] == "# NESP32"

    table.tap(PAD_DOWN)                             # the next screenful
    more, _ = wrap(body[starts[BODY_ROWS]:p.NESP_HTTP_KEEP])
    table.until(lambda: table.body() == more[:BODY_ROWS])
    table.tap(PAD_UP)                               # and the first again
    table.until(lambda: table.body() == rows[:BODY_ROWS])


def test_select_fetches_the_other_address_and_a_404_is_shown(table):
    stick = table.stick
    table.run(30)
    table.tap(PAD_SELECT)
    table.until(lambda: stick.fetch_url == MISSING_URL)
    stick.fetch_head(404, b"text/plain; charset=utf-8", 14)
    stick.fetch_body(b"404: Not Found")
    stick.fetch_done()
    table.until(lambda: table.row(STATE_ROW) == "STATE   DONE")
    table.until(lambda: table.body() == ["404: Not Found"] + [""] * (BODY_ROWS - 1))
    assert table.row(STATUS_ROW) == "STATUS  404"
    assert table.row(LENGTH_ROW) == "LENGTH  14 BYTES"


def test_a_nesp32_that_joins_its_network_later_is_asked_again(rom):
    table = Table(rom)
    stick = table.stick
    stick.set_wifi(p.NESP_WIFI_JOINING)             # switched on, and not on it yet
    table.until(lambda: table.row(STATE_ROW) == "STATE   NO WIFI")
    table.run(120)
    assert stick.fetches == 0
    stick.set_wifi(p.NESP_WIFI_JOINED, rssi=-50, address=(192, 168, 1, 23))
    table.until(lambda: stick.fetching, frames=90)
    assert stick.fetch_url == README_URL
    table.until(lambda: table.row(STATE_ROW) == "STATE   ASKING")


def test_a_fetch_that_fails_says_why_and_a_can_ask_again(table):
    stick = table.stick
    stick.fetch_done(ok=False, why=b"THE SITE DID NOT ANSWER")
    table.until(lambda: table.row(STATE_ROW) == "STATE   FAILED")
    table.until(lambda: table.row(TYPE_ROW) == "WHY     THE SITE DID NOT ANS")
    fetches = stick.fetches
    table.tap(PAD_A)
    table.until(lambda: stick.fetches == fetches + 1)
    table.until(lambda: table.row(STATE_ROW) == "STATE   ASKING")
