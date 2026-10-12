#!/usr/bin/env python3
"""Hear a sound track as the console would play it, without a console.

    tools/pcm_preview.py music/song.pcm build/song_nes.wav [--seconds 10]

An emulator cannot do this, having nothing on its controller port to send
the bytes. This runs the link ROM's stream routine on py65 (the tests'
console, tests/nes_harness.py) with the samples on its controller port as
a nesp32 would send them, takes every write to $4011 with the cycle it
landed on, and writes what the DAC would put out as a WAV file. So the levels, the DAC's curve and the few cycles by which the hunt
for a start bit moves each sample are all in what you hear; the console's
analog filters and the wire are not.

Needs the ROM built (make). A second of sound takes about two seconds, so
by default only the first 10 are played.
"""

import argparse
import os
import sys
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
for directory in (HERE, os.path.join(ROOT, "tests")):
    sys.path.insert(0, directory)

import pcm  # noqa: E402
import wav2pcm  # noqa: E402
from nes_harness import JOY2, Console  # noqa: E402

WAV_RATE = 44100
START = 500                     # cycles before the first start bit
FULL = 0.9                      # of the WAV's range that the DAC's takes
DEFAULT_SECONDS = 10.0


class Line:
    """Bytes back to back on D0, 8N2, from a cycle on: the line's level at
    any cycle."""

    def __init__(self, data, start, bit):
        self.data = data
        self.start = start
        self.bit = bit
        self.end = start + len(data) * pcm.FRAME_BITS * bit

    def level(self, cycle):
        if not self.start <= cycle < self.end:
            return 1
        index, within = divmod((cycle - self.start) / self.bit, pcm.FRAME_BITS)
        if within < 1:
            return 0                    # the start bit
        if within < 9:
            return (self.data[int(index)] >> int(within - 1)) & 1
        return 1                        # the two stop bits


def dac_writes(rom, labels, sound, clock_error=0.0):
    """Every (cycle, level) the stream routine writes for a sound."""
    machine = Console(rom, labels)
    machine.level_log = []
    line = Line(sound.samples + pcm.LAST_BYTE, START, sound.period / (1.0 + clock_error))
    # The port's buffer inverts D0, and the rest reads as the routines
    # count on. Every read is on its instruction's fourth cycle.
    machine.memory.subscribe_to_read(
        [JOY2], lambda address: pcm.PORT_IDLE | (line.level(machine.mpu.processorCycles + 3) ^ 1))
    # OUT0 at mark, where the ROM leaves it: the controller then shows
    # button A, which the routines look at, and it is up.
    machine._strobe = 1
    machine.call("pcm_stream_%d" % sound.rate, limit=line.end + 100000)
    return [(cycle, value & (pcm.LEVELS - 1)) for cycle, value in machine.level_log]


def render(writes, wav_rate=WAV_RATE):
    """The DAC's output as 16-bit samples: each is the mean of what the
    DAC held over its 1/wav_rate of a second."""
    if not writes:
        return []
    step = pcm.CPU_HZ / wav_rate
    out = []
    level = 0.0
    index = 0
    edge = float(writes[0][0])
    for _ in range(int((writes[-1][0] - edge) / step) + 1):
        area, at = 0.0, edge
        edge += step
        while index < len(writes) and writes[index][0] < edge:
            area += level * (writes[index][0] - at)
            at = writes[index][0]
            level = wav2pcm.DAC[writes[index][1]]
            index += 1
        area += level * (edge - at)
        value = (2 * area / step / wav2pcm.DAC[-1] - 1) * FULL
        out.append(int(round(value * 32767)))
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("source", help="a .pcm file")
    parser.add_argument("output", help="the WAV file to write")
    parser.add_argument("--seconds", type=float, default=DEFAULT_SECONDS,
                        help="how much of it to play (default %g)" % DEFAULT_SECONDS)
    parser.add_argument("--build", default=os.path.join(ROOT, "build"),
                        help="where jukebox_link.nes and its labels are")
    args = parser.parse_args(argv)
    with open(args.source, "rb") as handle:
        sound = pcm.Sound.from_bytes(handle.read())
    sound.samples = sound.samples[:int(args.seconds * pcm.sample_rate(sound.period))]
    writes = dac_writes(os.path.join(args.build, "jukebox_link.nes"),
                        os.path.join(args.build, "jukebox_link.labels"), sound)
    samples = render(writes)
    with wave.open(args.output, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(WAV_RATE)
        handle.writeframes(b"".join(sample.to_bytes(2, "little", signed=True)
                                    for sample in samples))
    print("%s: %d samples played, %.1f s" % (args.output, len(writes), len(samples) / WAV_RATE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
