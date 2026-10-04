#!/usr/bin/env python3
"""Make a sound track for the jukebox from an MP3 file.

    tools/mp32pcm.py song.mp3 music/song.pcm [--period 16] [--title "Game - Track"]
                                             [--seconds 30]

This has no MP3 decoder of its own. It runs one that is on the computer,
ffmpeg if there is one and otherwise macOS's afconvert, and has it write a
WAV file with one channel at the rate the link plays sound at. The rest is
tools/wav2pcm.py: the loudness, the DAC's curve, and the ramps at each end.

So it takes whatever that decoder reads, not only MP3: AAC, FLAC, and WAV
files too, which it converts much faster than wav2pcm.py's own resampler
does.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pcm  # noqa: E402
import wav2pcm  # noqa: E402


def decoder_command(source, output, rate, which=shutil.which):
    """The command that decodes source to a 16-bit WAV of one channel at
    rate samples a second, or None if this computer has no decoder."""
    if which("ffmpeg"):
        return ["ffmpeg", "-v", "error", "-y", "-i", source, "-vn", "-ac", "1",
                "-ar", str(rate), "-c:a", "pcm_s16le", output]
    if which("afconvert"):
        return ["afconvert", "-f", "WAVE", "-d", "LEI16@%d" % rate, "-c", "1", source, output]
    return None


def decode(source, rate, run=subprocess.run, which=shutil.which):
    """(samples from -1 to 1, samples a second) for a compressed file."""
    if not os.path.exists(source):
        raise ValueError("%s: no such file" % source)
    with tempfile.TemporaryDirectory() as scratch:
        output = os.path.join(scratch, "decoded.wav")
        command = decoder_command(source, output, rate, which)
        if command is None:
            raise ValueError("no decoder: install ffmpeg (macOS has afconvert)")
        done = run(command, capture_output=True, text=True)
        if done.returncode or not os.path.exists(output):
            raise ValueError("%s: %s could not decode it: %s" % (
                source, command[0], (done.stderr or done.stdout or "no output").strip()))
        return wav2pcm.read_wav(output)


def from_file(path, period=pcm.DEFAULT_PERIOD, title=None, seconds=None, **decoder):
    """A pcm.Sound for a compressed file, or for its first seconds."""
    samples, rate = decode(path, round(pcm.sample_rate(period)), **decoder)
    return wav2pcm.convert(samples, rate, period,
                           wav2pcm.title_of(path) if title is None else title, seconds)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("source", help="an MP3 file, or anything else the decoder reads")
    parser.add_argument("output", help="the .pcm file to write")
    wav2pcm.add_arguments(parser)
    args = parser.parse_args(argv)
    try:
        sound = from_file(args.source, args.period, args.title, args.seconds)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    wav2pcm.write(sound, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
