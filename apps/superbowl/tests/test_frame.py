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
import math

from console import Console
from netplay import TICK_AT, Table
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
        self.busy = 0               # an NMI for a busy scheduler, which has no music (net_busy)
        self.waits = 0              # a lag's, with a sound waiting to be taken (net_lag_waits)
        self.sounds = 0
        self._sounded = True
        self.watch("NMI_TASK_BUSY", Timed._busy)
        self.watch("net_busy", Timed._busy)
        self.watch("net_lag_waits", Timed._waits)
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

    def _waits(self):
        if self.timing:
            self.waits += 1

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
        # Each NMI's music, but the last (its frame not over), the game's
        # busy ones, as in the original, and a lag's with a sound waiting
        # to be taken, which few are.
        assert console.sounds >= console.nmis - console.busy - console.waits - 1, \
            "player %d: the music in %d of %d NMIs" % (side + 1, console.sounds, console.nmis)
        assert console.waits < console.nmis // 100


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


class InIrq(Console):
    """A console whose vblank, every `every` frames once `late` is set,
    comes as the IRQ's handler has saved A and X: the NMI breaks into it."""

    def __init__(self, *args, every=7, **kwargs):
        super().__init__(*args, **kwargs)
        self.late = False
        self.every = every
        self.forced = 0
        self.watch(self.labels["IRQ_START"] + 6, InIrq._in_handler)

    def _in_handler(self):
        if self.late and not self.in_nmi and len(self.frames) % self.every == 0:
            self.mpu.processorCycles = max(self.mpu.processorCycles, math.ceil(self.next_vblank))
            self.forced += 1


def test_an_nmi_in_the_irqs_handler_lets_no_irq_in(build):
    """In the simulation, with the two consoles lagging apart, the scheduler
    took up a task at X = $00 at the end of a game: an NMI had come in the
    IRQ's handler, which keeps the main thread's registers in IRQ_A, X and
    Y, and a lag's music let the next split's IRQ in, which saved its own
    over them. Now a lag's NMI that came with the IRQ off keeps it off to
    its RTI, and has no music (net_lag_waits)."""
    make = functools.partial(InIrq, str(build / "tsb_net.nes"), str(build / "tsb_net.dbg"))
    table = Table(make, delay=ms(10))
    table.start()
    table.to_game()
    table.run(60)
    console = table.consoles[1]
    console.late = True
    before = table.ticks(1)
    table.play(900, moves(8))
    assert console.forced >= 20
    assert table.ticks(1) - before > 600
    assert table.same_game() > 600
    for side in range(2):
        assert table.consoles[side].byte("net_mode") == 0x80, "player %d left the session" % (side + 1)


class LastLine(Console):
    """A console whose IRQ's handler, once `late` is set, runs into the
    vblank in every frame, as one for a split on the picture's last line
    does: the vblank comes as it is about to give back the registers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.late = False
        self.forced = 0
        self.frames_forced = None
        self.watch(self.labels["UPDATE_IRQ_CHR_BANKS_SCROLL_LOC"] - 4, LastLine._tail)   # LDA IRQ_A, before the RTI

    def _tail(self):
        if not self.late or self.in_nmi or "I" not in self.interrupts or self.frames_forced == len(self.frames):
            return
        # The IRQ came in the idle loop, as it does after a game.
        sp = self.mpu.sp
        at = self.ram[0x100 + ((sp + 2) & 0xFF)] | self.ram[0x100 + ((sp + 3) & 0xFF)] << 8
        if self.labels["CHECK_TASKS"] <= at < self.labels["UPDATE_CURRENT_TASK"]:
            self.mpu.processorCycles = max(self.mpu.processorCycles, math.ceil(self.next_vblank))
            self.frames_forced = len(self.frames)
            self.forced += 1


def test_an_nmi_in_an_irq_on_the_idle_loop_is_a_tick(build):
    """In the simulation, after a game, one console stopped taking ticks
    for good and the other gave the session up: a split on the picture's
    last line, whose IRQ's handler ran into the vblank in every frame, and
    each NMI, finding the handler where the main thread was, took itself
    for a lag. Now it looks under the handler, at where the IRQ found the
    main thread (net_where): the idle loop, and a tick."""
    make = functools.partial(LastLine, str(build / "tsb_net.nes"), str(build / "tsb_net.dbg"))
    table = Table(make, delay=ms(10))
    games = ({}, {})            # each tick's game but for the stack's page
    for side, console in enumerate(table.consoles):
        table_taken = console.watches[console.labels[TICK_AT]]

        def taken(console, side=side, table_taken=table_taken):
            table_taken(console)
            kept = console.kept()
            games[side].setdefault(table.ticks(side), kept[:0x100] + kept[0x200:])
        console.watch(TICK_AT, taken)
    table.start()
    table.to_game()
    table.run(60)
    console = table.consoles[1]
    console.late = True
    before = table.ticks(1)
    table.play(600, moves(9))
    assert console.forced >= 50
    assert table.ticks(1) - before > 400
    # The forcing takes most of a frame away when the IRQ is a split high on
    # the screen, as in play, and after it a sleeping task's saved carry
    # has differed for a tick at a time, on its stack: the game has not.
    shared = sorted(set(games[0]) & set(games[1]))
    assert len(shared) > 400
    for tick in shared:
        assert games[0][tick] == games[1][tick], "the games differ at tick %d" % tick
    for side in range(2):
        assert table.consoles[side].byte("net_mode") == 0x80, "player %d left the session" % (side + 1)


class Raced(Console):
    """A console whose vblank, once `late` is set, begins in the STA with
    which DISABLE_INTERRUPTS_RENDERING turns the NMI off: the CPU has the
    NMI's edge before the write, and takes it after."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.late = False
        self.forced = 0
        self.watch(self.labels["DISABLE_INTERRUPTS_RENDERING"] + 7, Raced._sta)     # STA NES_PPU_CTRL

    def _sta(self):
        start = math.ceil(self.next_vblank) - 2         # its write is 3 cycles in
        if self.late and not self.in_nmi and self.mpu.processorCycles <= start:
            self.mpu.processorCycles = start
            self.forced += 1


def test_an_nmi_taken_as_ppuctrl_turns_it_off_brings_no_other(build):
    """On hardware a console went black after a play, and NETWORK GAME's
    rows had its last NMIs as a vblank that began as the drawing task turned
    the NMI off, and one more in the first's PPUCTRL, which turned it on
    with the vblank's flag still up: the second saved its registers over
    the main thread's. A lag's or a busy task's NMI reads PPUSTATUS first."""
    make = functools.partial(Raced, str(build / "tsb_net.nes"), str(build / "tsb_net.dbg"))
    table = Table(make, delay=ms(10))
    table.start()
    table.to_game()
    table.run(60)
    console = table.consoles[1]
    console.late = True
    late_before = console.late_nmis
    before = table.ticks(1)
    table.play(900, moves(4))
    assert console.forced >= 10
    assert console.raced_nmis >= console.forced
    assert console.late_nmis == late_before, "an NMI came in the raced one's PPUCTRL"
    assert table.ticks(1) - before > 600
    assert table.same_game() > 600
    for side in range(2):
        assert table.consoles[side].byte("net_mode") == 0x80, "player %d left the session" % (side + 1)
