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

from nesjuke.protocol import OP_DATA, OP_HELLO, RequestDecoder

if hasattr(time, "ticks_us"):
    ticks_us = time.ticks_us
    ticks_diff = time.ticks_diff
else:  # CPython, for the tests
    def ticks_us():
        return int(time.monotonic() * 1000000)

    def ticks_diff(a, b):
        return a - b


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
        self.reply_us_max = 0   # this code's own time from bytes in to burst out

    def poll(self):
        """Answer what has arrived. True if a burst went out."""
        count = self.uart.readinto(self.rx)
        if not count:
            return False
        started = self.ticks_us()
        rx = self.rx
        decoder = self.decoder
        host = self.host
        wanted = False
        seq = arg = 0
        for index in range(count):
            if not decoder.push(rx[index]):
                continue
            self.requests += 1
            if decoder.op == OP_DATA:
                # After a pause several requests can be waiting. The NES
                # only listens for an answer to its latest, and repeats
                # are the same request again, so answer once.
                self.data_requests += 1
                if wanted:
                    self.stale += 1
                wanted = True
                seq = decoder.seq
                arg = decoder.arg
            else:
                host.handle(decoder.op, decoder.seq, decoder.arg)
                if decoder.op == OP_HELLO:
                    wanted = False
        if not wanted:
            return False
        self.uart.write(host.handle(OP_DATA, seq, arg))
        elapsed = ticks_diff(self.ticks_us(), started)
        if elapsed > self.reply_us_max:
            self.reply_us_max = elapsed
        host.prepare()
        return True

    def take_reply_us_max(self):
        """The slowest reply since the last call, in microseconds."""
        worst, self.reply_us_max = self.reply_us_max, 0
        return worst
