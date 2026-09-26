#!/usr/bin/env python3
"""Write a short original looping tune as a .jbs, so the ROM builds and the
tests run without any copyrighted rips.

    tools/demo_song.py -o build/demo.jbs

Pulse 1 arpeggiates C, Am, F, G with a volume decay written every frame,
the triangle holds the bass, and the noise channel ticks on every other
step. That is roughly the register traffic of a real game's sound engine.
"""

import argparse
import sys

import jbs

CPU_HZ = 1789773
FRAMES_PER_STEP = 8

C3, E3, F3, G3, A3, B3 = 130.81, 164.81, 174.61, 196.00, 220.00, 246.94
C4, D4, E4, F4, G4, A4 = 261.63, 293.66, 329.63, 349.23, 392.00, 440.00
F2, G2, A2 = 87.31, 98.00, 110.00

CHORDS = (  # (arpeggio notes, triangle bass)
    ((C4, E4, G4, 2 * C4), C3),
    ((A3, C4, E4, A4), A2),
    ((F3, A3, C4, F4), F2),
    ((G3, B3, D4, G4), G2),
)
PATTERN = (0, 1, 2, 3, 2, 1, 0, 1)


def pulse_period(hz):
    return round(CPU_HZ / (16 * hz)) - 1


def triangle_period(hz):
    return round(CPU_HZ / (32 * hz)) - 1


def demo_frames():
    frames = [[(0x15, 0x0F), (0x17, 0x40), (0x01, 0x08)]]
    for notes, bass in CHORDS:
        for step, index in enumerate(PATTERN):
            for tick in range(FRAMES_PER_STEP):
                frame = []
                if tick == 0:
                    period = pulse_period(notes[index])
                    frame += [(0x00, 0xBF), (0x02, period & 0xFF), (0x03, 0x08 | period >> 8)]
                    if step == 0:
                        period = triangle_period(bass)
                        frame += [(0x08, 0xFF), (0x0A, period & 0xFF), (0x0B, 0x08 | period >> 8)]
                    if step % 2 == 0:
                        frame += [(0x0C, 0x38), (0x0E, 0x03), (0x0F, 0x08)]
                else:
                    frame.append((0x00, 0xB0 | max(0, 15 - 2 * tick)))
                    if step % 2 == 0:
                        frame.append((0x0C, 0x30 | max(0, 8 - 3 * tick)))
                frames.append(frame)
    return frames


def demo_song():
    frames = demo_frames()
    encoded = jbs.encode(frames, loop_frame=1)
    return jbs.JbsFile(
        stream=encoded.data,
        total_frames=len(frames),
        loop_frame=1,
        loop_offset=encoded.loop_offset,
        title="NES Jukebox - Demo Arpeggio",
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args(argv)
    with open(args.output, "wb") as handle:
        handle.write(demo_song().to_bytes())
    return 0


if __name__ == "__main__":
    sys.exit(main())
