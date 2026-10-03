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
import protocol
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
    assert {r.seq for r in data} == {0}
    # Each request waits HUNT_TIMEOUT_FRAMES (4) for a marker, then repeats.
    assert 6 <= len(data) <= 8
    assert machine.word("link_timeouts") >= len(data) - 1
    assert machine.word("link_aborts") == 0


@pytest.mark.parametrize("turnaround_ms", [2, 5])
def test_turnaround_inside_the_budget_never_aborts(link_rom, demo, turnaround_ms):
    machine = LinkConsole(*link_rom, host=Host(demo), turnaround=lambda: ms(turnaround_ms))
    played_exactly(machine, demo, 300)
    assert counters(machine)["link_aborts"] == 0


@pytest.mark.parametrize("low_ms, high_ms", [(7, 7), (6, 9), (10, 14)])
def test_a_host_just_past_the_budget_settles(link_rom, demo, low_ms, high_ms):
    """A reply this late arrives in the frame after its request. The NES then
    asked again at once, partway through that frame, and the reply to that
    ran into the next NMI, so every other burst was lost and request_delay
    never settled. The request after a late burst now waits for an NMI."""
    rng = random.Random(5)
    machine = LinkConsole(*link_rom, host=Host(demo),
                          turnaround=lambda: ms(rng.uniform(low_ms, high_ms)))
    played_exactly(machine, demo, 400)
    stats = machine.host.stats
    assert stats["resends"] <= 0.05 * stats["bursts"]
    assert counters(machine)["underruns"] == 0


def test_the_nes_reports_its_counters_to_the_host(link_rom, demo):
    """The console shows nothing, so the host's status line is the only
    place to see why bursts were asked for again."""
    rng = random.Random(6)
    machine = LinkConsole(*link_rom, host=Host(demo), reply_fault=flip_random_bit(rng, 0.2))
    played_exactly(machine, demo, 400)
    reported = machine.host.nes
    assert set(reported) == set(protocol.NES_COUNTERS)
    assert reported["crc_errors"] + reported["rejects"] + reported["aborts"] > 5
    for name in ("aborts", "timeouts", "rejects", "crc_errors", "underruns"):
        # Reports take turns, so each is at most a couple of seconds old.
        assert 0 <= machine.word(name if name == "underruns" else "link_" + name) - reported[name] <= 30


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


@pytest.mark.parametrize("turnaround_ms", [8, 12, 16, 20])
def test_a_steady_slow_host_still_delivers(link_rom, demo, turnaround_ms):
    # Replies that always land across the NMI would lock up a link that
    # retried at the same point in the frame. The NES moves its request
    # later after each miss until the replies fit, and keeps what works.
    frames = 400
    machine = LinkConsole(*link_rom, host=Host(demo), turnaround=lambda: ms(turnaround_ms))
    machine.run(frames)
    stats = counters(machine)
    assert stats["underruns"] == 0
    assert stats["link_bursts"] * 24 / frames >= 5  # the demo needs about 4
    played = len(machine.played_frames())
    expected = itertools.islice(expected_frames(demo.stream, loop_offset(demo)), played)
    assert machine.played_frames() == list(expected)


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


@pytest.mark.parametrize("seed", [2, 6, 7, 9])
def test_corrupted_bursts_are_rejected_and_resent(link_rom, demo, seed):
    """Seeds 6, 7 and 9 flip a burst's length byte while the ring is nearly
    full. The receiver used to store such a burst before checking its length
    against the credit, and it ran over music that had not played yet."""
    rng = random.Random(seed)
    machine = LinkConsole(*link_rom, host=Host(demo), reply_fault=flip_random_bit(rng, 0.2))
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


class Recording:
    """A source wrapper that keeps every byte handed to the host."""

    def __init__(self, source):
        self.source = source
        self.log = bytearray()

    def take(self, count):
        data = self.source.take(count)
        self.log += data
        return data

    def restart(self):
        self.source.restart()
        self.log.clear()


def complete_frames(data):
    """Decode the longest prefix of data that ends on a frame boundary."""
    end = len(data)
    while end:
        try:
            jbs.frame_units(bytes(data[:end]))
            return bytes(data[:end])
        except jbs.StreamError:
            end -= 1
    return b""


