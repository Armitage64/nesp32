"""NES Radar's link ROM on a simulated console, with a nesp32 on port 2 and
the test in place of Wikidata and adsb.fi, worked as a person with a
controller would.

The console is nesp32's (its tests/console.py), with what this ROM does
that the setup ROM does not: it keeps its NMI off but for the moment it
waits for a vblank to write in, finds a vblank at other times by looking at
PPUSTATUS, and writes to its CN-ROM's latch. And it is held to what
nes-radar counts on: nothing written to the PPU but in a vblank while the
picture is on, and nothing heard on the line with the NMI on.
"""

import json
import os

import nesp_proto as p
from console import (PAD_A, PAD_B, PAD_DOWN, PAD_LEFT, PAD_RIGHT, PAD_SELECT, PAD_START,
                     PAD_UP, PPUCTRL_NMI, PRG_START, RENDERING, VBLANK_CYCLES, Console)
from nesp import Stick, reply_frame
from wire import link

__all__ = ["Scope", "plane", "reply_of", "PLACES", "PAD_A", "PAD_B", "PAD_DOWN", "PAD_LEFT",
           "PAD_RIGHT", "PAD_SELECT", "PAD_START", "PAD_UP", "reply_frame", "where_reply"]

PLACES = {"KSBA": (34.4262, -119.8404), "KLAX": (33.942501, -118.407997),
          "EGLL": (51.4706, -0.461941)}
