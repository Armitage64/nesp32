"""The link ROM on py65, wired through the serial line model to a host.

Every $4017 read returns the line level at the exact cycle the lda samples
it (its fourth cycle), and every $4016 write lands on the host's receiver at
the sta's fourth cycle. The host decodes requests as they complete and
queues each reply after a turnaround delay, so late hosts, noisy lines and
baud error can all be staged.

The receive loop's hunt for a start bit is fast-forwarded in whole loop
iterations while the line is idle, which keeps the loop's phase against the
next start bit exactly as it would have been.
"""

from nes_harness import JOY1, JOY2, Console
from protocol import RequestDecoder
from serial_line import CPU_HZ, MARK, HostToNes, NesToHost

LDA_ABS = 0xAD
STORE_ABS = (0x8C, 0x8D, 0x8E)  # sty, sta, stx absolute
HUNT_LOOP_CYCLES = 9            # lda abs 4 + lsr 2 + bcc taken 3
POLL_CYCLES = 200


def ms(value):
    return value * CPU_HZ / 1000.0


class LinkConsole(Console):
    def __init__(self, rom_path, labels_path, host=None, turnaround=lambda: ms(1.0),
                 to_nes=None, to_host=None, reply_fault=None, request_fault=None,
                 fast_forward=True):
        super().__init__(rom_path, labels_path)
        self.host = host
        self.turnaround = turnaround
        self.to_nes = to_nes or HostToNes()
        self.to_host = to_host or NesToHost()
        self.reply_fault = reply_fault        # bytes -> bytes, per reply
        self.request_fault = request_fault    # byte -> byte or None, per byte
        self.fast_forward = fast_forward
        self.decoder = RequestDecoder()
        self.requests = []    # (cycle, Request)
        self.read_log = None  # set to a list to record (cycle, level) reads
        self.write_log = None  # set to a list to record (cycle, level) writes
        self.next_poll = 0
        self.rx_hunt = self.labels["rx_hunt"]
        self.memory.subscribe_to_read([JOY2], self._read_joy2)
        self.memory.subscribe_to_write([JOY1], self._write_joy1)

    def _read_joy2(self, address):
        mpu = self.mpu
        if self.memory[mpu.pc - 1] != LDA_ABS:
            raise AssertionError("$4017 read by opcode $%02X" % self.memory[mpu.pc - 1])
        cycle = mpu.processorCycles + 3
        level = self.to_nes.level(cycle)
        if self.read_log is not None:
            self.read_log.append((cycle, level))
        return 0x40 | (level ^ 1)  # the port's buffer inverts D0

    def _write_joy1(self, address, value):
        mpu = self.mpu
        if self.memory[mpu.pc - 1] not in STORE_ABS:
            raise AssertionError("$4016 write by opcode $%02X" % self.memory[mpu.pc - 1])
        cycle = mpu.processorCycles + 3
        self.to_host.write(cycle, value & 1)
        if self.write_log is not None:
            self.write_log.append((cycle, value & 1))

    def poll(self, now):
        """Let the host act on every request byte that has arrived by now."""
        for end, byte in self.to_host.decode(now):
            if self.request_fault:
                byte = self.request_fault(byte)
                if byte is None:
                    continue
            for request in self.decoder.feed(bytes([byte])):
                self.requests.append((end, request))
                if self.host is None:
                    continue
                reply = self.host.handle(request)
                if reply and self.reply_fault:
                    reply = self.reply_fault(reply)
                if reply:
                    self.to_nes.send(reply, end + self.turnaround())

    def _idle_until(self, next_nmi):
        mpu = self.mpu
        now = mpu.processorCycles
        if now >= self.next_poll:
            self.poll(now)
            self.next_poll = now + POLL_CYCLES
        if not self.fast_forward:
            return None
        skip = super()._idle_until(next_nmi)
        if skip is not None:
            return skip
        if mpu.pc != self.rx_hunt or self.to_nes.in_frame(now):
            return None
        limit = min(self.to_nes.next_start_after(now), next_nmi, self.next_poll)
        loops = int((limit - now - 2 * HUNT_LOOP_CYCLES) // HUNT_LOOP_CYCLES)
        return now + loops * HUNT_LOOP_CYCLES if loops > 0 else None