def test_a_playlist_with_skips_plays_through_the_link(link_rom, demo):
    from playlist import PlaylistSource

    frames = [[(0x15, 0x0F)], [(0x04, 0xBF), (0x07, 0x08)]] + [[(0x04, 0xB0 | n)] for n in range(15)]
    encoded = jbs.encode(frames, loop_frame=1)
    short = jbs.JbsFile(stream=encoded.data, total_frames=len(frames), loop_frame=1,
                        loop_offset=encoded.loop_offset)
    started = []
    source = PlaylistSource([("demo", demo), ("short", short)], loops=2,
                            on_track=lambda index, title: started.append(title))
    recording = Recording(source)
    machine = LinkConsole(*link_rom, host=Host(recording))
    machine.run(150)
    source.skip(1)                  # mid-song, mid-burst
    machine.run(250)
    source.skip(-1)
    machine.run(250)

    sent = complete_frames(recording.log)
    played = machine.played_frames()
    expected = list(itertools.islice(expected_frames(sent, None), len(played)))
    assert played == expected
    assert machine.byte("stream_error") == 0
    # The NES's hello at boot restarts the first track, so it is announced
    # twice before the skips.
    assert started == ["demo", "demo", "short", "demo"]
    assert short.stream[2:] in bytes(recording.log)


# -- stop, play and flush ------------------------------------------------------

def frames_from_the_start(song, count):
    return list(itertools.islice(expected_frames(song.stream, loop_offset(song)), count))


def apu_silenced_since(machine, nmis):
    """True if some NMI in the last `nmis` wrote $4015 = 0 and nothing else."""
    return any(writes == [(0x15, 0x00)] for writes, _, _ in machine.frames[-nmis:])


def test_a_stopped_host_keeps_the_nes_quiet_and_the_link_alive(link_rom, demo):
    host = Host(demo, stopped=True)
    machine = LinkConsole(*link_rom, host=host)
    machine.run(200)
    assert machine.byte("playing") == 0 and machine.played_frames() == []
    stats = counters(machine)
    assert stats["underruns"] == 0 and machine.word("link_timeouts") == 0
    assert stats["link_bursts"] > 150          # an empty flush burst nearly every frame
    assert host.stats["resends"] == 0

    host.play()
    machine.run_until_played(300)
    assert machine.played_frames()[:300] == frames_from_the_start(demo, 300)
    assert counters(machine)["underruns"] == 0


def test_stop_silences_at_once_and_play_starts_the_song_again(link_rom, demo):
    host = Host(demo)
    machine = LinkConsole(*link_rom, host=host)
    machine.run_until_played(150)
    host.stop()
    machine.run(6)
    played = len(machine.played_frames())
    assert machine.byte("playing") == 0 and apu_silenced_since(machine, 6)
    machine.run(120)
    assert len(machine.played_frames()) == played    # nothing more came out
    assert counters(machine)["underruns"] == 0 and machine.word("link_timeouts") == 0

    host.play()
    machine.run_until_played(played + 200)
    frames = machine.played_frames()
    assert frames[:played] == frames_from_the_start(demo, played)
    assert frames[played:played + 200] == frames_from_the_start(demo, 200)
    assert counters(machine)["underruns"] == 0


def test_a_jump_is_heard_within_a_second(link_rom, demo):
    from playlist import PlaylistSource

    frames = [[(0x15, 0x0F)], [(0x04, 0xBF), (0x07, 0x08)]] + [[(0x04, 0xB0 | n)] for n in range(15)]
    encoded = jbs.encode(frames, loop_frame=1)
    short = jbs.JbsFile(stream=encoded.data, total_frames=len(frames), loop_frame=1,
                        loop_offset=encoded.loop_offset)
    source = PlaylistSource([("demo", demo), ("short", short)], loops=50)
    host = Host(source)
    machine = LinkConsole(*link_rom, host=host)
    machine.run_until_played(150)
    source.jump(1)
    host.flush()
    machine.run(8)
    played = len(machine.played_frames())      # where the old track was cut
    nmis = len(machine.frames)
    machine.run_until_played(played + 100)
    got = machine.played_frames()
    assert got[:played] == frames_from_the_start(demo, played)
    assert got[played:played + 100] == frames_from_the_start(short, 100)
    # The NES held about 3 s of the old track. The new one needs only the
    # prefill: 768 bytes, or about 32 frames, then it plays.
    silent = next(index for index, (_, underran, playing) in enumerate(machine.frames[nmis:])
                  if playing and not underran)
    assert silent < 60
    assert counters(machine)["underruns"] == 0


@pytest.mark.parametrize("seed", range(4))
def test_stop_and_play_survive_a_noisy_line(link_rom, demo, seed):
    rng = random.Random(seed)
    host = Host(demo, stopped=True)
    machine = LinkConsole(*link_rom, host=host, reply_fault=flip_random_bit(rng, 0.15),
                          turnaround=lambda: ms(rng.uniform(0.5, 9)))
    played = 0
    for _ in range(4):
        machine.run(rng.randrange(20, 90))
        assert len(machine.played_frames()) == played
        host.play()
        machine.run_until_played(played + 120)
        host.stop()
        machine.run(40)                        # resends may delay the flush
        got = machine.played_frames()
        assert machine.byte("playing") == 0
        assert got[played:] == frames_from_the_start(demo, len(got) - played)
        played = len(got)
    assert machine.byte("stream_error") == 0
