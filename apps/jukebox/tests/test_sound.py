"""Sampled sound on the link ROM: the routines that play it, measured cycle
by cycle, and then whole playlists with sound tracks in them, through the
host and the simulated serial line.

A sound's samples must all reach $4011, in order and once, and the music on
either side of it must stay frame-exact, whatever the line does to the
bursts that set it up.
"""

import itertools
import shutil
import subprocess
import os

import pytest

import gen_ui
import jbs
import pcm
import protocol
from link_harness import LinkConsole, ms
from nes_harness import PPUCTRL, PPUCTRL_NMI, expected_frames
from playlist import PlaylistSource
from protocol import OP_DATA, OP_SOUND, Host
from serial_line import SPACE, HostToNes
from test_link import complete_frames

ROOT = os.path.join(os.path.dirname(__file__), "..")
RATES = range(len(pcm.PERIODS))
PHASES = (0, 2.5, 4.5, 7, 8.5)
START = 500

pytestmark = pytest.mark.skipif(
    not (shutil.which("ca65") and shutil.which("ld65")), reason="cc65 not installed"
)


@pytest.fixture(scope="session")
def build(tmp_path_factory):
    build = tmp_path_factory.mktemp("sound_system")
    subprocess.run(["make", "-s", "BUILD=%s" % build, "verify"], cwd=ROOT, check=True)
    return build


@pytest.fixture(scope="session")
def link_rom(build):
    return str(build / "jukebox_link.nes"), str(build / "jukebox_link.labels")


@pytest.fixture(scope="session")
def demo(build):
    return jbs.JbsFile.from_bytes((build / "demo.jbs").read_bytes())


def levels(seed, count=300):
    """Samples that are easy to tell apart and never repeat in a row."""
    return [(seed + 37 * index + (index >> 3)) & 0x7F for index in range(count)]


def sound(seed=1, count=300, period=16, title="Voices - Hello"):
    return pcm.Sound(title, period, pcm.encode(levels(seed, count)))


def played_levels(machine):
    return [value & 0x7F for _, value in machine.level_log]


# --- the routines, called by themselves -----------------------------------------

def play(link_rom, rate, samples, phase=0.0, clock_error=0.0, last=0):
    machine = LinkConsole(*link_rom)
    machine.read_log = []
    machine.level_log = []
    data = pcm.encode(samples) + bytes((pcm.sample_byte(last, last=True),))
    machine.to_nes.send(data, START + phase, bit=pcm.PERIODS[rate] / (1.0 + clock_error))
    machine.call("pcm_stream_%d" % rate, limit=2_000_000)
    return machine


def test_each_routine_has_a_page_to_itself(link_rom):
    labels = LinkConsole(*link_rom).labels
    starts = [labels["pcm_stream_%d" % rate] for rate in RATES]
    assert all(start & 0xFF == 0 for start in starts)
    assert len({start >> 8 for start in starts}) == len(pcm.PERIODS)


@pytest.mark.parametrize("rate", RATES)
def test_every_sample_reaches_the_dac_at_every_start_phase(link_rom, rate):
    samples = levels(0x31 + rate)
    for phase in PHASES:
        machine = play(link_rom, rate, samples, phase, last=0x55)
        assert played_levels(machine) == samples + [0x55], "phase %.1f" % phase
        # All but the last carry the bit that keeps the stream going.
        assert all(value & pcm.MORE for _, value in machine.level_log[:-1])
        assert machine.level_log[-1][1] == 0x55


@pytest.mark.parametrize("rate", RATES)
def test_the_port_is_sampled_mid_bit_and_the_hunt_resumes_in_the_stop_bits(link_rom, rate):
    """The hunt's looks are 6 or 7 cycles apart, so a sample is up to 3.5
    off the middle of its bit, and a little more for rounding the first
    pad. After a byte's last sample the hunt must not look again until the
    last data bit is over, or a 0 there is taken for a start bit; and it
    must be looking before the next start bit falls."""
    period = pcm.PERIODS[rate]
    samples = levels(0x42 + rate, 40)
    worst = 0.0
    for phase in PHASES:
        reads = play(link_rom, rate, samples, phase).read_log
        detect = next(i for i, (_, level) in enumerate(reads) if level == SPACE)
        centers = [START + phase + (1.5 + k) * period for k in range(8)]
        for (cycle, _), center in zip(reads[detect + 1:detect + 9], centers):
            worst = max(worst, abs(cycle - center))
        resumed = reads[detect + 9][0]
        assert START + phase + 9 * period < resumed <= START + phase + 11 * period
    assert worst <= 7 / 2 + 1 and worst < period / 2