# nes-radar's two fonts of 42 characters, one after the other, and after
# them the numbers 1 to 8 in a box, for the aircraft that is selected.
GLYPHS = " 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ+-./:"
FONTS = 2
BOXED = FONTS * len(GLYPHS)
# Its screens (assets/ldv/ldv_screen.inc, and the editor's message).
MESSAGE = (15, 8, 16)
LINK = (27, 15, 9)
AIRPORT = (27, 27, 4)
COUNT = (1, 24, 2)
SELECTED = (5, 0, 2)
TABLE = [(22 + slot % 4, 1 + 16 * (slot // 4)) for slot in range(8)]
SPLASH_FRAMES = 130

WAIT_FLAG = bytes((0x2C, 0x02, 0x20, 0x10, 0xFB))   # bit PPUSTATUS / bpl: until a vblank
WAIT_NMI = (0xA5, 0xF0, 0xFC)                       # lda vblank_ready / beq


def plane(north, east, place=PLACES["KSBA"], **more):
    """An aircraft this many degrees north and east of a place."""
    item = {"hex": "abc123", "flight": "TEST1   ", "r": "N1", "t": "B738", "alt_baro": 5000,
            "gs": 250.0, "track": 90.0, "baro_rate": 0, "squawk": "1200", "category": "A3",
            "lat": place[0] + north, "lon": place[1] + east}
    item.update(more)
    return item


def where_reply(place):
    """Wikidata's answer to where an airport is: the place, or nothing."""
    found = [] if place is None else [{"p": {"type": "literal",
                                             "value": "Point(%r %r)" % (place[1], place[0])}}]
    return json.dumps({"head": {"vars": ["p"]}, "results": {"bindings": found}}).encode("utf-8")


def reply_of(aircraft):
    return json.dumps({"ac": aircraft, "msg": "No error", "now": 1, "total": len(aircraft)},
                      separators=(",", ":")).encode("utf-8")


class RadarConsole(Console):
    def __init__(self, rom_path, labels_path):
        super().__init__(rom_path, labels_path)
        self.strict = False         # the NMI is off most of the time, and that is meant
        self.latch = None           # the CN-ROM's: which 8 KB of CHR
        self.late_writes = []       # (frame, cycles after its vblank) of a PPU write too late
        self.heard_in_nmi = 0       # reads of the line with the NMI on
        self.dmas = 0
        self.memory.subscribe_to_write(range(PRG_START, 0x10000), self._write_latch)

    def _write_latch(self, address, value):
        self.latch = value & 3
        return self.prg[address - PRG_START]    # the program is not written to

    def _in_vblank(self):
        return self.now + 3 - self.frame.start < VBLANK_CYCLES

    def _write_data(self, address, value):
        if self.mask & RENDERING and not self._in_vblank():
            self.late_writes.append((len(self.frames), self.now + 3 - self.frame.start))
        self.strict, strict = False, self.strict
        super()._write_data(address, value)
        self.strict = strict

    def _write_dma(self, address, value):
        if self.mask & RENDERING and not self._in_vblank():
            self.late_writes.append((len(self.frames), self.now + 3 - self.frame.start))
        self.dmas += 1
        super()._write_dma(address, value)

    def _read_joy2(self, address):
        if self.ctrl & PPUCTRL_NMI:
            self.heard_in_nmi += 1
        return super()._read_joy2(address)

    def _skip(self):
        mpu = self.mpu
        offset = mpu.pc - PRG_START
        if offset >= 0 and self.next_vblank != float("inf"):
            waiting = (self.prg[offset:offset + 5] == WAIT_FLAG and not self.vblank_unread)
            if not waiting and self.ctrl & PPUCTRL_NMI:
                code = self.prg[offset:offset + 4]
                waiting = ((code[0], code[2], code[3]) == WAIT_NMI
                           and code[1] == self.labels["vblank_ready"]
                           and not self.byte("vblank_ready"))
            if waiting and mpu.processorCycles < int(self.next_vblank):
                mpu.processorCycles = int(self.next_vblank) + 1
                return True
        return super()._skip()

    def field(self, where):
        """A field's tiles as text, whichever of the fonts they are in."""
        row, column, length = where
        return "".join(GLYPHS[tile % len(GLYPHS)] if tile < FONTS * len(GLYPHS) else "^"
                       for tile in self.tiles(row, column, length))


class Scope:
    """A console on the link ROM, a nesp32, and a Wikidata that knows a few
    airports."""

    def __init__(self, rom_path, labels_path, stick=True, online=True, places=PLACES,
                 **port_options):
        self.c = RadarConsole(rom_path, labels_path)
        self.stick = self.port = None
        self.places = places
        if stick:
            self.stick, self.port = link(self.c, Stick, **port_options)
            if online:
                self.stick.set_wifi(p.NESP_WIFI_JOINED, address=(10, 0, 0, 2))

    # --- what is on the screen ---------------------------------------------------

    @property
    def message(self):
        return self.c.field(MESSAGE).strip()

    @property
    def link(self):
        return self.c.field(LINK).strip()

    @property
    def airport(self):
        return self.c.field(AIRPORT)

    @property
    def count(self):
        return int(self.c.field(COUNT))

    @property
    def selected(self):
        """The selected aircraft's number, 1 to 8, or None: the tile after
        the blank one, which is from the eight that are numbers in a box."""
        tile = self.c.tiles(SELECTED[0], SELECTED[1] + 1, 1)[0]
        return tile - BOXED + 1 if BOXED <= tile < BOXED + 8 else None

    def row(self, slot):
        """(callsign, type) of a slot's row of the table."""
        row, column = TABLE[slot]
        return (self.c.field((row, column + 2, 7)).rstrip(),
                self.c.field((row, column + 10, 4)).rstrip())

    def calls(self):
        return [self.row(slot)[0] for slot in range(8)]

    @property
    def code(self):
        return self.c.data("icao_code", 4).decode()

    def targets(self):
        """The (x, y) of each target on the picture: the left half of each
        pair of sprites."""
        out = []
        for index in range(0, 16, 2):
            sprite = self.c.sprite(index)
            if sprite is not None:
                out.append(sprite[:2])
        return out

    # --- the controller ----------------------------------------------------------

    def past_splash(self):
        self.c.run(SPLASH_FRAMES)
        assert self.c.latch == 1

    def choose(self, code):
        """Set the editor's four letters."""
        for position, letter in enumerate(code):
            while self.code[position] != letter:
                up = (ord(letter) - ord(self.code[position])) % 26 <= 13
                self.c.press(PAD_UP if up else PAD_DOWN)
            self.c.press(PAD_RIGHT)
        assert self.code == code

    def start(self, code="KSBA"):
        """From power-on to Start on an airport."""
        self.past_splash()
        self.choose(code)
        self.c.press(PAD_START)

    def locate(self, code, found=True, frames=200):
        """The nesp32 asks where the airport is, and is told, or told there
        is none."""
        self.c.run_until(lambda: self.stick.fetching, frames)
        assert "wikidata" in self.stick.fetch_url and '%%22%s%%22' % code in self.stick.fetch_url
        assert self.message == "REQUESTING"
        assert self.stick.fetch_body(where_reply(self.places.get(code) if found else None))
        self.stick.fetch_done(True)

    def open(self, code="KSBA", known=False):
        """From power-on to the scope, with the fetch of its aircraft under
        way."""
        self.start(code)
        if not known:
            self.locate(code)
        self.c.run_until(lambda: self.stick.fetching and "adsb.fi" in self.stick.fetch_url, 200)
        self.c.run_until(lambda: self.link == "WAITING" and self.airport == code, 60)

    # --- adsb.fi -----------------------------------------------------------------

    def land(self, aircraft, frames=120):
        """The fetch under way brings these aircraft, and the scope shows
        them."""
        self.c.run_until(lambda: self.stick.fetching and "adsb.fi" in self.stick.fetch_url, 600)
        body = reply_of(aircraft)
        assert self.stick.fetch_body(body)
        self.stick.fetch_done(True)
        self.c.run(frames)

    def fail(self, frames=120):
        self.c.run_until(lambda: self.stick.fetching, 600)
        self.stick.fetch_done(False, b"no route")
        self.c.run(frames)

    def asked(self, op):
        """How many requests the console has made of RADAR with this op."""
        count = 0
        data = b"".join(self.port.received)
        at = data.find(bytes((p.NESP_REQUEST_MARKER, p.NESP_SVC_RADAR, op)))
        while at >= 0:
            count += 1
            at = data.find(bytes((p.NESP_REQUEST_MARKER, p.NESP_SVC_RADAR, op)), at + 1)
        return count
