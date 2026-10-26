"""The Weather ROM on py65, joined by the serial line model to a nesp32,
with the test as the Internet.

The console and the line are nesp32's own tests' (its tests/console.py and
tests/wire.py), and the nesp32's end is its firmware's code, built for this
computer. That console lets the PPU be written to only inside an NMI once
the picture is on, and notes how far into vblank each NMI's last write
came.

The two sites are here: a fetch the nesp32 begins is answered by `serve`,
from what the test says each is to send.
"""

import gen_screen as layout
import nesp
import nesp_proto as p
from console import (PAD_A, PAD_B, PAD_DOWN, PAD_LEFT, PAD_RIGHT, PAD_SELECT, PAD_START,
                     PAD_UP, VBLANK_CYCLES, Console)
from wire import link

__all__ = ["Forecast", "PAD_A", "PAD_B", "PAD_DOWN", "PAD_LEFT", "PAD_RIGHT", "PAD_SELECT",
           "PAD_START", "PAD_UP", "KEPT", "NOT_FOUND"]

VIEW_FORM, VIEW_REPORT = 0, 1
NOT_FOUND = object()                # Zippopotam's answer to a zip code there is none of
# What a nesp32 keeps of 90210 once it has found it.
KEPT = (b"90210", 34090100, -118406500, b"BEVERLY HILLS, CA")


