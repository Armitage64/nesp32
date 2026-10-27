"""Work the setup ROM as a person with a controller would, for the tests.

Buttons are pressed and let go a frame at a time. What is on the screen is
read from the nametable, by the rows apps/setup/tools/gen_screen.py lays out.
"""

import gen_screen as layout
import nesp_proto as p
from console import (PAD_A, PAD_B, PAD_DOWN, PAD_LEFT, PAD_RIGHT, PAD_SELECT, PAD_START,
                     PAD_UP)

STATE_STATUS, STATE_SCAN, STATE_LIST, STATE_KEYS = 0, 1, 2, 3
STATE_SEND, STATE_JOINING, STATE_FAILED, STATE_TEST = 4, 5, 6, 7
STATE_USB, STATE_KBD, STATE_KBD_LIST = 8, 9, 10
MENU_WIFI, MENU_TEST, MENU_USB, MENU_KBD, MENU_FLIP, MENU_QUIT = 0, 1, 2, 3, 4, 5
KBD_MENU_PAIR, KBD_MENU_FORGET, KBD_MENU_BACK = 0, 1, 2
LAYER_KEYS = layout.KEY_ROWS * layout.KEY_COLUMNS
SET_COL = 0                     # on the space bar's row, the set key (keys.inc)

__all__ = ["Setup", "PAD_A", "PAD_B", "PAD_DOWN", "PAD_LEFT", "PAD_RIGHT", "PAD_SELECT",
           "PAD_START", "PAD_UP"]


def find_key(char):
    """(layer, row, column) of the key that types a character."""
    for layer, rows in enumerate(layout.LAYERS):
        for row, keys in enumerate(rows):
            column = keys.find(char)
            if column >= 0 and char != " ":
                return layer, row, column
    raise ValueError("no key types %r" % char)