@pytest.mark.parametrize("rate", RATES)
def test_samples_come_out_a_byte_apart_give_or_take_the_hunt(link_rom, rate):
    """The host's UART is the clock. A write comes right after its byte's
    last sample: a fixed time from the start bit, plus where the hunt's
    look fell, 0 to 7 cycles."""
    period = pcm.PERIODS[rate]
    machine = play(link_rom, rate, levels(0x53 + rate), 3)
    lags = [cycle - (START + 3 + index * pcm.FRAME_BITS * period)
            for index, (cycle, _) in enumerate(machine.level_log)]
    assert max(lags) - min(lags) <= 7
    assert 8.5 * period < min(lags) and max(lags) < 10 * period


@pytest.mark.parametrize("rate", RATES)
@pytest.mark.parametrize("clock_error", [-0.01, 0.01])
def test_a_host_clock_1_percent_off_plays_every_sample(link_rom, rate, clock_error):
    samples = levels(0x64 + rate)
    for phase in (0, 8.5):
        assert played_levels(play(link_rom, rate, samples, phase, clock_error)) == samples + [0]


def test_a_pause_in_the_samples_holds_the_level_and_loses_nothing(link_rom):
    rate = len(pcm.PERIODS) - 1
    samples = levels(0x75)
    machine = LinkConsole(*link_rom)
    machine.level_log = []
    resume = machine.to_nes.send(pcm.encode(samples[:100]), START, bit=pcm.PERIODS[rate])
    machine.to_nes.send(pcm.encode(samples[100:]) + pcm.LAST_BYTE, resume + 20000.5,
                        bit=pcm.PERIODS[rate])
    machine.call("pcm_stream_%d" % rate, limit=2_000_000)
    assert played_levels(machine) == samples + [0]
    times = [cycle for cycle, _ in machine.level_log]
    assert times[100] - times[99] > 20000   # nothing was written in between


def test_filler_at_the_links_rate_ends_a_stream_at_every_rate(link_rom):
    for rate in RATES:
        machine = LinkConsole(*link_rom)
        machine.level_log = []
        end = machine.to_nes.send(pcm.encode(levels(0x06, 20)), START, bit=pcm.PERIODS[rate])
        machine.to_nes.send(pcm.FILLER, end + 5000)
        machine.call("pcm_stream_%d" % rate, limit=2_000_000)
        assert len(machine.level_log) == 21 and not machine.level_log[-1][1] & pcm.MORE


# --- whole playlists --------------------------------------------------------------

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

    def __getattr__(self, name):
        return getattr(self.source, name)


class HeldAtSound(Host):
    """A host that is paused from the moment the console asks for a sound,
    which is the only way to see the console waiting: the go burst would
    otherwise answer its first request."""

    def __init__(self, source, hold=False):
        super().__init__(source)
        self.hold = hold

    def handle(self, request):
        if request.op == OP_SOUND and self.hold:
            self.hold = False
            self.paused = True
        return super().handle(request)


def console(link_rom, tracks, loops=1, repeat=False, hold=False, **options):
    source = Recording(PlaylistSource(tracks, loops=loops, repeat=repeat))
    machine = LinkConsole(*link_rom, host=HeldAtSound(source, hold), **options)
    machine.level_log = []
    return machine, source


def run_until(machine, done, limit=3000):
    while not done():
        assert len(machine.frames) < limit, "still waiting after %d NMIs" % limit
        machine.run(10)


def music_is_exact(machine, source):
    """Everything the NES played is what the stream it was sent says. After
    a sound record's frame the NES plays nothing, for as many frames as the
    go burst takes and until the flush burst after the sound empties its
    buffer; those frames are not in the stream, and are passed over."""
    sent = complete_frames(source.log)
    frames, _ = jbs.decode(sent)
    sounds = {index for index, frame in enumerate(frames)
              if frame and isinstance(frame[-1], jbs.SoundRecord)}
    expected = expected_frames(sent, None)
    played = iter(machine.played_frames())
    index = compared = 0
    for got in played:
        assert got == next(expected), "frame %d" % index
        compared += 1
        if index in sounds:
            for got in played:
                if got:
                    index += 1
                    assert got == next(expected), "frame %d" % index
                    compared += 1
                    break
        index += 1
    assert compared > 100 or not frames
    assert machine.byte("stream_error") == 0


