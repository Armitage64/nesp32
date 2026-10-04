"""The reply loop: requests in from the UART, bursts out. No hardware here.

The NES sends a request right after a vblank and waits for the burst, so
poll() must be called as often as possible. Everything else the Stick does
(buttons, the screen, garbage collection) belongs right after poll() returns
True: the burst then takes about 8 ms to go out, and the next request cannot
come before the next vblank.

The uart needs readinto(buffer), returning None or 0 when nothing is
waiting, and write(buffer).
"""

import time

from nesjuke.protocol import OP_DATA, OP_HELLO, OP_SOUND, RequestDecoder

if hasattr(time, "ticks_us"):
    ticks_us = time.ticks_us
    ticks_diff = time.ticks_diff
else:  # CPython, for the tests
    def ticks_us():
        return int(time.monotonic() * 1000000)

    def ticks_diff(a, b):
        return a - b


FRAME_US = 16639        # one NTSC frame: requests come this far apart, or a multiple
QUIET_FROM_US = 1000    # after a request arrives: the reply is on its way
QUIET_UNTIL_US = 6000   # late enough to leave 10 ms before the next can come
TRUST_PHASE_US = 5000000
TIGHT_POLL_US = 1000


class Player:
    def __init__(self, uart, host, ticks_us=ticks_us):
        self.uart = uart
        self.host = host
        self.ticks_us = ticks_us
        self.decoder = RequestDecoder()
        self.rx = bytearray(64)
        self.requests = 0
        self.data_requests = 0
        self.stale = 0          # data requests passed over for a newer one
        # This code's own time from bytes in to handing the burst to the
        # UART, which is when it starts to go out; and how long write() then
        # took, which matters only if it holds up the next poll.
        self.reply_us_max = 0
        self.reply_us_sum = 0
        self.replies = 0
        self.write_us_max = 0
        self.request_us = None  # when a request last arrived, for quiet()
        self.polled_us = None

    def quiet(self, now_us):
        """True when now is a safe time to start up to 10 ms of other work.

        The NES sends requests at a fixed point after its vblank, so the
        next one can only arrive a whole number of frames after the last.
        Work that starts just after that point is over before the next. With
        no recent request to go by, any time is as good as another.
        """
        if self.request_us is None:
            return True
        age = ticks_diff(now_us, self.request_us)
        if age > TRUST_PHASE_US:
            return True
        return QUIET_FROM_US <= age % FRAME_US <= QUIET_UNTIL_US

    def poll(self):
        """Answer what has arrived. True if a burst went out."""
        count = self.uart.readinto(self.rx)
        if not count:
            self.polled_us = self.ticks_us()
            return False
        started = self.ticks_us()
        # These bytes arrived just now only if the last poll was a moment
        # ago. After a pause they may have been waiting, and say nothing
        # about where in the frame requests fall.
        timely = (self.polled_us is not None
                  and ticks_diff(started, self.polled_us) < TIGHT_POLL_US)
        self.polled_us = started
        rx = self.rx
        decoder = self.decoder
        host = self.host
        wanted = False
        op = seq = arg = 0
        for index in range(count):
            if not decoder.push(rx[index]):
                continue
            self.requests += 1
            if timely:
                self.request_us = started
            if decoder.op == OP_DATA or decoder.op == OP_SOUND:
                # After a pause several requests can be waiting. The NES
                # only listens for an answer to its latest, and repeats
                # are the same request again, so answer once. A sound
                # request is answered as a data request is.
                self.data_requests += 1
                if wanted:
                    self.stale += 1
                wanted = True
                op = decoder.op
                seq = decoder.seq
                arg = decoder.arg
            else:
                host.handle(decoder.op, decoder.seq, decoder.arg)
                if decoder.op == OP_HELLO:
                    wanted = False
        if not wanted:
            return False
        burst = host.handle(op, seq, arg)
        ready = self.ticks_us()
        self.uart.write(burst)
        written = self.ticks_us()
        elapsed = ticks_diff(ready, started)
        if elapsed > self.reply_us_max:
            self.reply_us_max = elapsed
        self.reply_us_sum += elapsed
        self.replies += 1
        elapsed = ticks_diff(written, ready)
        if elapsed > self.write_us_max:
            self.write_us_max = elapsed
        host.prepare()
        return True

    def take_reply_us(self):
        """(slowest, average, slowest write) since the last call, in microseconds."""
        timing = (self.reply_us_max, self.reply_us_sum // max(1, self.replies),
                  self.write_us_max)
        self.reply_us_max = self.reply_us_sum = self.replies = self.write_us_max = 0
        return timing