class Setup:
    """A console on the setup ROM, and a Stick."""

    def __init__(self, console, stick, port):
        self.c = console
        self.stick = stick
        self.port = port

    # --- what is on the screen ---------------------------------------------------

    @property
    def state(self):
        return self.c.byte("state")

    @property
    def heading(self):
        return self.c.line(layout.HEADING_ROW)

    @property
    def message(self):
        return self.c.line(layout.MESSAGE_ROW)

    def value(self, label):
        """The status screen's value for a label."""
        row = layout.BODY_ROW + layout.STATUS_LABELS.index(label)
        assert self.c.text(row, layout.LEFT, len(label)) == label
        return self.c.text(row, layout.VALUE_COLUMN, layout.VALUE_WIDTH).strip()

    def values(self):
        return {label: self.value(label) for label in layout.STATUS_LABELS}

    def kbd_value(self, label):
        """The keyboard screen's value for a label."""
        row = layout.BODY_ROW + layout.KBD_LABELS.index(label)
        assert self.c.text(row, layout.LEFT, len(label)) == label
        return self.c.text(row, layout.VALUE_COLUMN, layout.VALUE_WIDTH).strip()

    @property
    def kbd_item(self):
        """Which of the keyboard screen's menu items the arrow is at."""
        x, y, tile = self.c.sprite()
        assert x == 8 * layout.LEFT and self.tile_names()[tile] == "ARROW"
        return (y - 8 * layout.KBD_MENU_ROW) // 8

    def kbd_menu(self, item):
        """On the keyboard's screen: its menu's item, by its place (KBD_MENU_*)."""
        while self.kbd_item != item:
            self.press(PAD_DOWN if self.kbd_item < item else PAD_UP)
        self.press(PAD_A)

    @property
    def echo(self):
        """The keyboard screen's line of what was typed, with its cursor."""
        return self.c.text(layout.KBD_ECHO_ROW, layout.LEFT, layout.WIDTH).rstrip()

    def listed(self):
        """The list's lines as (name, locked, bars), bars 0 for a line that
        is not a network."""
        out = []
        for line in range(layout.LIST_ROWS):
            row = layout.LIST_ROW + line
            name = self.c.text(row, layout.LIST_COLUMN, layout.LIST_NAME).rstrip()
            lock, bars = (self.c.tiles(row, column, 1)[0]
                          for column in (layout.LIST_LOCK, layout.LIST_BARS))
            tiles = self.tile_names()
            out.append((name, tiles.get(lock) == "LOCK", int(tiles.get(bars, "BARS0")[4:])))
        return out

    def tile_names(self):
        screen = layout.build_screen()
        return {tile: name for name, tile in screen.named.items()}

    @property
    def arrow_line(self):
        """Which of the list's lines the arrow is at."""
        x, y, tile = self.c.sprite()
        assert x == 8 * layout.LEFT and self.tile_names()[tile] == "ARROW"
        return (y - 8 * layout.LIST_ROW) // 8

    @property
    def field(self):
        return self.c.text(layout.FIELD_ROW, layout.LEFT, layout.FIELD_WIDTH).rstrip()

    def test_value(self, label):
        """The link test's number for a label."""
        for row in range(layout.BODY_ROW, layout.BODY_ROW + 8):
            if self.c.text(row, layout.LEFT, len(label) + 1).rstrip() == label:
                return self.c.text(row, layout.TEST_VALUE_COLUMN, 16).strip()
        raise AssertionError("no line %r:\n%s" % (label, self.c.screen()))

    # --- the controller ----------------------------------------------------------

    def press(self, buttons):
        self.c.press(buttons, frames=1, release=1)

    def menu(self, item):
        """From the status screen: the menu's item, by its place (MENU_*)."""
        for _ in range(item):
            self.press(PAD_DOWN)
        self.press(PAD_A)

    def wait_for(self, state, frames=600):
        self.c.run_until(lambda: self.state == state, frames)
        self.c.run(4)               # and for what it stages first

    def wait_for_message(self, text, frames=600):
        self.c.run_until(lambda: self.message == text, frames)

    def settle(self, frames=40):
        """Long enough for a screen to finish drawing itself."""
        self.c.run(frames)

    # --- the keyboard ------------------------------------------------------------

    def type(self, text):
        for char in text:
            if char == " ":
                self._move_to_row(layout.KEY_ROWS)
                if self.c.byte("cur_col") == SET_COL:
                    self.press(PAD_RIGHT)       # from the set key to the space bar
            else:
                layer, row, column = find_key(char)
                while self.c.byte("keys_layer") // LAYER_KEYS != layer:
                    self.next_set()
                self._move_to_row(row)
                self._move_to_column(column)
            before = self.c.byte("keys_len")
            self.press(PAD_A)
            assert self.c.byte("keys_len") == before + 1, "%r was not typed" % char

    def next_set(self):
        """The set key, on the space bar's row: the next set of keys."""
        self._move_to_row(layout.KEY_ROWS)
        if self.c.byte("cur_col") != SET_COL:
            self.press(PAD_LEFT)
        self.press(PAD_A)

    def _move_to_row(self, row):
        while self.c.byte("cur_row") != row:
            self.press(PAD_DOWN if self.c.byte("cur_row") < row else PAD_UP)

    def _move_to_column(self, column):
        while self.c.byte("cur_col") != column:
            ahead = (column - self.c.byte("cur_col")) % layout.KEY_COLUMNS
            self.press(PAD_RIGHT if ahead <= layout.KEY_COLUMNS // 2 else PAD_LEFT)

    # --- whole errands -----------------------------------------------------------

    def scan(self, networks):
        """From the status screen: A, and the Stick finds these networks."""
        self.stick.scan_set(networks)
        self.press(PAD_A)
        self.c.run_until(lambda: self.stick.scan_state == p.NESP_SCAN_RUNNING, 120)
        self.c.run(20)
        self.stick.scan_finish()
        self.wait_for(STATE_LIST)
        self.settle()

    def choose(self, entry):
        """Move the arrow to an entry of the list and press A."""
        while self.c.byte("list_cur") != entry:
            self.press(PAD_DOWN if self.c.byte("list_cur") < entry else PAD_UP)
        self.press(PAD_A)