def line_counters(machine):
    return {name: machine.word(name) for name in
            ("link_aborts", "link_rejects", "link_crc_errors", "link_timeouts", "underruns")}


def screen(nametable, column, row, width):
    start = 32 * row + column
    return nametable[start:start + width].decode("latin-1").strip("\x00 ")


def requests(machine, op):
    return [(cycle, request) for cycle, request in machine.requests if request.op == op]


@pytest.mark.parametrize("period", pcm.PERIODS)
def test_a_sound_track_plays_between_two_tracks_of_music(link_rom, demo, period):
    voice = sound(3, 2500, period)
    machine, source = console(link_rom, [("Demo - One", demo), ("Voices - Hello", voice),
                                         ("Demo - Two", demo)])
    run_until(machine, lambda: machine.sounds)
    before = len(machine.played_frames())
    machine.run(300)
    assert played_levels(machine) == levels(3, 2500) + [0]
    assert len(machine.played_frames()) > before + 200      # and the music went on
    music_is_exact(machine, source)
    assert line_counters(machine) == dict.fromkeys(line_counters(machine), 0)
    assert machine.host.stats["resends"] == 0
    # The record came after the first track's last frame, and asked once.
    asked = requests(machine, OP_SOUND)
    assert [request.arg for _, request in asked] == [voice.rate]
    assert source.index == 2


def test_the_console_does_nothing_else_while_a_sound_plays(link_rom, demo):
    machine, _ = console(link_rom, [("Demo - One", demo), ("Voices - Hello", sound(4, 4000)),
                                    ("Demo - Two", demo)])
    run_until(machine, lambda: machine.sounds)
    machine.run(60)
    start, end, _ = machine.sounds[0]
    first, last = machine.level_log[0][0], machine.level_log[-1][0]
    assert start < first and last < end + 16 * pcm.FRAME_BITS
    # Nothing came from the console from the go burst's last request until
    # the samples were over, not even its controller read.
    asked = requests(machine, OP_SOUND)[-1][0]
    assert not [cycle for cycle, _ in machine.requests if asked < cycle < end]
    assert not [cycle for cycle in machine.to_host.times if asked + 2000 < cycle < end]
    # And then it asked for music again, with the next burst's number.
    after = [request for cycle, request in machine.requests if cycle > end]
    assert after[0].op == OP_DATA
    assert after[0].seq == (requests(machine, OP_SOUND)[-1][1].seq + 1) & 0xFF


def test_the_screen_names_the_sound_before_it_stands_still(link_rom, demo):
    voice = sound(5, 6102)      # 0.6 s at 10169 a second: 36 frames
    machine, _ = console(link_rom, [("Demo - One", demo), ("Voices - Hello", voice)])
    run_until(machine, lambda: machine.sounds)
    shown = machine.sound_screens[0]
    assert screen(shown, gen_ui.GAME_COLUMN, gen_ui.GAME_ROW, gen_ui.TITLE_MAX) == "Voices"
    assert screen(shown, gen_ui.TITLE_COLUMN, gen_ui.TITLE_ROW, gen_ui.TITLE_MAX) == "Hello"
    assert screen(shown, gen_ui.STATUS_COLUMN, gen_ui.STATUS_ROW,
                  gen_ui.STATUS_WIDTH) == "SAMPLED SOUND"
    assert screen(shown, gen_ui.TIME_COLUMN, gen_ui.TIME_ROW,
                  len(gen_ui.TIME_TEMPLATE)) == "0:00 / 0:00"
    assert machine.memory[PPUCTRL] & PPUCTRL_NMI


def test_a_sound_can_be_the_whole_playlist_and_repeat(link_rom):
    machine, source = console(link_rom, [("Voices - Hello", sound(6, 1500))], repeat=True)
    run_until(machine, lambda: len(machine.sounds) >= 3)
    machine.run(30)
    whole = levels(6, 1500) + [0]
    heard = played_levels(machine)
    assert len(heard) >= 3 * len(whole) and heard[:3 * len(whole)] == whole * 3
    assert machine.byte("stream_error") == 0


def test_a_sound_after_the_last_music_ends_the_playlist_quietly(link_rom, demo):
    machine, source = console(link_rom, [("Demo - One", demo), ("Voices - Hello", sound(7))])
    run_until(machine, lambda: machine.sounds)
    machine.run(200)
    assert played_levels(machine) == levels(7) + [0]
    assert source.finished and machine.byte("sound_wanted") == 0
    assert len(requests(machine, OP_SOUND)) == 1
    music_is_exact(machine, source)


