#!/usr/bin/env python3
"""Hear a sound track as the console would play it, without a console.

    tools/pcm_preview.py music/song.pcm build/song_nes.wav [--seconds 10]

An emulator cannot do this, having nothing on its controller port to send
the bytes. This runs the link ROM's stream routine on py65 with the tests'
model of the line (tests/link_harness.py), takes every write to $4011 with
the cycle it landed on, and writes what the DAC would put out as a WAV
file. So the levels, the DAC's curve and the few cycles by which the hunt
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
for directory in (HERE, os.path.join(ROOT, "host"), os.path.join(ROOT, "tests")):
    sys.path.insert(0, directory)

import pcm  # noqa: E402
import wav2pcm  # noqa: E402
from link_harness import LinkConsole  # noqa: E402

WAV_RATE = 44100
START = 500                     # cycles before the first start bit
FULL = 0.9                      # of the WAV's range that the DAC's takes
DEFAULT_SECONDS = 10.0


def dac_writes(rom, labels, sound, clock_error=0.0):
    """Every (cycle, level) the stream routine writes for a sound."""
    machine = LinkConsole(rom, labels)
    machine.level_log = []
    bit = sound.period / (1.0 + clock_error)
    end = machine.to_nes.send(sound.samples + pcm.LAST_BYTE, START, bit=bit)
    machine.call("pcm_stream_%d" % sound.rate, limit=end + 100000)
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
