"""The Gallery ROM on py65, joined by the serial line model to a nesp32,
with the test as Wikimedia Commons.

The console and the line are nesp32's own tests' (its tests/console.py and
tests/wire.py), with sprite 0's hit on, and the nesp32's end is its
firmware's code, built for this computer.

Commons is here: a search the nesp32 begins is answered with `pictures`
of them, each named and with a thumbnail's address; a thumbnail with the
picture the test gave, or a failure.
"""

import json

import nesp
import nesp_proto as p
from console import (PAD_A, PAD_B, PAD_DOWN, PAD_LEFT, PAD_RIGHT, PAD_SELECT, PAD_START,
                     PAD_UP, Console)
from wire import link

__all__ = ["Viewer", "PAD_A", "PAD_B", "PAD_DOWN", "PAD_LEFT", "PAD_RIGHT", "PAD_SELECT",
           "PAD_START", "PAD_UP", "STATE_SEARCH", "STATE_SEARCHING", "STATE_INFO",
           "STATE_LOADING", "STATE_VIEW"]

STATE_SEARCH, STATE_SEARCHING, STATE_INFO, STATE_LOADING, STATE_VIEW = range(5)
THUMB = "https://upload.example/thumb/%d.jpg"


def reply_of(count, start=1):
    """A search's reply from Commons with `count` pictures."""
    pages = [{"pageid": 100 + index, "ns": 6, "index": index,
              "title": "File:Picture number %d.jpg" % index,
              "imageinfo": [{"thumburl": THUMB % index, "thumbwidth": 320,
                             "extmetadata": {"Artist": {"value": "<a href=\"//x\">Ann Example</a>"},
                                             "LicenseShortName": {"value": "CC BY 4.0"}}}]}
             for index in range(start, start + count)]
    return json.dumps({"batchcomplete": True, "query": {"pages": pages}}).encode()


class Viewer:
    """A console on the ROM, and a nesp32 on a network. Commons finds
    `pictures` pictures for any search, each of them `picture` (bytes of a
    JPEG); failing is a set of the thumbnails' numbers that fail."""

    def __init__(self, rom_path, labels_path, picture=None, pictures=3, failing=(),
                 wifi=p.NESP_WIFI_JOINED):
        self.c = Console(rom_path, labels_path)
        self.c.sprite0_hits = True
        self.picture = picture
        self.pictures = pictures
        self.failing = set(failing)
        self.hold = False           # fetches wait to be served
        self.served = []            # the address of every fetch answered
        self.stick, self.port = link(self.c, nesp.Stick)
        self.stick.set_wifi(wifi, address=(10, 0, 0, 2))

    # --- Commons --------------------------------------------------------------------

    def serve(self):
        """Answer the fetch the nesp32 has under way."""
        url = self.stick.fetch_url
        self.served.append(url)
        if url.startswith("https://commons.wikimedia.org/"):
            self.stick.fetch_body(reply_of(self.pictures))
            self.stick.fetch_done(True)
            return
        number = int(url.rsplit("/", 1)[1].split(".")[0])
        if number in self.failing:
            self.stick.fetch_done(False, b"THE SITE SAID 404")
            return
        for start in range(0, len(self.picture), 4096):
            self.stick.fetch_body(self.picture[start:start + 4096])
        self.stick.fetch_done(True)

    def made(self):
        """The picture as the nesp32 makes it from what Commons sends."""
        return self.stick.picture(self.picture)

    # --- the console ----------------------------------------------------------------

    def run(self, frames=1, pad=None):
        for _ in range(frames):
            self.c.run(1, pad=pad)
            if self.stick.fetching and not self.hold:
                self.serve()

    def press(self, buttons, frames=2, release=2):
        self.run(frames, pad=buttons)
        self.run(release, pad=0)

    def run_until(self, condition, frames=900):
        for count in range(frames):
            if condition():
                return count
            self.run(1)
        raise AssertionError("still waiting after %d frames, in state %d:\n%s"
                             % (frames, self.state, self.c.screen()))

    @property
    def state(self):
        return self.c.byte("state")

    def text(self, nametable, row, column=0, length=32):
        """A row of a nametable as text, the second colour's bit off."""
        start = 0x2000 + 0x400 * nametable + 32 * row + column
        out = []
        for tile in self.c.vram[start:start + length]:
            code = tile & 0x7F
            out.append(chr(code) if 0x20 <= code < 0x7F else " ")
        return "".join(out)

    def line(self, nametable, row):
        return self.text(nametable, row).strip()

    def search(self):
        """From power-on to the first picture's info page: the default
        search, by Start."""
        self.run_until(lambda: self.c.byte("query_len") > 0)
        self.press(PAD_START)
        self.run_until(lambda: self.state != STATE_SEARCHING and self.state != STATE_SEARCH)

    def shown(self):
        """Run until a picture is up."""
        self.run_until(lambda: self.state == STATE_VIEW)
        self.run(3)
