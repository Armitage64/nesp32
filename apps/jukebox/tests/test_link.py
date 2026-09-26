"""The link ROM against the Python host over the simulated serial line.

The music must come out frame-exact whatever the line does: the NES may
play later than it would have (an underrun holds the notes for a frame), but
it must never play something different. The link counters say which
recovery path each fault took.
"""

import glob
import itertools
import os
import random
import shutil
import subprocess

import pytest

import jbs
import vgm
import vgm2jbs
from link_harness import LinkConsole, ms
from nes_harness import NTSC_FRAME_CYCLES, expected_frames
from protocol import Host, OP_DATA, OP_HELLO
from serial_line import HostToNes, NesToHost

ROOT = os.path.join(os.path.dirname(__file__), "..")
RIPS = sorted(glob.glob(os.path.join(ROOT, "music", "*.vg[mz]")))

pytestmark = pytest.mark.skipif(
    not (shutil.which("ca65") and shutil.which("ld65")), reason="cc65 not installed"
)


@pytest.fixture(scope="session")
def build(tmp_path_factory):
    build = tmp_path_factory.mktemp("link_system")
    subprocess.run(["make", "-s", "BUILD=%s" % build, "verify"], cwd=ROOT, check=True)
    return build


@pytest.fixture(scope="session")
def link_rom(build):
    return str(build / "jukebox_link.nes"), str(build / "jukebox_link.labels")


@pytest.fixture(scope="session")
def demo(build):
    return jbs.JbsFile.from_bytes((build / "demo.jbs").read_bytes())


def loop_offset(song):
    return song.loop_offset if song.loop_frame is not None else None


def played_exactly(machine, song, count):
    machine.run_until_played(count)
    expected = itertools.islice(expected_frames(song.stream, loop_offset(song)), count)
    for index, (got, want) in enumerate(zip(machine.played_frames(), expected)):
        assert got == want, "frame %d" % index
    assert machine.byte("stream_error") == 0


def counters(machine):
    names = ("link_bursts", "link_aborts", "link_rejects", "link_crc_errors", "underruns")
    return {name: machine.word(name) for name in names}


def test_clean_link_plays_frame_exact(link_rom, demo):
    machine = LinkConsole(*link_rom, host=Host(demo))
    played_exactly(machine, demo, 600)
    stats = counters(machine)
    assert stats["link_aborts"] == stats["link_rejects"] == stats["link_crc_errors"] == 0
    assert stats["underruns"] == 0
    assert machine.requests[0][1].op == OP_HELLO
    assert machine.host.stats["resends"] == 0


def test_playback_waits_for_the_prefill(link_rom, demo):
    machine = LinkConsole(*link_rom, host=Host(demo))
    machine.run(20)
    assert machine.byte("playing") == 0      # 20 bursts of 24 is under 768
    machine.run_until_played(1)
    assert len(machine.frames) < 40


def test_no_host_means_no_playback_and_no_hang(link_rom):
    machine = LinkConsole(*link_rom)
    machine.run(30)
    assert machine.byte("playing") == 0
    data = [r for _, r in machine.requests if r.op == OP_DATA]
    assert len(data) >= 29 and {r.seq for r in data} == {0}
    # Each hunt is cut off by the next NMI, except the one still waiting.
    assert machine.word("link_aborts") >= len(data) - 1


@pytest.mark.parametrize("turnaround_ms", [2, 5])
def test_turnaround_inside_the_budget_never_aborts(link_rom, demo, turnaround_ms):
    machine = LinkConsole(*link_rom, host=Host(demo), turnaround=lambda: ms(turnaround_ms))
    played_exactly(machine, demo, 300)
    assert counters(machine)["link_aborts"] == 0


def test_turnaround_budget_is_reported(link_rom, demo):
    """The longest host turnaround at which a full-credit burst still lands
    before the next NMI, for PLAN.md's budget."""
    best = 0.0
    for tenths in range(40, 120, 5):
        turnaround = tenths / 10
        machine = LinkConsole(*link_rom, host=Host(demo), turnaround=lambda: ms(turnaround))
        machine.run(80)  # prefill: every burst asks for the full credit
        if machine.word("link_aborts"):
            break
        best = turnaround
    print("\nfull-credit bursts land before the NMI with turnaround up to %.1f ms" % best)
    assert best >= 5.0


