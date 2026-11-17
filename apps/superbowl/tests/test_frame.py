"""What a session's NMI does to the frame, as the original's does: the
screen's splits on time, and the music in every NMI.

On hardware (November 2026) the top of the screen broke up in play and in
many scenes, and the music slowed with the lags: the exchange, which holds
the IRQ off, came where the first split's IRQ falls (some 5,000 cycles into
the frame), and a lag's NMI did not run the sound engine. Now the read and
the exchange come before the sound (net_sound_hook), the digest is taken
with the IRQ on, and a lag's NMI runs the music (net_lag_sound). A
misheard reply is asked again in the same NMI only if the next split
leaves room (net_ask)."""

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


def mishear(port, every):
    """One of each `every` runs of bytes the nesp32 sends the console made
    to fail its check: a sample's fetch, on hardware."""
    write = port.write
    runs = [0]

    def damaged(data):
        runs[0] += 1
        if runs[0] % every == 0 and data:
            data = bytes(data[:-1]) + bytes([data[-1] ^ 0x5A])
        return write(data)
    port.write = damaged


def test_a_reply_misheard_holds_no_split_back(build):
    """On hardware (November 2026) the top of the screen still broke up now
    and again, with the voice's samples: a reply misheard and asked again
    in the same NMI is a second exchange, which ran past the first split
    (line 32, some 6,000 cycles into the frame, in most of play)."""
    make = functools.partial(Timed, str(build / "tsb_net.nes"), str(build / "tsb_net.dbg"))
    table = Table(make, delay=ms(10))
    table.start()
    table.to_game()
    table.run(120)
    for side, console in enumerate(table.consoles):
        console.timing = True
        mishear(table.ports[side], 7)
    table.play(600, moves(4))
    assert table.same_game() > 400
    for side, console in enumerate(table.consoles):
        late = [cycles for cycles in console.late if cycles > LINE]
        assert len(console.late) > 400, "the splits were not seen"
        assert not late, "player %d: %d of %d splits a scanline late or more, the worst %d cycles" % (
            side + 1, len(late), len(console.late), max(late))


class Late(Console):
    """A console whose session NMI's exchange takes a frame and more, once
    in `every` frames, once `late` is set: as one whose nesp32 answered
    that late would."""

    def __init__(self, *args, every=37, **kwargs):
        super().__init__(*args, **kwargs)
        self.late = False
        self.every = every
        self.stretched = 0
        self.nested = 0
        self.watch("net_exchange_now", Late._long)
        self.watch(self.labels["RETURN_FROM_NMI_TASK_BUSY"] + 6, Late._back)

    def _long(self):
        if self.late and len(self.frames) % self.every == 0:
            self.mpu.processorCycles += 31000      # past the next vblank
            self.stretched += 1

    def _back(self):
        self.nested += 1


def test_an_nmi_that_runs_into_the_next_is_let_be(build):
    """On hardware (November 2026) both consoles stopped in a game, the
    screen black and a note held. An NMI that came while a session's NMI
    was still at its own work, its exchange having run long, went as a lag:
    it put the banks back from the game's shadows, and returned into the
    netplay's code in another bank. Now it gives the registers back and
    nothing else (net_nmi_check), and the NMI it came in goes back to the
    start of the idle loop, whose registers it no longer has."""
    make = functools.partial(Late, str(build / "tsb_net.nes"), str(build / "tsb_net.dbg"))
    table = Table(make, delay=ms(10))
    table.start()
    table.to_game()
    table.run(60)
    console = table.consoles[0]
    console.late = True
    before = table.ticks(0)
    table.play(600, moves(7))
    assert console.stretched >= 10
    assert console.nested >= 10                 # each of them let be
    assert table.ticks(0) - before > 400
    assert table.same_game() > 400
    for side in range(2):
        assert table.consoles[side].byte("net_mode") == 0x80, "player %d left the session" % (side + 1)
