#!/usr/bin/env python3
"""Make a sound track for the jukebox from a WAV file, or from a test tone.

    tools/wav2pcm.py song.wav music/song.pcm [--period 16] [--title "Game - Track"]
                                             [--seconds 30]
    tools/wav2pcm.py --tone 440 music/tone.pcm

For MP3 and other compressed files see tools/mp32pcm.py, which is also much
the faster of the two on a long file.

The console plays a byte as a sample, so a .pcm file (tools/pcm.py) is one
byte a sample at the rate the link runs at for sound (pcm.sample_rate:
10169 samples a second at 16 cycles a bit). This mixes the WAV down to one
channel, resamples it to that rate, makes it as loud as fits, and turns
each sample into the level for $4011 that puts the DAC nearest to it.

The DAC is not a straight line: the console's mixer squeezes the top of the
range, so level 127 gives 64% of 127 times level 1. dac_output is nesdev's
formula for it with the triangle and noise silent, and the levels are
chosen through it.

A file starts and ends at level 0, where the DAC rests, by a short ramp at
each end; without them the first and last samples would be clicks.

The title is what the console's screen shows, "game - track" as for music.
It defaults to the file's name.
"""

import argparse
import bisect
import math
import os
import sys
import wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pcm  # noqa: E402

RAMP_MS = 20
SINC_ZEROS = 8                  # zero crossings each side of the resampler's kernel
PASSBAND = 0.92                 # of the lower of the two Nyquist rates
TONE_SECONDS = 2.0
TONE_LEVEL = 0.8


def dac_output(level):
    """The mixer's output for a $4011 level, with the triangle and noise
    silent; 0 to about 0.57."""
    return 159.79 / (22638.0 / level + 100.0) if level else 0.0


DAC = [dac_output(level) for level in range(pcm.LEVELS)]


def nearest_level(fraction):
    """The level whose output is nearest to this fraction of full scale."""
    target = min(max(fraction, 0.0), 1.0) * DAC[-1]
    above = min(bisect.bisect_left(DAC, target), len(DAC) - 1)
    below = max(above - 1, 0)
    return below if target - DAC[below] <= DAC[above] - target else above


def read_wav(path):
    """(samples from -1 to 1, mixed to one channel; samples a second)."""
    with wave.open(path, "rb") as handle:
        channels, width, rate = handle.getnchannels(), handle.getsampwidth(), handle.getframerate()
        data = handle.readframes(handle.getnframes())
    if width not in (1, 2, 3):
        raise ValueError("%s: %d-bit samples are not supported" % (path, 8 * width))
    scale = float(1 << (8 * width - 1))
    values = []
    for offset in range(0, len(data) - width + 1, width):
        if width == 1:
            values.append((data[offset] - 128) / scale)     # 8-bit WAV is unsigned
        else:
            values.append(int.from_bytes(data[offset:offset + width], "little", signed=True) / scale)
    return [sum(values[start:start + channels]) / channels
            for start in range(0, len(values) - channels + 1, channels)], rate


def resample(samples, source_rate, rate):
    """Band-limited: a Hann-windowed sinc, cut off under the lower of the
    two rates' Nyquist."""
    if abs(source_rate - rate) < 1 or not samples:
        return list(samples)        # a decoder already did it (mp32pcm.py)
    cutoff = PASSBAND * min(1.0, rate / source_rate) / 2    # cycles a source sample
    half = SINC_ZEROS / (2 * cutoff)
    step = source_rate / rate
    out = []
    for index in range(int(len(samples) / step)):
        center = index * step
        total = weight = 0.0
        for k in range(max(0, int(center - half) + 1), min(len(samples), int(center + half) + 1)):
            t = k - center
            x = 2 * math.pi * cutoff * t
            w = (math.sin(x) / x if x else 1.0) * (0.5 + 0.5 * math.cos(math.pi * t / half))
            total += samples[k] * w
            weight += w
        out.append(total / weight if weight else 0.0)
    return out


def tone(hertz, rate, seconds=TONE_SECONDS):
    return [TONE_LEVEL * math.sin(2 * math.pi * hertz * index / rate)
            for index in range(int(seconds * rate))]


def to_levels(samples, rate):
    """Samples from -1 to 1 at the link's rate, as levels for $4011: made
    as loud as fits, with a ramp from and to level 0."""
    peak = max((abs(sample) for sample in samples), default=0.0)
    gain = 1.0 / peak if peak else 0.0
    fractions = [(sample * gain + 1.0) / 2 for sample in samples] or [0.0]
    ramp = max(1, int(rate * RAMP_MS / 1000))
    rise = [fractions[0] * step / ramp for step in range(ramp)]
    fall = [fractions[-1] * (ramp - 1 - step) / ramp for step in range(ramp)]
    return [nearest_level(fraction) for fraction in rise + fractions + fall]


def convert(samples, source_rate, period=pcm.DEFAULT_PERIOD, title="", seconds=None):
    """A pcm.Sound for samples from -1 to 1, or for the first seconds of
    them. The cut is made before the loudness and the ramps are worked
    out, so a shortened sound still ends at level 0."""
    rate = pcm.sample_rate(period)
    if seconds is not None:
        samples = samples[:int(seconds * source_rate)]
    levels = to_levels(resample(samples, source_rate, rate), rate)
    return pcm.Sound(title, period, pcm.encode(levels))


def title_of(path):
    return os.path.splitext(os.path.basename(path))[0]


def from_wav(path, period=pcm.DEFAULT_PERIOD, title=None, seconds=None):
    samples, source_rate = read_wav(path)
    return convert(samples, source_rate, period, title_of(path) if title is None else title,
                   seconds)


def add_arguments(parser):
    """The arguments this tool and mp32pcm.py share."""
    parser.add_argument("--period", type=int, default=pcm.DEFAULT_PERIOD, choices=pcm.PERIODS,
                        help="cycles a bit on the link (default %d)" % pcm.DEFAULT_PERIOD)
    parser.add_argument("--title", help="for the console's screen (default: the file's name)")
    parser.add_argument("--seconds", type=float,
                        help="keep only this much from the start (default: all of it)")


def write(sound, path):
    with open(path, "wb") as handle:
        handle.write(sound.to_bytes())
    rate = pcm.sample_rate(sound.period)
    print("%s: %d samples, %.1f s at %d a second (%d baud), %d KB"
          % (path, len(sound.samples), len(sound.samples) / rate, round(rate),
             pcm.baud(sound.period), (len(sound.samples) + 1023) // 1024))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("source", nargs="?", help="a WAV file")
    parser.add_argument("output", help="the .pcm file to write")
    add_arguments(parser)
    parser.add_argument("--tone", type=float, metavar="HZ",
                        help="a %g second test tone, with no WAV file" % TONE_SECONDS)
    args = parser.parse_args(argv)
    if (args.source is None) == (args.tone is None):
        parser.error("give a WAV file or --tone, not both")
    if args.tone is not None:
        rate = pcm.sample_rate(args.period)
        title = "%d Hz tone" % args.tone if args.title is None else args.title
        sound = convert(tone(args.tone, rate), rate, args.period, title)
    else:
        sound = from_wav(args.source, args.period, args.title, args.seconds)
    write(sound, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