def test_a_late_host_is_cut_off_and_resent(link_rom, demo):
    rng = random.Random(1)
    machine = LinkConsole(*link_rom, host=Host(demo), turnaround=lambda: ms(rng.uniform(1, 16)))
    played_exactly(machine, demo, 400)
    stats = counters(machine)
    assert stats["link_aborts"] > 0
    assert machine.host.stats["resends"] > 0


def flip_random_bit(rng, rate):
    def fault(reply):
        if rng.random() >= rate:
            return reply
        data = bytearray(reply)
        data[rng.randrange(len(data))] ^= 1 << rng.randrange(8)
        return bytes(data)
    return fault


def drop_random_byte(rng, rate):
    def fault(reply):
        if rng.random() >= rate:
            return reply
        index = rng.randrange(len(reply))
        return reply[:index] + reply[index + 1:]
    return fault


def test_corrupted_bursts_are_rejected_and_resent(link_rom, demo):
    rng = random.Random(2)
    machine = LinkConsole(*link_rom, host=Host(demo), reply_fault=flip_random_bit(rng, 0.1))
    played_exactly(machine, demo, 500)
    stats = counters(machine)
    assert stats["link_crc_errors"] + stats["link_rejects"] + stats["link_aborts"] > 0
    assert machine.host.stats["resends"] > 0


def test_dropped_burst_bytes_are_recovered(link_rom, demo):
    rng = random.Random(3)
    machine = LinkConsole(*link_rom, host=Host(demo), reply_fault=drop_random_byte(rng, 0.1))
    played_exactly(machine, demo, 500)
    assert machine.host.stats["resends"] > 0


def test_corrupted_requests_are_ignored_and_repeated(link_rom, demo):
    rng = random.Random(4)

    def fault(byte):
        return byte ^ (1 << rng.randrange(8)) if rng.random() < 0.03 else byte

    machine = LinkConsole(*link_rom, host=Host(demo), request_fault=fault)
    played_exactly(machine, demo, 500)
    assert machine.decoder.discarded > 0
    assert machine.word("link_aborts") > 0


@pytest.mark.parametrize("to_nes_error, to_host_error", [(0.02, -0.02), (-0.02, 0.02)])
def test_baud_error_both_ways(link_rom, demo, to_nes_error, to_host_error):
    machine = LinkConsole(*link_rom, host=Host(demo),
                          to_nes=HostToNes(clock_error=to_nes_error),
                          to_host=NesToHost(clock_error=to_host_error))
    played_exactly(machine, demo, 300)
    stats = counters(machine)
    assert stats["link_rejects"] == stats["link_crc_errors"] == 0


def test_a_song_without_a_loop_ends_and_the_link_idles(link_rom):
    frames = [[(0x15, 0x0F)], [(0x00, 0xBF), (0x03, 0x08)]] + [[] for _ in range(10)]
    encoded = jbs.encode(frames)
    song = jbs.JbsFile(stream=encoded.data, total_frames=len(frames))
    machine = LinkConsole(*link_rom, host=Host(song))
    played_exactly(machine, song, 40)
    assert machine.byte("ended") == 1
    assert counters(machine)["link_rejects"] == 0


@pytest.mark.skipif(not RIPS, reason="no rips in music/")
@pytest.mark.parametrize("path", RIPS, ids=os.path.basename)
def test_rips_over_the_link(link_rom, path):
    song, _ = vgm2jbs.convert(vgm.load(path))
    rng = random.Random(path)
    machine = LinkConsole(*link_rom, host=Host(song), turnaround=lambda: ms(rng.uniform(0.5, 4)))
    played_exactly(machine, song, 400)
    stats = counters(machine)
    assert stats["underruns"] == 0
    assert stats["link_aborts"] == stats["link_rejects"] == stats["link_crc_errors"] == 0
