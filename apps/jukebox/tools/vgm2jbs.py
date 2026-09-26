#!/usr/bin/env python3
"""Convert NES .vgm/.vgz rips into .jbs jukebox streams.

    tools/vgm2jbs.py music/*.vgz --out-dir build/jbs
    tools/vgm2jbs.py song.vgm -o song.jbs --report song.json

Pipeline:

1. vgm.parse pulls out the 2A03 register writes with sample timestamps.
2. normalize puts each write on the frame grid, drops what v1 cannot play
   (DMC samples, raw PCM through $4011), forces $4017 bit 6 (frame IRQ off, so the receiver is never
   interrupted), and rescales PAL periods to NTSC pitch.
3. jbs.encode merges, deduplicates and orders each frame's writes under the
   APU write-order model and emits the stream.

The frame grid is VGM's own 735 samples (1/60 s). The console runs at
60.0988 Hz, so playback is 0.16% fast, which nobody can hear. The benefit
is that rips logged once per frame map one to one onto console frames, with
no merged or skipped frames. PAL rips (882 samples per frame) land on the
same grid by timestamp, which keeps their tempo.
"""

import argparse
import json
import os
import sys
from collections import Counter

import apu_model
import jbs
import vgm

FRAME_SAMPLES = 735
PAL_TO_NTSC = vgm.NTSC_CLOCK / vgm.PAL_CLOCK

STATUS_CHANNELS = 0x0F  # $4015 bit 4 is DMC, dropped in v1
FRAME_IRQ_INHIBIT = 0x40
DMC_LEVEL_MASK = 0x7F

# More $4011 writes than this in one frame is raw PCM (voices, drums), which
# no link can stream. The occasional level set is kept; see apu_model.
MAX_DMC_LEVEL_WRITES_PER_FRAME = 4

NTSC_NOISE_PERIODS = (4, 8, 16, 32, 64, 96, 128, 160, 202, 254, 380, 508, 762, 1016, 2034, 4068)
PAL_NOISE_PERIODS = (4, 8, 14, 30, 60, 88, 118, 148, 188, 236, 354, 472, 708, 944, 1890, 3778)

# (low register, high register) for each timer whose period the rescale
# rewrites. The pulse timer mutes below 8, so those periods are left alone.
PERIOD_TIMERS = ((0x02, 0x03), (0x06, 0x07), (0x0A, 0x0B))
PULSE_MUTE_BELOW = 8
MAX_PERIOD = 0x7FF
NOISE_PERIOD = 0x0E


