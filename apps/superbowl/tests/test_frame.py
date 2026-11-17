"""What a session's NMI does to the frame, as the original's does: the
screen's splits on time, and the music in every NMI.

On hardware (November 2026) the top of the screen broke up in play and in
many scenes, and the music slowed with the lags: the exchange, which holds
the IRQ off, came where the first split's IRQ falls (some 5,000 cycles into
the frame), and a lag's NMI did not run the sound engine. Now the read and
the exchange come before the sound (net_sound_hook), the digest is taken
with the IRQ on, and a lag's NMI runs the music (net_lag_sound)."""

import functools

from console import Console
from netplay import Table
from test_lockstep import moves
from wire import ms

LINE = 341 / 3.0                # CPU cycles a scanline
SOUND_ENGINE = 0x8000           # SOUND_ENGINE_START, in bank $1B
SOUND_BANK = 0x1B


class Timed(Console):
    """A console that notes how late each of the MMC3's IRQs is taken, and
    which NMIs ran the sound engine, once `timing` is set."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timing = False
        self.raised_at = None
        self.late = []
        self.nmis = 0
        self.busy = 0               # the game's own NMI for a busy scheduler, which has no music
        self.sounds = 0
        self._sounded = True
        self.watch("NMI_TASK_BUSY", Timed._busy)
        self.watch(SOUND_ENGINE, Timed._sound)
        irq = self.mpu.irq

        def taken():
            if self.timing and self.raised_at is not None:
                self.late.append(self.mpu.processorCycles - self.raised_at)
            self.raised_at = None
            irq()
        self.mpu.irq = taken

    def _busy(self):
        if self.timing:
            self.busy += 1

    def _sound(self):
        if self.bus.bank_at(SOUND_ENGINE) == SOUND_BANK and not self._sounded:
            self._sounded = True
            self.sounds += 1

    def _vblank(self):
        if self.timing and self.ctrl & 0x80:
            self.nmis += 1
            self._sounded = False
        super()._vblank()

    def _clock(self):
        before = self.irq_line
        super()._clock()
        if self.irq_line and not before:
            self.raised_at = self.mpu.processorCycles


def test_the_splits_on_time_and_the_music_in_every_nmi(build):
    make = functools.partial(Timed, str(build / "tsb_net.nes"), str(build / "tsb_net.dbg"))
    table = Table(make, delay=ms(10))
    table.start()
    table.to_game()
    table.run(120)
    for console in table.consoles:
        console.timing = True
    table.play(1500, moves(4))
    assert table.same_game() > 1400
    for side, console in enumerate(table.consoles):
        late = [cycles for cycles in console.late if cycles > LINE]
        assert len(console.late) > 1000, "the splits were not seen"
        assert not late, "player %d: %d of %d splits a scanline late or more, the worst %d cycles" % (
            side + 1, len(late), len(console.late), max(late))
        # Each NMI's music, but the last (its frame not over) and the
        # game's busy ones, as in the original.
        assert console.sounds >= console.nmis - console.busy - 1, \
            "player %d: the music in %d of %d NMIs" % (side + 1, console.sounds, console.nmis)