# --- what the line can do to the go burst --------------------------------------------

def go_fault(action, times=1):
    """A reply_fault that acts on the first go bursts and passes the rest."""
    left = [times]

    def fault(reply):
        if reply[0] == protocol.SOUND_MARKER and left[0]:
            left[0] -= 1
            return action(reply)
        return reply

    return fault


@pytest.mark.parametrize("action, counter", [
    (lambda reply: b"", "link_timeouts"),                                       # lost
    (lambda reply: reply[:3] + bytes((reply[3] ^ 0x04,)) + reply[4:], "link_crc_errors"),
    (lambda reply: reply[:4], "link_aborts"),         # cut short: the next NMI ends the wait
])
def test_a_go_burst_that_does_not_arrive_is_asked_for_again(link_rom, demo, action, counter):
    """The host waits before it sends samples, in case the console missed
    the go burst. It did, asks again, and gets the same burst; the sound
    then plays once, whole. (The music's own bursts may then be asked for
    again a few times: a timeout moves the console's requests later in
    the frame, as it always does, until it finds a place that works.)"""
    machine, source = console(link_rom, [("Demo - One", demo), ("Voices - Hello", sound(8, 1200)),
                                         ("Demo - Two", demo)],
                              reply_fault=go_fault(action, times=2))
    run_until(machine, lambda: machine.sounds)
    machine.run(200)
    assert len(machine.sounds) == 1
    assert played_levels(machine) == levels(8, 1200) + [0]
    assert machine.word(counter) >= 1
    asked = requests(machine, OP_SOUND)
    assert len(asked) == 3 and len({request.seq for _, request in asked}) == 1
    music_is_exact(machine, source)


@pytest.mark.parametrize("turnaround_ms", [4.0, 9.0, 14.0])
def test_a_slow_host_still_gets_its_go_burst_through(link_rom, demo, turnaround_ms):
    machine, source = console(link_rom, [("Demo - One", demo), ("Voices - Hello", sound(9, 1200)),
                                         ("Demo - Two", demo)],
                              turnaround=lambda: ms(turnaround_ms))
    run_until(machine, lambda: machine.sounds)
    machine.run(200)
    assert len(machine.sounds) == 1
    assert played_levels(machine) == levels(9, 1200) + [0]
    music_is_exact(machine, source)


@pytest.mark.parametrize("clock_error", [-0.01, 0.01])
def test_a_host_clock_1_percent_off_plays_a_sound_track(link_rom, demo, clock_error):
    machine, source = console(link_rom, [("Demo - One", demo),
                                         ("Voices - Hello", sound(10, 3000, pcm.PERIODS[-1]))],
                              to_nes=HostToNes(clock_error=clock_error))
    run_until(machine, lambda: machine.sounds)
    machine.run(100)
    assert played_levels(machine) == levels(10, 3000) + [0]


# --- sounds that are not played -------------------------------------------------------

def test_a_console_whose_port_reads_otherwise_refuses_and_the_music_goes_on(link_rom, demo):
    """The routines count on the port's unused bits. A console where they
    read something else says so in its request, and the host skips the
    sound."""
    machine, source = console(link_rom, [("Demo - One", demo), ("Voices - Hello", sound(11)),
                                         ("Demo - Two", demo)])
    machine.port_bits = 0x00
    run_until(machine, lambda: requests(machine, OP_SOUND))
    before = len(machine.played_frames())
    machine.run(300)
    assert [request.arg for _, request in requests(machine, OP_SOUND)] == [protocol.SOUND_REFUSED]
    assert machine.sounds == [] and machine.level_log == []
    assert source.index == 2 and len(machine.played_frames()) > before + 200
    assert machine.byte("sound_wanted") == 0
    music_is_exact(machine, source)


def test_a_rate_the_console_does_not_have_is_refused(link_rom, demo):
    odd = sound(12)
    record = jbs.sound_record(len(pcm.PERIODS))

    class OddRate(PlaylistSource):
        def _start(self, index):
            super()._start(index)
            if self.sound_next is not None:
                self.data = record

    source = Recording(OddRate([("Demo - One", demo), ("Voices - Hello", odd),
                                ("Demo - Two", demo)], loops=1))
    machine = LinkConsole(*link_rom, host=Host(source))
    machine.level_log = []
    run_until(machine, lambda: requests(machine, OP_SOUND))
    machine.run(200)
    assert [request.arg for _, request in requests(machine, OP_SOUND)] == [protocol.SOUND_REFUSED]
    assert machine.sounds == [] and source.index == 2