def frame_of(sample):
    return (sample + FRAME_SAMPLES // 2) // FRAME_SAMPLES


def normalize(song, pal_rescale=True):
    """Return (frames, loop_frame, stats) for a parsed NesVgm."""
    stats = Counter()
    rescaler = PalRescaler(stats) if pal_rescale and song.is_pal else None
    last_frame = frame_of(song.writes[-1].sample) if song.writes else 0
    total = max(frame_of(song.total_samples), last_frame + 1)
    frames = [[] for _ in range(total)]
    level_writes = Counter(
        frame_of(write.sample) for write in song.writes if write.register == apu_model.DMC_LEVEL
    )
    for write in song.writes:
        register, value = write.register, write.value
        if register not in apu_model.STREAMED_REGISTERS:
            stats["dropped_%s" % _dropped_name(register)] += 1
            continue
        if register == apu_model.DMC_LEVEL:
            if level_writes[frame_of(write.sample)] > MAX_DMC_LEVEL_WRITES_PER_FRAME:
                stats["dropped_dmc_pcm_4011"] += 1
                continue
            value &= DMC_LEVEL_MASK
        elif register == apu_model.STATUS:
            if value & ~STATUS_CHANNELS & 0x1F:
                stats["dmc_enable_cleared"] += 1
            value &= STATUS_CHANNELS
        elif register == apu_model.FRAME_COUNTER:
            value |= FRAME_IRQ_INHIBIT
        frame = frames[frame_of(write.sample)]
        if rescaler:
            frame.extend(rescaler.write(register, value))
        else:
            frame.append((register, value))

    for writes in frames:
        registers = [register for register, _ in writes]
        if len(registers) != len(set(registers)):
            stats["frames_with_repeated_register"] += 1

    loop_frame = None
    if song.loop_start_sample is not None:
        loop_frame = frame_of(song.loop_start_sample)
        if loop_frame >= total:
            loop_frame = None
            stats["loop_past_end"] += 1
    return frames, loop_frame, stats


def _dropped_name(register):
    if 0x10 <= register <= 0x13:
        return "dmc_%04X" % (0x4000 + register)
    return "%04X" % (0x4000 + register)


class PalRescaler:
    """Rewrite PAL timer periods so they play at the right NTSC pitch.

    A period spans a low and a high register, and writing the high register
    restarts the note. When a rescaled high byte changes because of a low
    byte write alone, it cannot be written without a spurious retrigger, so
    the high bits stay put and the mismatch is counted. That only happens
    when a pitch slide crosses a 256-period boundary.
    """

    def __init__(self, stats):
        self.stats = stats
        self.source = {}  # register -> value as the rip wrote it
        self.console = {}  # register -> last rescaled value written

    def write(self, register, value):
        for low, high in PERIOD_TIMERS:
            if register in (low, high):
                return self._timer(low, high, register, value)
        if register == NOISE_PERIOD:
            index = _nearest_noise_index(value & 0x0F)
            return [(register, (value & 0xF0) | index)]
        return [(register, value)]

    def _timer(self, low, high, register, value):
        self.source[register] = value
        period = (self.source.get(high, 0) & 0x07) << 8 | self.source.get(low, 0)
        scaled = _rescale_period(period, pulse=high != 0x0B)
        new_low = scaled & 0xFF
        writes = []
        if register == high:
            # Always pair the low byte with it. The encoder drops it when the
            # console already holds it, and it knows about loop re-entry,
            # which this class does not.
            writes.append((low, new_low))
            writes.append((high, (value & 0xF8) | scaled >> 8))
        else:
            writes.append((low, new_low))
            held_high = self.console.get(high)
            if held_high is not None and held_high & 0x07 != scaled >> 8:
                self.stats["pal_period_high_mismatch"] += 1
        self.console.update(writes)
        return writes


def _rescale_period(period, pulse):
    if pulse and period < PULSE_MUTE_BELOW:
        return period
    return min(MAX_PERIOD, round((period + 1) * PAL_TO_NTSC) - 1)


def _nearest_noise_index(pal_index):
    # Same pitch means the same clock / period, so compare ratios.
    target = vgm.NTSC_CLOCK / (vgm.PAL_CLOCK / PAL_NOISE_PERIODS[pal_index])
    return min(range(16), key=lambda i: abs(NTSC_NOISE_PERIODS[i] / target - 1))


def convert(song, pal_rescale=True):
    """Return (JbsFile, report dict)."""
    frames, loop_frame, stats = normalize(song, pal_rescale)
    encoded = jbs.encode(frames, loop_frame)
    title = " - ".join(part for part in (song.game, song.title) if part)
    jbs_file = jbs.JbsFile(
        stream=encoded.data,
        total_frames=len(frames),
        loop_frame=loop_frame,
        loop_offset=encoded.loop_offset,
        pal_source=song.is_pal,
        title=title,
    )
    return jbs_file, _report(song, frames, loop_frame, encoded, stats, title)


def _report(song, frames, loop_frame, encoded, stats, title):
    per_frame = encoded.frame_bytes
    ordered = sorted(per_frame)
    window = 60
    worst_window = max(
        (sum(per_frame[i:i + window]) for i in range(max(1, len(per_frame) - window + 1))),
        default=0,
    )
    return {
        "title": title,
        "clock": song.clock,
        "pal_source": song.is_pal,
        "fds": song.fds,
        "frames": len(frames),
        "seconds": round(len(frames) / 60.0988, 2),
        "loop_frame": loop_frame,
        "loop_offset": encoded.loop_offset,
        "stream_bytes": len(encoded.data),
        "vgm_apu_writes": len(song.writes),
        "bytes_per_frame_mean": round(len(encoded.data) / max(1, len(frames)), 2),
        "bytes_per_frame_p99": ordered[int(0.99 * (len(ordered) - 1))] if ordered else 0,
        "bytes_per_frame_max": ordered[-1] if ordered else 0,
        "worst_60_frames_bytes": worst_window,
        "skipped_vgm": dict(song.skipped),
        "normalize": dict(stats),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("inputs", nargs="+", help=".vgm or .vgz files")
    parser.add_argument("-o", "--output", help="output .jbs (single input only)")
    parser.add_argument("--out-dir", help="directory for .jbs files (default: beside input)")
    parser.add_argument("--report", help="write the JSON report here (single input only)")
    parser.add_argument("--no-pal-rescale", action="store_true",
                        help="leave PAL periods as ripped")
    args = parser.parse_args(argv)
    if len(args.inputs) > 1 and (args.output or args.report):
        parser.error("-o and --report take a single input")

    failed = 0
    for path in args.inputs:
        try:
            song = vgm.load(path)
        except (OSError, vgm.VgmError) as error:
            print("%s: %s" % (path, error), file=sys.stderr)
            failed += 1
            continue
        jbs_file, report = convert(song, pal_rescale=not args.no_pal_rescale)
        output = args.output or _output_path(path, args.out_dir)
        with open(output, "wb") as handle:
            handle.write(jbs_file.to_bytes())
        if args.report:
            with open(args.report, "w") as handle:
                json.dump(report, handle, indent=2)
                handle.write("\n")
        print(
            "%s -> %s: %d frames, %d bytes, %.1f B/frame mean, p99 %d, max %d, worst 1 s %d"
            % (
                path,
                output,
                report["frames"],
                report["stream_bytes"],
                report["bytes_per_frame_mean"],
                report["bytes_per_frame_p99"],
                report["bytes_per_frame_max"],
                report["worst_60_frames_bytes"],
            )
        )
        dropped = {**report["skipped_vgm"], **report["normalize"]}
        if dropped:
            print("    " + ", ".join("%s=%d" % item for item in sorted(dropped.items())))
    return 1 if failed else 0


def _output_path(path, out_dir):
    base = os.path.basename(path)
    for suffix in (".vgz", ".vgm"):
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)]
    directory = out_dir if out_dir else os.path.dirname(path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    return os.path.join(directory, base + ".jbs")


if __name__ == "__main__":
    sys.exit(main())