class Forecast:
    """A console on the ROM, and a nesp32 on a network unless wifi says
    otherwise. kept is the zip code the nesp32 has from before it was
    switched on (as nesp.Stick.zip gives one). where and weather are what
    the two sites send; either may be a (False, words) for a fetch that
    fails, and where may be NOT_FOUND."""

    def __init__(self, rom_path, labels_path, where=None, weather=None,
                 wifi=p.NESP_WIFI_JOINED, kept=None, attached=True, **port_options):
        self.c = Console(rom_path, labels_path)
        self.where, self.weather = where, weather
        self.stick = self.port = None
        self.served = []            # the address of every fetch answered
        self.clock = 0.0            # milliseconds the nesp32's clock is ahead of the console's
        if attached:
            self.plug_in(wifi, kept, **port_options)

    def plug_in(self, wifi=p.NESP_WIFI_JOINED, kept=None, **port_options):
        """A nesp32 on the port: a new one, which knows nothing of the
        console."""
        self.stick, self.port = link(self.c, nesp.Stick, **port_options)
        now_ms = self.port.now_ms
        self.port.now_ms = lambda: now_ms() + self.clock
        self.stick.set_wifi(wifi, address=(10, 0, 0, 2))
        self.stick.zip = kept

    # --- the Internet ------------------------------------------------------------

    def serve(self):
        """Answer the fetch the nesp32 has under way."""
        assert self.stick.fetching
        url = self.stick.fetch_url
        self.served.append(url)
        reply = self.where if "zippopotam" in url else self.weather
        if reply is NOT_FOUND:
            self.stick.fetch_done(False, b"THE SITE SAID 404")
        elif isinstance(reply, tuple):
            self.stick.fetch_done(*reply)
        else:
            assert self.stick.fetch_body(reply)
            self.stick.fetch_done(True)

    def run(self, frames=1, pad=None):
        """Run some frames, with the sites answering as soon as asked."""
        for _ in range(frames):
            self.c.run(1, pad=pad)
            if self.stick is not None and self.stick.fetching:
                self.serve()

    def run_until(self, condition, frames=600):
        for count in range(frames):
            if condition():
                return count
            self.run(1)
        raise AssertionError("still waiting after %d frames:\n%s" % (frames, self.c.screen()))

    def later(self, ms):
        """The nesp32's clock, this much on."""
        self.clock += ms

    # --- the controller ----------------------------------------------------------

    def press(self, buttons):
        self.run(1, pad=buttons)
        self.run(1, pad=0)

    def enter(self, digits):
        """Set the form's digits, from wherever its mark is, by the shorter
        way round for each."""
        for index, digit in enumerate(digits):
            while self.c.byte("cursor") != index:
                self.press(PAD_RIGHT)
            there = self.c.byte("zip", index) - ord("0")
            ahead = (int(digit) - there) % 10
            for _ in range(ahead if ahead <= 5 else 10 - ahead):
                self.press(PAD_UP if ahead <= 5 else PAD_DOWN)
        assert self.digits == digits

    # --- what is on the screen ---------------------------------------------------

    @property
    def view(self):
        return self.c.byte("view")

    @property
    def status(self):
        return self.c.line(layout.STATUS_ROW)

    @property
    def foot(self):
        return self.c.line(layout.FOOT_ROW)

    def row(self, number):
        """A row of the middle of the screen, as its tiles."""
        return self.c.tiles(layout.BODY_ROW + number, layout.BODY_COLUMN,
                            layout.COLUMNS).decode("latin-1")

    def rows(self):
        return [self.row(number) for number in range(layout.ROWS)]

    @property
    def digits(self):
        """The digits the form shows, which are the ones it holds."""
        row = self.row(layout.FORM_DIGITS_ROW)
        shown = "".join(row[layout.FORM_DIGIT_COLUMN + layout.FORM_DIGIT_STEP * index]
                        for index in range(layout.ZIP_LEN))
        assert shown == bytes(self.c.data("zip", layout.ZIP_LEN)).decode("ascii")
        return shown

    @property
    def lit(self):
        """Which of the form's digits has the cursor's palette, by its
        square of the screen; None if none has. No other square of the
        screen ever has it."""
        attributes = bytearray(self.c.vram[0x23C0:0x2400])
        found = []
        for index in range(layout.ZIP_LEN):
            byte, shift = layout.attribute_cell(*layout.digit_place(index))
            if attributes[byte] >> shift & 3 == layout.PALETTE_CURSOR:
                found.append(index)
                attributes[byte] &= ~(3 << shift) & 0xFF
        assert bytes(attributes) == layout.build_screen().nametable()[960:]
        assert len(found) <= 1
        return found[0] if found else None

    @property
    def pulse(self):
        """The font's colour in the cursor's palette."""
        return self.c.vram[layout.PULSE_ADDRESS]

    def go(self):
        """From the form as it comes up: A, for the digits it has."""
        self.form_is_up()
        self.press(PAD_A)

    def form_is_up(self):
        """The form, whole and still, with nothing of a report under it."""
        self.run_until(lambda: self.c.byte("asked_last") and self.view == VIEW_FORM
                       and self.c.byte("paint_at") == self.c.byte("paint_end")
                       and not self.c.byte("row_dirty") and not self.c.byte("attr_dirty"))
        rows = self.rows()
        for number, line in enumerate(layout.form_lines()[:layout.ROWS]):
            if number != layout.FORM_DIGITS_ROW:
                assert rows[number] == line
        box = layout.build_screen().box[1]
        digits = rows[layout.FORM_DIGITS_ROW]
        assert digits[layout.BOX_FIRST] == chr(box[0]) and digits[layout.BOX_LAST] == chr(box[-1])
        assert self.foot == (layout.FOOT_FORM_CART if self.c.byte("on_cart")
                             else layout.FOOT_FORM)
        assert self.lit == self.c.byte("cursor")
        return self.digits

    def report_is_up(self, frames=600):
        """A report, whole: the rows of the middle of the screen."""
        self.run_until(lambda: self.view == VIEW_REPORT and self.c.byte("serial_have") != 0
                       and self.c.byte("serial_have") == self.c.byte("serial_want")
                       and self.c.byte("row_next") == layout.PAINT_ROWS
                       and not self.c.byte("row_dirty") and not self.c.byte("attr_dirty"), frames)
        assert self.foot == layout.FOOT_REPORT and self.status == ""
        assert self.lit is None
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
                if service == p.NESP_SVC_WEATHER and asked == op]

    def latest_write(self):
        """How far into vblank the latest of any NMI's PPU writes came."""
        return max(frame.last_write for frame in self.c.frames)

    def writes_were_in_time(self):
        assert 0 < self.latest_write() < VBLANK_CYCLES
