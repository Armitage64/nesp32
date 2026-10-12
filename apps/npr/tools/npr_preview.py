#!/usr/bin/env python3
"""Hear the station as the console would play it, without a console or a
nesp32.

    tools/npr_preview.py --live 20 build/npr_nes.wav    the station, for 20 seconds
    tools/npr_preview.py some.mp3 build/some_nes.wav    or any MP3

The stream goes through nesp32's own TUNER service, built for this
computer (make -C ../.. host): its decoder, its resampler and its levels
for the console's DAC. What it then puts on the line, a byte a sample, is
written out as a WAV file of what the DAC would put out for each, at the
rate the line carries them. The console's own part is left out, since it
changes nothing: it writes each byte it receives to the DAC (the tests
hold it to that). Its analog filters are not modelled.
"""

import argparse
import os
import struct
import sys
import time
import urllib.request
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
NESP32 = os.path.abspath(os.environ.get("NESP32", os.path.join(HERE, "..", "..", "..")))
BUILD = os.environ.get("NESP_BUILD", os.path.join(NESP32, "build"))
for directory in (os.path.join(NESP32, "host"), BUILD,
                  os.path.join(HERE, "..", "..", "jukebox", "tools")):
    sys.path.insert(0, directory)

import nesp  # noqa: E402
import nesp_proto as p  # noqa: E402
import pcm  # noqa: E402
import wav2pcm  # noqa: E402

STATION = "https://npr-ice.streamguys1.com/live.mp3"
AGENT = "nesp32-npr/0.1 (NPR on a NES; a preview on a computer)"
PIECE = 1024                    # bytes of the stream at a time, as a fetch brings them
FULL = 0.9                      # of the WAV's range that the DAC's takes
RATE = pcm.sample_rate(p.NESP_TUNER_PERIOD)


def live(seconds):
    """The station's stream for this long."""
    request = urllib.request.Request(STATION, headers={"User-Agent": AGENT})
    data = bytearray()
    until = time.monotonic() + seconds
    with urllib.request.urlopen(request, timeout=10) as reply:
        while time.monotonic() < until:
            data += reply.read(PIECE)
    return bytes(data)


def play(stream):
    """What the nesp32 puts on the line for a stream, and how its ring
    fared: (the bytes, times dry, samples dropped)."""
    stick = nesp.Stick()
    stick.set_wifi(p.NESP_WIFI_JOINED)
    stick.line.room = 64        # a UART takes a little at a time
    clock = [0]

    def wait(ms):
        for _ in range(ms):
            clock[0] += 1
            stick.tick(clock[0])

    def ask(op, payload=b""):
        reply = stick.ask(p.NESP_SVC_TUNER, op, payload)
        wait(5)
        return reply.payload

    assert stick.hello(app=b"NPR ", services=[p.NESP_SVC_RAW, p.NESP_SVC_TUNER]).ok
    ask(p.NESP_TUNER_PLAY)
    at = 0
    while ask(p.NESP_TUNER_STATE)[0] == p.NESP_TUNER_TUNING and at < len(stream):
        stick.fetch_body(stream[at:at + PIECE])
        at += PIECE
    if ask(p.NESP_TUNER_SOUND, bytes((p.NESP_TUNER_RATE,)))[1] != p.NESP_SOUND_GO:
        raise SystemExit("not enough of it is MP3 to play")
    # The rest as the ring has room for it, as a station's own pace would
    # bring it; then the stream is lost, and what is held is played out.
    ended = False
    while stick.raw_state == p.NESP_RUN_ARMED or stick.raw_state == p.NESP_RUN_RUNNING:
        while at < len(stream) and stick.tuner_held < 4 * RATE:
            stick.fetch_body(stream[at:at + PIECE])
            at += PIECE
        if at >= len(stream) and not ended:
            stick.fetch_done(False, b"THE END")
            ended = True
        wait(1)
    return bytes(stick.line.sent), stick.tuner_dry, stick.tuner_dropped


def write_wav(path, sent):
    levels = pcm.decode(sent)
    top = wav2pcm.DAC[-1]
    frames = b"".join(struct.pack("<h", int(round((2 * wav2pcm.DAC[level] / top - 1)
                                                  * FULL * 32767)))
                      for level in levels)
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(round(RATE)))
        handle.writeframes(frames)
    return len(levels)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("mp3", nargs="?", help="an MP3 file, in place of the station")
    parser.add_argument("wav", help="the WAV file to write")
    parser.add_argument("--live", type=float, metavar="SECONDS",
                        help="fetch the station for this long")
    args = parser.parse_args(argv)
    if (args.mp3 is None) == (args.live is None):
        parser.error("give an MP3 file or --live, not both")
    if args.mp3 is not None:
        with open(args.mp3, "rb") as handle:
            stream = handle.read()
    else:
        stream = live(args.live)
    sent, dry, dropped = play(stream)
    count = write_wav(args.wav, sent)
    print("%s: %.1f seconds at %d samples a second, 7 bits; the ring ran dry %d times and "
          "dropped %d samples" % (args.wav, count / RATE, round(RATE), dry, dropped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
