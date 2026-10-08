"""The link ROM on py65, joined by the serial line model to a nesp32.

The nesp32's end is its own firmware: the link and the JUKE and RAW
services, built for this computer (conftest.py) and driven through
nesp32's host/nesp.py. Only the hardware under them is a stand-in: its
files are the tracks the test gives it, and its UART is wire.py's Port.

Every $4017 read returns the line's level on the cycle the instruction
samples it (its fourth), and every $4016 write reaches the nesp32's
receiver on the cycle the sta makes it. The nesp32's code is polled every
SLICE cycles, as its link task would be, so late replies, noisy lines and
baud error can all be staged.

The receiver's hunt for a start bit is skipped in whole passes while the
line rests, which keeps its phase against the next start bit exactly as it
would have been.

Sampled sound needs nothing more: the nesp32's RAW service changes the
Port's rate and writes the samples to it, and they are on the line with
bits of the sound's own length.
"""

import nesp
import nesp_proto as p
import pcm
from nes_harness import JOY1, JOY2, PRG_START, Console
from wire import SLICE, Port, ms

__all__ = ["LinkConsole", "ms"]

# Instructions that read $4017 on their fourth cycle: lda, and the sound
# routines' cpy, cmp and eor.
READS_ABS = (0xAD, 0xCC, 0xCD, 0x4D)
STORE_ABS = (0x8C, 0x8D, 0x8E)  # sty, sta, stx absolute
# The link's wait for a start bit (nesp32's nes/lib/gen_link.py): lda JOY2 /
# lsr a / bcc, 9 cycles a look.
HUNT = bytes((0xAD, 0x17, 0x40, 0x4A, 0x90, 0xFA))
HUNT_CYCLES = 9


class LinkConsole(Console):
    """tracks are the nesp32's files, in order: .jbs and .pcm files as
    bytes. attached=False leaves the port with nothing on it. The rest are
    the Port's: turnaround, to_console, clock_error. loops and repeat are
    what a nesp32 would have set (it plays a looping track twice, and the
    playlist over again)."""

    def __init__(self, rom_path, labels_path, tracks=(), attached=True, fast_forward=True,
                 loops=None, repeat=None, **port_options):
        super().__init__(rom_path, labels_path)
        self.port = Port(self, **port_options)
        self.stick = None
        self._tracks = tuple(tracks)
        if attached:
            self.stick = nesp.Stick(self.port)
            for track in tracks:
                self.stick.add_track(track)
            settings = {name: value for name, value in (("loops", loops), ("repeat", repeat))
                        if value is not None}
            if settings:
                self.stick.set_juke(**settings)
        self.fast_forward = fast_forward
        self.read_log = None    # set to a list to record (cycle, level) reads
        self.write_log = None   # set to a list to record (cycle, level) writes
        self.port_bits = pcm.PORT_IDLE  # what the port's unused bits read
        self.next_poll = 0
        self.later = []         # (cycle, what to do then), for at()
        # Every reply the nesp32 made, before the line had its way with it:
        # (the request it answers, as requests() gives one, the cycle, the
        # reply's bytes). `answering` is that request while the Port's
        # to_console is being asked what becomes of the reply.
        self.answers = []
        self.answering = None
        self._heard = b""
        read, write = self.port.read, self.port.write

        def hear():
            data = read()
            if data:
                self._heard = (self._heard + data)[-2 * p.NESP_FRAME_MAX:]
            return data

        def answer(data):
            found = self._requests_in(self._heard)
            self.answering = found[-1] if found else None
            self.answers.append((self.answering, self.now, bytes(data)))
            write(data)
        self.port.read, self.port.write = hear, answer
        # The picture as each run of sound took the line: the screen stands
        # still from before then until the sound is over.
        self.sound_screens = []
        change_rate = self.port.line_rate

        def watch_rate(period):
            if len(self.port.rates) % 2 == 0:       # to a run's rate, not back from it
                self.sound_screens.append(self.nametable())
            change_rate(period)
        self.port.line_rate = watch_rate
        self.prg = bytes(self.memory[PRG_START:PRG_START + 0x8000])
        self.memory.subscribe_to_read([JOY2], self._read_joy2)
        self.memory.subscribe_to_write([JOY1], self._write_joy1)

    @property
    def now(self):
        """The time, in CPU cycles: what the Port goes by."""
        return self.mpu.processorCycles if self.mpu is not None else 0

    def _read_joy2(self, address):
        mpu = self.mpu
        if self.memory[mpu.pc - 1] not in READS_ABS:
            raise AssertionError("$4017 read by opcode $%02X" % self.memory[mpu.pc - 1])
        cycle = mpu.processorCycles + 3
        level = self.port.wire.level(cycle)
        if self.read_log is not None:
            self.read_log.append((cycle, level))
        return self.port_bits | (level ^ 1)  # the port's buffer inverts D0

    def _write_joy1(self, address, value):
        mpu = self.mpu
        if self.memory[mpu.pc - 1] not in STORE_ABS:
            raise AssertionError("$4016 write by opcode $%02X" % self.memory[mpu.pc - 1])
        cycle = mpu.processorCycles + 3
        self.port.tap.write(cycle, value & 1)
        if self.write_log is not None:
            self.write_log.append((cycle, value & 1))

    def press_button(self, event):
        """A button on the nesp32 (p.NESP_EVENT_BUTTON_*)."""
        self.stick.event(event)

    def power_off(self):
        """The nesp32 loses its power. What its UART already held of a run
        still goes out, which a real one's would not; the tests that use
        this do not count on either."""
        self.stick = None

    def power_cycle(self, tracks=None):
        """A new nesp32 on the same port, which knows nothing of the
        console. Its UART is at the link's rate, and it says what one says
        when it starts: four zero bytes."""
        tracks = self._tracks if tracks is None else tracks
        self.port.line_rate(p.NESP_PERIOD)
        self.stick = nesp.Stick(self.port)
        for track in tracks:
            self.stick.add_track(track)
        self.port.wire.send(bytes(4), self.now, self.port.bit)

    def at(self, cycle, action):
        """Do something when the clock reaches a cycle, wherever the ROM
        is then: in the middle of a sound, with the NMI off, as well."""
        self.later.append((cycle, action))

    def _idle_until(self, next_nmi):
        mpu = self.mpu
        now = mpu.processorCycles
        if now >= self.next_poll:
            for due in [item for item in self.later if item[0] <= now]:
                self.later.remove(due)
                due[1]()
            if self.stick is not None:
                self.stick.poll()
            self.next_poll = now + SLICE
        if not self.fast_forward:
            return None
        skip = super()._idle_until(next_nmi)
        if skip is not None:
            return skip
        offset = mpu.pc - PRG_START
        if offset < 0 or self.prg[offset:offset + len(HUNT)] != HUNT:
            return None
        quiet = self.port.wire.quiet_until(now)
        if quiet is None:
            return None
        limit = min(quiet, next_nmi, self.next_poll)
        passes = int((limit - now - 2 * HUNT_CYCLES) // HUNT_CYCLES)
        return now + passes * HUNT_CYCLES if passes > 0 else None

    # --- what the console did, in the link's terms ---------------------------------

    def requests(self):
        """Every request the nesp32's UART heard, as (service, op, payload),
        found in the bytes the way its decoder finds them."""
        if self.stick is None:
            self.port.read()        # nobody else has been listening
        return self._requests_in(b"".join(self.port.received))

    @staticmethod
    def _requests_in(heard):
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
