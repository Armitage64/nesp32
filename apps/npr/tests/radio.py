"""The NPR ROM on py65, joined by the serial line model to a nesp32.

The console and the line are the jukebox's (its tests/link_harness.py),
and the nesp32's end is its own firmware, built for this computer. What is
different here is time: the jukebox's console is run a number of NMIs, and
a sound of the jukebox's ends by itself. A station's does not, and while it
plays there is no NMI to count. So this one is run a number of CPU cycles,
with whatever NMIs fall in them.

And the PPU, which the station's routine writes to while it plays, with the
NMI off: it asks $2002 whether vblank has begun, and may write only while
it lasts. So with the NMI off $2002 says what a console's would, the
vblank flag from the cycle vblank begins until it is read or vblank ends;
and every write to the PPU then is noted, with how far into vblank it came
(`ppu_writes`), or that it was outside one (`ppu_strays`). The two
nametables are both kept, and the one PPUCTRL names is the screen.
"""

import nesp_proto as p
from link_harness import LinkConsole
from nes_harness import (NTSC_FRAME_CYCLES, PPUADDR, PPUCTRL, PPUCTRL_NMI, PPUDATA, PPUSTATUS,
                         VBLANK, VBLANK_CYCLES)
from wire import ms

import gen_news
import gen_screen

__all__ = ["Radio", "ms", "PPUSCROLL"]

PPUSCROLL = 0x2005
NAMETABLES = (0x2000, 0x2800)       # horizontal mirroring: PPUCTRL's bit 1 chooses

STATUS_ROW, STATUS_COLUMN = gen_screen.STATUS_ROW, gen_screen.STATUS_COLUMN
STATUS_WIDTH = gen_screen.STATUS_WIDTH
FOOT_ROW = gen_screen.gen_ui.HELP_ROW
# The foot's pictures' tiles, as gen_screen.FOOT_TEXT has them.
ICONS = {chr(tile): char for char, tile in gen_screen.build_screen().icons.items()}


class Radio(LinkConsole):
    """A console on the ROM, with a nesp32 that is on a network unless
    wifi says otherwise. It has been run to its first NMI."""

    def __init__(self, rom_path, labels_path, wifi=p.NESP_WIFI_JOINED, **options):
        super().__init__(rom_path, labels_path, **options)
        if self.stick is not None:
            self.stick.set_wifi(wifi)
        self.level_log = []
        self.ppu_writes = []        # with the NMI off: (cycles into vblank, register, value)
        self.ppu_strays = []        # and those that were not in one: (cycle, register, value)
        self._vblank_read = None    # the vblank whose flag has been read
        self.memory.subscribe_to_write([PPUCTRL, PPUSCROLL, PPUADDR, PPUDATA], self._ppu_write)
        self.run(1)
        self.vblank = self.now - self.nmi_cycles[-1] + NTSC_FRAME_CYCLES

    def byte(self, name, offset=0):
        # The jukebox's console looks at its player's memory with every
        # NMI, which this ROM has none of.
        if name not in self.labels:
            return 0
        return super().byte(name, offset)

    def _vblank_before(self, cycle):
        """When the last vblank at or before a cycle began."""
        return self.vblank - -(-(self.vblank - cycle) // NTSC_FRAME_CYCLES) * NTSC_FRAME_CYCLES

    def _read_ppustatus(self, address):
        if getattr(self, "vblank", None) is None or not self.deaf:
            return super()._read_ppustatus(address)     # the ROM's own waits, at reset
        self.ppu_latch = None
        cycle = self.mpu.processorCycles + 3
        began = self._vblank_before(cycle)
        if cycle - began >= VBLANK_CYCLES or self._vblank_read == began:
            return 0
        self._vblank_read = began
        return VBLANK

    def _ppu_write(self, address, value):
        if getattr(self, "vblank", None) is None or not self.deaf or self.mpu is None:
            return
        if address == PPUCTRL and value & PPUCTRL_NMI:
            return                  # the sound is over: the NMI goes back on
        cycle = self.mpu.processorCycles + 3
        into = cycle - self._vblank_before(cycle)
        if into < VBLANK_CYCLES:
            self.ppu_writes.append((into, address, value))
        else:
            self.ppu_strays.append((cycle, address, value))

    @property
    def shown(self):
        """Where the nametable on the screen is."""
        return NAMETABLES[self.memory[PPUCTRL] >> 1 & 1]

    def screen_text(self, column, row, length, nametable=None):
        start = (self.shown if nametable is None else nametable) + 32 * row + column
        return bytes(self.vram[start:start + length]).decode("latin-1")

    def nametable(self, which=None):
        start = self.shown if which is None else which
        return bytes(self.vram[start:start + 0x400])

    def page(self, nametable=None):
        """The ten lines of headlines on a nametable, the screen's unless
        another is named."""
        return [self.screen_text(gen_news.NEWS_COLUMN, gen_news.NEWS_ROW + row,
                                 gen_news.COLUMNS, nametable) for row in range(gen_news.ROWS)]

    @property
    def deaf(self):
        """The NMI is off: the console is in a sound."""
        return not self.memory[PPUCTRL] & PPUCTRL_NMI

    def advance(self, cycles):
        """Run this many CPU cycles, at least: the NMIs that fall in them
        are taken if the ROM has them on."""
        mpu = self.mpu
        end = mpu.processorCycles + cycles
        while mpu.processorCycles < end:
            if mpu.processorCycles >= self.vblank:
                self.vblank += NTSC_FRAME_CYCLES
                if not self.deaf:
                    self._nmi()
                    continue
            skip = self._idle_until(min(self.vblank, end))
            if skip is not None and skip > mpu.processorCycles:
                mpu.processorCycles = skip
            else:
                mpu.step()

    def wait(self, count=1):
        self.advance(count * NTSC_FRAME_CYCLES)

    def until(self, done, limit=600):
        """Run a frame at a time until done() is true."""
        for _ in range(limit):
            if done():
                return
            self.wait()
        raise AssertionError("still waiting after %d frames" % limit)

    def press(self, buttons, frames=3):
        """Hold buttons on controller 1 for some frames, then let go."""
        self.pad = buttons
        self.wait(frames)
        self.pad = 0

    def reset(self):
        """The console's Reset button."""
        self.mpu.pc = self.memory[0xFFFC] | self.memory[0xFFFD] << 8

    @property
    def status(self):
        """What the status line says."""
        return self.screen_text(STATUS_COLUMN, STATUS_ROW, STATUS_WIDTH).strip()

    @property
    def off(self):
        """No station is tuned in, and the status line says nothing: the
        menu waits for A or Start."""
        return self.status == "" and self.byte("tuner") == p.NESP_TUNER_OFF

    def foot(self, nametable=None):
        """What the foot says, with its pictures as gen_screen.FOOT_TEXT
        has them."""
        text = self.screen_text(gen_screen.FOOT_COLUMN, FOOT_ROW, gen_screen.FOOT_WIDTH,
                                nametable)
        return "".join(ICONS.get(char, char) for char in text).strip()

    def air(self, data, piece=1024):
        """More of the station's stream, in the pieces a fetch brings."""
        for start in range(0, len(data), piece):
            self.stick.fetch_body(data[start:start + piece])

    def asked(self, op):
        """How many times the console has asked TUNER this."""
        return sum(1 for service, asked, _ in self.requests()
                   if (service, asked) == (p.NESP_SVC_TUNER, op))
