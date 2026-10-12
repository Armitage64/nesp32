"""The NPR ROM on py65, joined by the serial line model to a nesp32.

The console and the line are the jukebox's (its tests/link_harness.py),
and the nesp32's end is its own firmware, built for this computer. What is
different here is time: the jukebox's console is run a number of NMIs, and
a sound of the jukebox's ends by itself. A station's does not, and while it
plays there is no NMI to count. So this one is run a number of CPU cycles,
with whatever NMIs fall in them.
"""

import nesp_proto as p
from link_harness import LinkConsole
from nes_harness import NTSC_FRAME_CYCLES, PPUCTRL, PPUCTRL_NMI
from wire import ms

import gen_screen

__all__ = ["Radio", "ms"]

STATUS_ROW, STATUS_COLUMN = gen_screen.STATUS_ROW, gen_screen.STATUS_COLUMN
STATUS_WIDTH = gen_screen.STATUS_WIDTH


class Radio(LinkConsole):
    """A console on the ROM, with a nesp32 that is on a network unless
    wifi says otherwise. It has been run to its first NMI."""

    def __init__(self, rom_path, labels_path, wifi=p.NESP_WIFI_JOINED, **options):
        super().__init__(rom_path, labels_path, **options)
        if self.stick is not None:
            self.stick.set_wifi(wifi)
        self.level_log = []
        self.run(1)
        self.vblank = self.now - self.nmi_cycles[-1] + NTSC_FRAME_CYCLES

    def byte(self, name, offset=0):
        # The jukebox's console looks at its player's memory with every
        # NMI, which this ROM has none of.
        if name not in self.labels:
            return 0
        return super().byte(name, offset)

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

    def air(self, data, piece=1024):
        """More of the station's stream, in the pieces a fetch brings."""
        for start in range(0, len(data), piece):
            self.stick.fetch_body(data[start:start + piece])

    def asked(self, op):
        """How many times the console has asked TUNER this."""
        return sum(1 for service, asked, _ in self.requests()
                   if (service, asked) == (p.NESP_SVC_TUNER, op))
