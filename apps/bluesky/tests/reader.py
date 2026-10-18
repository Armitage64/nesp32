"""The Bluesky ROM on py65, joined by the serial line model to a nesp32,
with the test as Bluesky.

The console and the line are nesp32's own tests' (its tests/console.py and
tests/wire.py), and the nesp32's end is its firmware's code, built for this
computer. That console lets the PPU be written to only inside an NMI while
the picture is on, and notes how far into vblank each NMI's last write
came.

Bluesky is here: a fetch the nesp32 begins is answered by `serve`, from
what the test says each handle has.
"""

import calendar
from urllib.parse import parse_qs, urlparse

import gen_screen as layout
import nesp
import nesp_proto as p
from console import (PAD_A, PAD_B, PAD_DOWN, PAD_LEFT, PAD_RIGHT, PAD_SELECT, PAD_START,
                     PAD_UP, VBLANK_CYCLES, Console)
from wire import link

__all__ = ["Reader", "PAD_A", "PAD_B", "PAD_DOWN", "PAD_LEFT", "PAD_RIGHT", "PAD_SELECT",
           "PAD_START", "PAD_UP", "NOT_FOUND", "NOW", "cards"]

VIEW_SPLASH, VIEW_LIST, VIEW_FORM, VIEW_POST = range(4)
NOT_FOUND = object()                # Bluesky's answer to a handle no one has
NOW = calendar.timegm((2026, 10, 18, 10, 0, 0))


def her_char(tile):
    """A tile of ConnectedNES's font as its character."""
    if tile == layout.SPLASH_BLANK:
        return " "
    return chr(int("{:08b}".format(tile)[::-1], 2))


def cards(body, handle=b"bsky.app"):
    """Every post's lines, as a nesp32 that is sent `body` lays them out:
    the firmware's own code, on a Stick of its own."""
    stick = nesp.Stick()
    stick.set_time(NOW)
    stick.set_wifi(p.NESP_WIFI_JOINED)
    assert stick.hello(services=[p.NESP_SVC_BSKY]).ok
    reply = stick.ask(p.NESP_SVC_BSKY, p.NESP_BSKY_FEED, b"\x01" + handle)
    assert reply.ok
    stick.fetch_body(body)
    stick.fetch_done(True)
    count = stick.ask(p.NESP_SVC_BSKY, p.NESP_BSKY_FEED, b"\x01" + handle).payload[2]
    out = []
    for post in range(count):
        lines = []
        for row in range(p.NESP_BSKY_ROWS):
            reply = stick.ask(p.NESP_SVC_BSKY, p.NESP_BSKY_LINE, bytes((post, row)))
            lines.append(reply.payload[4:])
        out.append(lines)
    return out


