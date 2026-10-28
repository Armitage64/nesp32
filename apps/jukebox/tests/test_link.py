"""The link ROM against a nesp32 over the simulated serial line.

The nesp32's end is its own firmware, built for this computer
(link_harness.py). Whatever the line does, the music must come out
frame-exact: the NES may play later than it would have (an underrun holds
the notes for a frame), but it must never play something different.
"""

import glob
import os
import random

import nesp
import nesp_proto as p
import pytest

import jbs
import vgm
import vgm2jbs
from link_harness import LinkConsole, ms
from linked import (LINK_STOPPED, LINK_STREAMING, LINK_WAITING, damage_requests, drop_random_byte,
                    ending_track, files, flip_random_bit, frames_of, greet, jbs_file,
                    played_exactly, playlist_stream, short_track, start, track_stream, wait_for)

ROOT = os.path.join(os.path.dirname(__file__), "..")
RIPS = sorted(glob.glob(os.path.join(ROOT, "music", "*.vg[mz]")))
LOOPS = 50                      # times round the demo's loop: longer than any test plays
CREDIT_MAX = 56                 # nes/serial_link.inc: the most a reply brings
PREFILL = 768                   # nes/jukebox.s: bytes buffered before the music starts


@pytest.fixture(scope="session")
def demo(build):
    return jbs.JbsFile.from_bytes((build / "demo.jbs").read_bytes())


@pytest.fixture
def linked(link_rom, demo):
    """Make a console on the link ROM with a nesp32 that holds the demo
    under the name "Demo - Song": linked(**port_options)."""
    def make(**options):
        options.setdefault("loops", LOOPS)
        return LinkConsole(*link_rom, tracks=[jbs_file(demo, "Demo - Song")], **options)
    return make


@pytest.fixture(scope="session")
def demo_stream(demo):
    return track_stream("Demo - Song", demo, LOOPS)


def failed(machine):
    """Exchanges the console made that brought no good reply."""
    return machine.word("link_failed")


# --- hello, and a link with nothing wrong ----------------------------------------------

def test_the_rom_says_who_it_is_and_what_it_needs(linked):
    machine = linked()
    greet(machine)
    service, op, payload = machine.requests()[0]
    assert (service, op) == (p.NESP_SVC_SYS, p.NESP_SYS_HELLO)
    assert payload == bytes((p.NESP_PROTOCOL,)) + b"JUKE" + bytes(
        (2, 63, p.NESP_SVC_JUKE, p.NESP_SVC_RAW, p.NESP_SVC_KBD))
    assert machine.stick.app == (b"JUKE", 2)
    assert machine.stick.active(p.NESP_SVC_JUKE) and machine.stick.active(p.NESP_SVC_RAW)
    assert machine.stick.active(p.NESP_SVC_KBD)     # a keyboard stays connected for the next ROM
    assert machine.stick.hellos == 1


def test_nothing_plays_until_a_button_says_so(linked):
    machine = linked()
    machine.run(200)
    assert machine.byte("playing") == 0 and machine.played_frames() == []
    assert machine.byte("link_state") == LINK_STOPPED
    # The console asks every frame all the same, so the link stays up and
    # the nesp32 can see that it is there.
    assert machine.stick.requests >= 195 and failed(machine) == 0
    assert machine.word("underruns") == 0


def test_a_clean_link_plays_frame_exact(linked, demo_stream):
    machine = start(linked())
    played_exactly(machine, demo_stream, 600)
    assert failed(machine) == 0 and machine.word("underruns") == 0
    assert machine.stick.juke_resent == 0 and machine.stick.repeats == 0
    assert machine.byte("link_state") == LINK_STREAMING


