"""The player ROM, run on py65, against the Python decoder.

Every NMI's APU writes must equal the decoder's frame, in order. NMIs that
found the ring dry are allowed (they write nothing and are counted), but
they may only delay the song, never change it.
"""

import glob
import itertools
import os
import random
import shutil
import subprocess

import pytest

import apu_model
import jbs
import vgm
import vgm2jbs
from nes_harness import NTSC_FRAME_CYCLES, Console, expected_frames

ROOT = os.path.join(os.path.dirname(__file__), "..")
RIPS = sorted(glob.glob(os.path.join(ROOT, "music", "*.vg[mz]")))

# The NMI must leave most of the frame to the link. Measured on real rips:
# steady play stays under about 1 ms, and only a song's opening frame, where
# a game's init writes 20+ registers in order, runs to about 3 ms. PLAN.md
# budgets phase 3 from these.
NMI_P99_BUDGET = 2000
NMI_MAX_BUDGET = 6000


def assert_nmi_budget(machine):
    cycles = sorted(machine.nmi_cycles)
    assert cycles[int(0.99 * (len(cycles) - 1))] <= NMI_P99_BUDGET
    assert cycles[-1] <= NMI_MAX_BUDGET

pytestmark = pytest.mark.skipif(
    not (shutil.which("ca65") and shutil.which("ld65")), reason="cc65 not installed"
)


@pytest.fixture(scope="session")
def rom(tmp_path_factory):
    build = tmp_path_factory.mktemp("build")
    subprocess.run(["make", "-s", "BUILD=%s" % build, "verify"], cwd=ROOT, check=True)
    return str(build / "jukebox.nes"), str(build / "jukebox.labels")


def console(rom):
    return Console(*rom)


def assert_plays(machine, stream, loop_offset, count):
    played = machine.played_frames()
    assert len(played) >= count
    expected = list(itertools.islice(expected_frames(stream, loop_offset), count))
    for index, (got, want) in enumerate(zip(played, expected)):
        assert got == want, "frame %d" % index
    assert machine.byte("stream_error") == 0


def test_boot_silences_the_apu_and_inhibits_the_frame_irq(rom):
    machine = console(rom)
    machine.run(1)
    assert machine.reset_writes == [(0x17, 0x40), (0x10, 0x00), (0x15, 0x00)]


def test_demo_song_plays_on_the_frame_clock(rom):
    machine = console(rom)
    machine.run_until_played(700)
    with open(os.path.join(os.path.dirname(rom[0]), "demo.jbs"), "rb") as handle:
        demo = jbs.JbsFile.from_bytes(handle.read())
    assert machine.word("underruns") == 0
    assert_plays(machine, demo.stream, demo.loop_offset, 700)
    assert_nmi_budget(machine)


def random_song(seed, frames=150, max_writes=10):
    rng = random.Random(seed)
    registers = sorted(apu_model.STREAMED_REGISTERS)
    values = (0x00, 0x08, 0x30, 0x80, 0x8F, 0xFF)
    song = []
    for _ in range(frames):
        if rng.random() < 0.3:
            song.append([])
            continue
        frame = []
        for _ in range(rng.randint(1, max_writes)):
            register = rng.choice(registers)
            value = rng.randint(0, 15) if register == 0x15 else rng.choice(values)
            frame.append((register, value))
        song.append(frame)
    loop_frame = rng.choice([None, 0, rng.randrange(frames)])
    encoded = jbs.encode(song, loop_frame)
    return encoded.data, (encoded.loop_offset if loop_frame is not None else None)


@pytest.mark.parametrize("seed", range(12))
def test_random_streams_survive_nmis_at_any_instruction(rom, seed):
    # NMIs every few hundred to few thousand cycles land inside feed, inside
    # the tail commit, and inside head reads, and starve the ring so frames
    # split across top-ups. None of it may change what gets played.
    stream, loop_offset = random_song(seed)
    machine = console(rom)
    machine.load_song(stream, loop_offset)
    rng = random.Random(1000 + seed)
    # A 32-byte top-up takes about 1400 cycles, so NMIs this close together
    # leave the main loop too little time to keep up.
    while len(machine.played_frames()) < 300 and len(machine.frames) < 20000:
        machine.run(100, period=lambda: rng.randint(20, 400))
    if loop_offset is not None:
        # A song without a loop is about 1 KB and nearly all of it fits in
        # the ring at prefill, so only looping ones are sure to run dry.
        assert machine.word("underruns") > 0
    assert_plays(machine, stream, loop_offset, 300)


@pytest.mark.parametrize("window", ["tail_commit_high", "head_read_low"])
@pytest.mark.parametrize("seed", range(3))
def test_nmis_inside_the_ring_handoff_windows(rom, window, seed):
    # tail_commit_high is between the two stores that publish tail. An NMI
    # reading tail there sees the new low byte with the old high byte, which
    # on a page-crossing commit points past real data. head_read_low is
    # between the main loop's reads of head's two bytes. Fire an NMI at the
    # window on every pass, with the ring starved and frames big enough
    # (up to 40 writes) to run past the real tail when the limit is wrong.
    stream, _ = random_song(seed, max_writes=40)
    loop_offset = 2
    machine = console(rom)
    machine.load_song(stream, loop_offset)
    rng = random.Random(2000 + seed)
    while len(machine.played_frames()) < 150 and len(machine.frames) < 20000:
        machine.run(100, period=lambda: rng.randint(20, 400), interrupt_at=[window])
    assert machine.word("underruns") > 0
    assert_plays(machine, stream, loop_offset, 150)


def test_a_song_without_a_loop_ends_in_silence(rom):
    frames = [[(0x15, 0x0F)], [(0x00, 0xBF), (0x03, 0x08)], []]
    stream = jbs.encode(frames).data
    machine = console(rom)
    machine.load_song(stream)
    machine.run_until_played(10)
    assert_plays(machine, stream, None, 10)
    assert machine.byte("ended") == 1


def test_a_malformed_stream_stops_playback(rom):
    stream = bytes([0x80, 0x01, 0x81, 0x00, 0x30, 0x01])  # empty pulse submask
    machine = console(rom)
    machine.load_song(stream, loop_offset=2)
    machine.run(5)
    assert machine.byte("stream_error") == 1
    assert machine.byte("ended") == 1
    assert [(0x15, 0x00)] in [writes for writes, _, _ in machine.frames]


@pytest.mark.skipif(not RIPS, reason="no rips in music/")
@pytest.mark.parametrize("path", RIPS, ids=os.path.basename)
def test_rips_play_frame_exact(rom, path):
    song, _ = vgm2jbs.convert(vgm.load(path))
    loop_offset = song.loop_offset if song.loop_frame is not None else None
    machine = console(rom)
    machine.load_song(song.stream, loop_offset)
    count = min(song.total_frames + 200, 3000)
    machine.run_until_played(count)
    assert machine.word("underruns") == 0
    assert_plays(machine, song.stream, loop_offset, count)
    assert_nmi_budget(machine)