class Reader:
    """A console on the ROM, and a nesp32 on a network unless wifi says
    otherwise. kept is the favorites the nesp32 has from before it was
    switched on (as nesp.Stick.favorites gives them). feeds is what Bluesky
    sends for a handle, as bytes, a (False, words) for a fetch that fails,
    or NOT_FOUND; default is for any other."""

    def __init__(self, rom_path, labels_path, feeds=None, default=None,
                 wifi=p.NESP_WIFI_JOINED, kept=None, attached=True, **port_options):
        self.c = Console(rom_path, labels_path)
        self.feeds, self.default = dict(feeds or {}), default
        self.stick = self.port = None
        self.served = []            # the handle of every fetch answered
        self.hold = False           # the fetches wait to be served
        if attached:
            self.plug_in(wifi, kept, **port_options)

    def plug_in(self, wifi=p.NESP_WIFI_JOINED, kept=None, **port_options):
        """A nesp32 on the port: a new one, which knows nothing of the
        console."""
        self.stick, self.port = link(self.c, nesp.Stick, **port_options)
        self.stick.set_wifi(wifi, address=(10, 0, 0, 2))
        self.stick.set_time(NOW)
        self.stick.favorites = kept

    # --- Bluesky -----------------------------------------------------------------

    def serve(self):
        """Answer the fetch the nesp32 has under way."""
        assert self.stick.fetching
        query = parse_qs(urlparse(self.stick.fetch_url).query)
        handle = query["actor"][0]
        self.served.append(handle)
        reply = self.feeds.get(handle, self.default)
        if reply is NOT_FOUND:
            self.stick.fetch_done(False, b"THE SITE SAID 400")
        elif isinstance(reply, tuple):
            self.stick.fetch_done(*reply)
        else:
            self.stick.fetch_body(reply)
            self.stick.fetch_done(True)

    def run(self, frames=1, pad=None):
        """Run some frames, with Bluesky answering as soon as asked."""
        for _ in range(frames):
            self.c.run(1, pad=pad)
            if self.stick is not None and self.stick.fetching and not self.hold:
                self.serve()

    def run_until(self, condition, frames=600):
        for count in range(frames):
            if condition():
                return count
            self.run(1)
        raise AssertionError("still waiting after %d frames:\n%s" % (frames, self.c.screen()))

    # --- the controller ----------------------------------------------------------

    def press(self, buttons):
        self.run(1, pad=buttons)
        self.run(1, pad=0)

    def type(self, handle):
        """Set the form's letters to a handle, from wherever its mark is."""
        letters = layout.LETTERS
        for index in range(layout.HANDLE_MAX):
            want = letters.index(handle[index]) if index < len(handle) else 0
            while self.c.byte("form_cursor") != index:
                self.press(PAD_RIGHT)
            there = self.c.byte("form_at", index)
            ahead = (want - there) % len(letters)
            for _ in range(ahead if ahead <= len(letters) // 2 else len(letters) - ahead):
                self.press(PAD_UP if ahead <= len(letters) // 2 else PAD_DOWN)
        self.settle()
        assert self.typed == handle

    # --- what is on the screen ---------------------------------------------------

    @property
    def view(self):
        return self.c.byte("view")

    @property
    def splash_status(self):
        row = self.c.tiles(layout.SPLASH_STATUS_ROW, layout.SPLASH_COLUMN,
                           layout.SPLASH_STATUS_WIDTH)
        return "".join(her_char(tile) for tile in row).strip()

    @property
    def status(self):
        return self.c.line(layout.STATUS_ROW)

    @property
    def foot(self):
        return self.c.line(layout.FOOT_ROW)

    def row(self, number):
        """A row of the middle of the screen, as its tiles."""
        return self.c.tiles(layout.BODY_ROW + number, layout.LEFT, layout.COLUMNS)

    def rows(self):
        return [self.row(number) for number in range(layout.POST_ROWS)]

    @property
    def arrow(self):
        """The favorite the arrow is at, by its row of the middle; None if
        it is not on the picture."""
        sprite = self.c.sprite()
        if sprite is None or sprite[2] != layout.ARROW_TILE:
            return None
        x, y, _ = sprite
        assert x == 8 * layout.ARROW_COLUMN and y % 8 == 0
        return y // 8 - layout.BODY_ROW

    @property
    def typed(self):
        row = self.row(layout.FORM_ROW).decode("ascii")
        assert row[0] == "@"
        return row[1:].rstrip()

    def painted(self):
        return (self.c.byte("paint_at") == self.c.byte("paint_end")
                and not self.c.byte("row_dirty") and not self.c.byte("status_dirty"))

    def settle(self, frames=600):
        self.run_until(self.painted, frames)

    def splash_is_up(self, frames=600):
        self.run_until(lambda: self.view == VIEW_SPLASH and self.c.byte("greeted")
                       and self.splash_status == "Press Start", frames)

    def list_is_up(self):
        """The favorites, whole: their handles."""
        self.run_until(lambda: self.view == VIEW_LIST and not self.c.byte("fav_load")
                       and self.painted())
        rows = self.rows()
        assert rows == layout.list_rows([row[1:].decode().rstrip() for row in
                                         rows[layout.LIST_ROW:layout.LIST_ROW
                                              + self.c.byte("fav_count")]])
        assert self.foot == layout.FOOT_LIST
        return [row[1:].decode().rstrip()
                for row in rows[layout.LIST_ROW:layout.LIST_ROW + self.c.byte("fav_count")]]

    def go(self):
        """From power-on to the favorites."""
        self.splash_is_up()
        self.press(PAD_START)
        return self.list_is_up()

    def post_is_up(self, frames=600):
        """A post, whole: its lines."""
        self.run_until(lambda: self.view == VIEW_POST
                       and self.c.byte("row_next") == layout.POST_ROWS and self.painted(),
                       frames)
        assert self.foot == layout.FOOT_POST
        assert self.c.sprite() is None
        return self.rows()

    # --- what the console did ----------------------------------------------------

    def requests(self):
        """Every request the nesp32's UART heard, as (service, op, payload)."""
        heard = b"".join(self.port.received)
        out = []
        at = 0
        while at + p.NESP_OVERHEAD <= len(heard):
            total = p.NESP_OVERHEAD + heard[at + 4]
            frame = heard[at:at + total]
            if (heard[at] == p.NESP_REQUEST_MARKER and len(frame) == total
                    and nesp.checks(frame[1:-2]) == frame[-2:]):
                out.append((frame[1], frame[2], frame[5:-2]))
                at += total
            else:
                at += 1
        return out

    def asked(self, op):
        return [payload for service, asked, payload in self.requests()
                if service == p.NESP_SVC_BSKY and asked == op]

    def latest_write(self):
        """How far into vblank the latest of any NMI's PPU writes came."""
        return max(frame.last_write for frame in self.c.frames)

    def writes_were_in_time(self):
        assert 0 < self.latest_write() < VBLANK_CYCLES