def test_playback_waits_for_the_prefill(linked):
    machine = start(linked())
    began = len(machine.frames)
    machine.run(PREFILL // CREDIT_MAX - 2)
    assert machine.byte("playing") == 0         # that many replies cannot hold 768 bytes
    machine.run_until_played(1)
    assert len(machine.frames) - began < PREFILL // CREDIT_MAX + 6


def test_no_nesp32_means_no_playback_and_no_hang(link_rom):
    machine = LinkConsole(*link_rom, attached=False)
    machine.run(60)
    assert machine.byte("playing") == 0 and machine.byte("link_state") == LINK_WAITING
    # A hello every frame, each given up at the next vblank.
    hellos = [payload for service, op, payload in machine.requests()
              if (service, op) == (p.NESP_SVC_SYS, p.NESP_SYS_HELLO)]
    assert 55 <= len(hellos) <= 60
    assert len(hellos) - 1 <= failed(machine) <= len(hellos)    # the last is still out


@pytest.mark.parametrize("turnaround_ms", [0.05, 1, 3])
def test_a_reply_inside_the_budget_is_never_missed(linked, demo_stream, turnaround_ms):
    machine = start(linked(turnaround=ms(turnaround_ms)))
    played_exactly(machine, demo_stream, 300)
    assert failed(machine) == 0 and machine.word("underruns") == 0


def test_the_time_the_nesp32_has_to_answer_is_reported(linked):
    """The longest the nesp32 may take for a reply that brings as much as
    the ROM ever asks for to land before the next vblank; for
    docs/PROTOCOL.md. Its firmware's slowest on hardware was 0.2 ms."""
    best = 0.0
    for tenths in range(20, 90, 5):
        turnaround = tenths / 10
        machine = start(linked(turnaround=ms(turnaround)))
        machine.run(12)                         # the prefill: every reply is a full one
        if failed(machine):
            break
        best = turnaround
    print("\nfull replies land before the vblank with the nesp32 taking up to %.1f ms" % best)
    assert best >= 3.0


def test_a_late_reply_is_dropped_and_its_bytes_asked_for_again(linked, demo_stream):
    """A reply cut off by the vblank is no reply. The next request says
    where the console still is, and the same bytes come again."""
    rng = random.Random(1)
    machine = start(linked(turnaround=lambda: ms(rng.uniform(0.2, 12))))
    played_exactly(machine, demo_stream, 400)
    assert failed(machine) > 5 and machine.stick.juke_resent > 5
    assert machine.word("underruns") == 0


def test_a_nesp32_that_always_answers_a_frame_late_is_never_heard(linked):
    """Nothing here waits past the vblank for a reply, and the firmware
    never takes a hundredth of this. The console must only not hang, and
    say that it hears nothing."""
    machine = linked(turnaround=ms(18))
    machine.run(60)
    assert machine.byte("greeted") == 0 and machine.byte("link_state") == LINK_WAITING
    assert machine.byte("playing") == 0


@pytest.mark.parametrize("seed", [2, 6, 7, 9])
def test_damaged_replies_are_dropped_and_asked_for_again(linked, demo_stream, seed):
    """Among them are replies whose length byte is the one that is wrong:
    none may be stored past what was asked for, into music that has not
    played yet."""
    rng = random.Random(seed)
    machine = start(linked(to_console=flip_random_bit(rng, 0.2)))
    played_exactly(machine, demo_stream, 500)
    assert failed(machine) > 0 and machine.stick.juke_resent > 0
    assert machine.word("underruns") == 0


def test_replies_with_bytes_missing_are_recovered(linked, demo_stream):
    rng = random.Random(3)
    machine = start(linked(to_console=drop_random_byte(rng, 0.1)))
    played_exactly(machine, demo_stream, 500)
    assert machine.stick.juke_resent > 0


def test_damaged_requests_are_passed_over_and_asked_again(linked, demo_stream):
    machine = start(linked())
    damage_requests(machine, random.Random(4), 0.03)
    played_exactly(machine, demo_stream, 500)
    assert failed(machine) > 20
    assert machine.stick.juke_resent == 0       # nothing it sent was lost: it was never asked


@pytest.mark.parametrize("clock_error", [-0.02, 0.02])
def test_a_nesp32_whose_clock_is_out(linked, demo_stream, clock_error):
    machine = start(linked(clock_error=clock_error))
    played_exactly(machine, demo_stream, 300)
    assert failed(machine) == 0


def test_the_nesp32_keeps_the_consoles_underruns(linked, demo_stream):
    """The console has no place to show them. A nesp32 that goes quiet
    until the ring has run dry is how to make some; the music then goes on
    from where it stopped."""
    machine = start(linked())
    machine.run_until_played(100)
    machine.port.deaf = True
    wait_for(machine, lambda: machine.word("underruns") > 20, limit=1000, step=10)
    machine.port.deaf = False
    machine.run(30)
    assert machine.word("underruns") < 60
    assert machine.stick.juke_underruns == machine.word("underruns")
    played_exactly(machine, demo_stream, 600)


# --- playlists ----------------------------------------------------------------------------

def test_a_track_without_a_loop_ends_and_the_link_idles(link_rom):
    song = ending_track()
    machine = start(LinkConsole(*link_rom, tracks=files([("Last", song)]), repeat=False))
    stream = playlist_stream([("Last", song)], end=True)
    played_exactly(machine, stream, 40)
    assert machine.byte("ended") == 1 and failed(machine) == 0
    assert machine.stick.requests > 40          # it goes on asking: Start plays it again


def test_one_track_follows_another_and_the_playlist_goes_round(link_rom, demo):
    tracks = [("Short - One", short_track()), ("Demo - Two", demo)]
    machine = start(LinkConsole(*link_rom, tracks=files(tracks)))
    stream = playlist_stream(tracks, loops=2, times=3)
    once = len(jbs.decode(playlist_stream(tracks, loops=2))[0])    # frames in the playlist
    played_exactly(machine, stream, 2 * once + 50)
    assert machine.word("underruns") == 0 and failed(machine) == 0


@pytest.mark.skipif(not RIPS, reason="no rips in music/")
@pytest.mark.parametrize("path", RIPS, ids=os.path.basename)
def test_rips_over_the_link(link_rom, path):
    song, _ = vgm2jbs.convert(vgm.load(path))
    rng = random.Random(path)
    machine = start(LinkConsole(*link_rom, tracks=[jbs_file(song, "A Game - A Rip")],
                                turnaround=lambda: ms(rng.uniform(0.1, 3))))
    played_exactly(machine, track_stream("A Game - A Rip", song), 400)
    assert machine.word("underruns") == 0 and failed(machine) == 0


def test_a_change_of_track_is_heard_within_a_second(link_rom, demo):
    tracks = [("Demo - One", demo), ("Short - Two", short_track())]
    machine = start(LinkConsole(*link_rom, tracks=files(tracks), loops=LOOPS))
    machine.run_until_played(150)
    machine.press_button(p.NESP_EVENT_BUTTON_POWER)      # next
    machine.run(4)
    played = len(machine.played_frames())               # where the old track was cut
    nmis = len(machine.frames)
    machine.run_until_played(played + 100)
    got = machine.played_frames()
    assert got[:played] == frames_of(track_stream(*tracks[0], LOOPS), played)
    assert got[played:played + 100] == frames_of(track_stream(*tracks[1], LOOPS), 100)
    # The NES held seconds of the old track. The new one needs only the
    # prefill, 768 bytes at 56 a frame, and then it plays.
    silent = next(index for index, (_, underran, playing) in enumerate(machine.frames[nmis:])
                  if playing and not underran)
    assert silent < 30
    assert machine.word("underruns") == 0 and machine.stick.juke_index == 1


def test_a_pause_holds_the_music_and_the_link_stays_up(linked, demo_stream):
    machine = start(linked())
    machine.run_until_played(150)
    machine.press_button(p.NESP_EVENT_BUTTON_A)
    machine.run(4)
    played = len(machine.played_frames())
    asked = machine.stick.requests
    machine.run(120)
    assert len(machine.played_frames()) == played       # nothing more came out
    assert machine.byte("paused") == 1 and machine.memory[0x4015] == 0
    assert machine.stick.requests - asked >= 118 and failed(machine) == 0
    machine.press_button(p.NESP_EVENT_BUTTON_A)
    played_exactly(machine, demo_stream, played + 200)  # one unbroken song
    assert machine.word("underruns") == 0


@pytest.mark.parametrize("seed", range(4))
def test_changes_of_track_survive_a_noisy_line(link_rom, demo, seed):
    rng = random.Random(seed)
    tracks = [("Demo - One", demo), ("Short - Two", short_track())]
    streams = [track_stream(*track, LOOPS) for track in tracks]
    machine = start(LinkConsole(*link_rom, tracks=files(tracks), loops=LOOPS,
                                to_console=flip_random_bit(rng, 0.15),
                                turnaround=lambda: ms(rng.uniform(0.1, 9))))
    played = 0
    for turn in range(5):
        machine.run_until_played(played + rng.randrange(40, 160))
        got = machine.played_frames()
        assert got[played:] == frames_of(streams[turn % 2], len(got) - played)
        machine.press_button(p.NESP_EVENT_BUTTON_POWER)
        # A damaged reply may put the flush off by a frame or two; then
        # nothing of the old track plays again.
        wait_for(machine, lambda: machine.byte("playing") == 0, limit=40)
        got = machine.played_frames()
        assert got[played:] == frames_of(streams[turn % 2], len(got) - played)
        played = len(got)
    assert machine.byte("stream_error") == 0


# --- when one of the two starts again -----------------------------------------------------

def test_a_console_that_is_reset_says_hello_again_and_the_music_stops(linked, demo_stream):
    machine = start(linked())
    machine.run_until_played(100)
    played = len(machine.played_frames())
    machine.mpu.pc = machine.memory[0xFFFC] | machine.memory[0xFFFD] << 8
    greet(machine)
    machine.run(30)
    assert machine.stick.hellos == 2 and len(machine.played_frames()) == played
    assert machine.byte("playing") == 0
    start(machine)
    machine.run_until_played(played + 100)
    assert machine.played_frames()[played:played + 100] == frames_of(demo_stream, 100)


def test_a_nesp32_switched_off_and_on_is_greeted_again_and_the_ring_dropped(linked, demo_stream):
    """It has forgotten the hello, and says so to the first thing it is
    asked. What the console holds is music the new one knows nothing of."""
    machine = start(linked())
    machine.run_until_played(100)
    machine.power_cycle()
    machine.stick.set_juke(loops=LOOPS)
    wait_for(machine, lambda: machine.stick.hellos == 1, limit=10)
    wait_for(machine, lambda: machine.byte("playing") == 0, limit=10)
    played = len(machine.played_frames())
    machine.run(60)
    assert len(machine.played_frames()) == played
    assert machine.byte("link_state") == LINK_STOPPED
    start(machine)
    machine.run_until_played(played + 100)
    assert machine.played_frames()[played:played + 100] == frames_of(demo_stream, 100)
    assert machine.byte("stream_error") == 0


def test_a_nesp32_switched_off_is_missed_and_found_again(linked, demo_stream):
    machine = start(linked())
    machine.run_until_played(50)
    machine.port.deaf = True
    machine.run(40)
    assert machine.byte("link_state") == LINK_WAITING
    machine.port.deaf = False
    machine.run(10)
    assert machine.byte("link_state") == LINK_STREAMING
    played_exactly(machine, demo_stream, 400)   # and nothing was lost by it


def test_firmware_older_than_the_rom_is_told_apart_from_none(linked):
    """A nesp32 whose firmware has no JUKE answers the hello, and says what
    it lacks. The screen then says what to do about it."""
    def old(reply):
        answer = nesp.parse(reply)
        if answer.svc == p.NESP_SVC_SYS and len(answer.payload) >= 7:
            return nesp.reply_frame(p.NESP_SVC_SYS, p.NESP_ST_NO_SERVICE, answer.seq,
                                    answer.payload[:6] + bytes((1, p.NESP_SVC_JUKE)))
        return reply
    machine = linked(to_console=old)
    machine.run(30)
    assert machine.byte("greeted") == 0
    assert machine.byte("link_state") == machine_constant("LINK_OLD")


def test_a_nesp32_without_kbd_is_used_all_the_same(link_rom):
    """The hello asks for KBD only to keep a keyboard connected for the
    next program; firmware without it plays the music all the same."""
    def older(reply):
        answer = nesp.parse(reply)
        if answer.svc == p.NESP_SVC_SYS and answer.ok and len(answer.payload) == 7:
            return nesp.reply_frame(p.NESP_SVC_SYS, p.NESP_ST_NO_SERVICE, answer.seq,
                                    answer.payload[:6] + bytes((1, p.NESP_SVC_KBD)))
        return reply
    machine = LinkConsole(*link_rom, to_console=older)
    machine.run(30)
    assert machine.byte("greeted") == 1
    assert machine.byte("link_state") == machine_constant("LINK_EMPTY")


def machine_constant(name):
    return {"LINK_OLD": 7, "LINK_EMPTY": 8}[name]


def test_a_nesp32_with_no_music_says_so(link_rom):
    machine = LinkConsole(*link_rom)
    machine.run(30)
    assert machine.byte("greeted") == 1
    assert machine.byte("link_state") == machine_constant("LINK_EMPTY")
    assert machine.byte("playing") == 0