def test_a_stopped_host_answers_a_sound_request_with_silence(link_rom):
    """Stopped while the console waits for its go burst: the answer is an
    empty flush burst, which takes the sound away. Play starts the track
    again, and this time it sounds."""
    machine, source = console(link_rom, [("Voices - Hello", sound(13, 900))], hold=True)
    host = machine.host
    run_until(machine, lambda: len(requests(machine, OP_SOUND)) >= 3)
    assert machine.byte("sound_wanted") == 1 + pcm.PERIODS.index(16)
    host.stop()
    machine.run(30)
    assert machine.byte("sound_wanted") == 0 and machine.sounds == []
    asked = len(requests(machine, OP_SOUND))
    machine.run(30)
    assert len(requests(machine, OP_SOUND)) == asked    # it asks for data again
    host.play()
    run_until(machine, lambda: machine.sounds)
    machine.run(30)
    assert played_levels(machine) == levels(13, 900) + [0]


def test_a_paused_host_holds_a_sound_until_it_is_resumed(link_rom):
    machine, _ = console(link_rom, [("Voices - Hello", sound(14, 900))], hold=True)
    host = machine.host
    run_until(machine, lambda: requests(machine, OP_SOUND))
    machine.run(60)
    # Paused, the console asks every frame and is told to wait every time.
    assert len(requests(machine, OP_SOUND)) > 40 and machine.sounds == []
    assert line_counters(machine)["link_timeouts"] == 0
    host.press(protocol.BUTTON_PLAY)
    run_until(machine, lambda: machine.sounds)
    machine.run(30)
    assert played_levels(machine) == levels(14, 900) + [0]


def test_the_controller_can_skip_a_sound_that_has_not_started(link_rom, demo):
    from nes_harness import PAD_RIGHT

    machine, source = console(link_rom, [("Voices - Hello", sound(15, 900)), ("Demo - One", demo)],
                              hold=True)
    run_until(machine, lambda: requests(machine, OP_SOUND))
    machine.pad = PAD_RIGHT
    machine.run(5)
    machine.pad = 0
    machine.run(200)
    assert machine.sounds == [] and machine.level_log == []
    assert source.index == 1 and len(machine.played_frames()) > 100
    assert machine.byte("sound_wanted") == 0


class CutShort(LinkConsole):
    """A host that dies partway through a sound, and one that starts up
    later and sends its filler."""

    def _send_sound(self):
        self.sound_fault = lambda samples: samples[:400]
        super()._send_sound()
        self.to_nes.send(pcm.FILLER, self.sounds[-1][1] + ms(400))


def test_filler_frees_a_console_left_in_the_middle_of_a_sound(link_rom, demo):
    source = Recording(PlaylistSource([("Voices - Hello", sound(16, 900)), ("Demo - One", demo)],
                                      loops=1))
    machine = CutShort(*link_rom, host=Host(source))
    machine.level_log = []
    run_until(machine, lambda: machine.sounds)
    machine.run(200)
    assert played_levels(machine)[:400] == levels(16, 900)[:400]
    assert len(machine.level_log) == 401            # the filler's first byte ended it
    assert machine.memory[PPUCTRL] & PPUCTRL_NMI
    assert len(machine.played_frames()) > 100       # and the music after it played


def test_the_bars_are_cleared_before_the_screen_stands_still(link_rom, demo):
    """A sound follows the music's last frame at once, with its notes'
    bars still up. They would stay up for the whole sound."""
    machine, _ = console(link_rom, [("Demo - One", demo), ("Voices - Hello", sound(17))])
    run_until(machine, lambda: machine.sounds)
    shown = machine.sound_screens[0]
    for row in range(gen_ui.BAR_ROW, gen_ui.BAR_ROW + gen_ui.BAR_ROWS):
        start = 32 * row + gen_ui.BAR_COLUMN
        assert shown[start:start + gen_ui.BAR_COUNT] == bytes(gen_ui.BAR_COUNT), "row %d" % row
    assert all(machine.byte("ui_level", bar) == 0 for bar in range(gen_ui.BAR_COUNT))
