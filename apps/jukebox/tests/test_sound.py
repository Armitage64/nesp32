"""Sampled sound on the link ROM: the routines that play it, measured cycle
by cycle, and then whole playlists with sound tracks in them, from a
nesp32 over the simulated serial line.

A sound's samples must all reach $4011, in order and once, and the music on
either side of it must stay frame-exact, whatever the line does to the
exchange that sets it up.
"""

import random

import nesp
import nesp_proto as p
import pytest

import gen_ui
import jbs
import pcm
from link_harness import LinkConsole, ms
from linked import (LINK_STOPPED, files, frames_of, greet, playlist_stream, press, start,
                    track_stream, wait_for)
from nes_harness import PAD_A, PAD_LEFT, PAD_RIGHT, PAD_START, PPUCTRL, PPUCTRL_NMI, expected_frames
from wire import SPACE

RATES = range(len(pcm.PERIODS))
HUNTED = [rate for rate in RATES if not pcm.tracked(pcm.PERIODS[rate])]
TRACKED = [rate for rate in RATES if pcm.tracked(pcm.PERIODS[rate])]
PHASES = (0, 2.5, 4.5, 7, 8.5)
START = 500
SOUND = (p.NESP_SVC_JUKE, p.NESP_JUKE_SOUND)
STREAM = (p.NESP_SVC_JUKE, p.NESP_JUKE_STREAM)


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

def at_rest(link_rom):
    """A console with nothing on its port, and OUT0 at mark, where the ROM
    leaves it: the routines look at button A, which the controller shows
    for as long as OUT0 is high."""
    machine = LinkConsole(*link_rom, attached=False)
    machine._strobe = 1
    return machine


def play(link_rom, rate, samples, phase=0.0, clock_error=0.0, last=0):
    machine = at_rest(link_rom)
    machine.read_log = []
    machine.level_log = []
    period = pcm.PERIODS[rate]
    data = pcm.lead(period) + pcm.encode(samples) + bytes((pcm.sample_byte(last, last=True),))
    machine.port.wire.send(data, START + phase, period / (1.0 + clock_error))
    machine.call("pcm_stream_%d" % rate, limit=2_000_000)
    return machine


def test_each_routine_has_a_page_to_itself(link_rom):
    labels = LinkConsole(*link_rom, attached=False).labels
    starts = [labels["pcm_stream_%d" % rate] for rate in RATES]
    assert all(start & 0xFF == 0 for start in starts)
    assert len({start >> 8 for start in starts}) == len(pcm.PERIODS)


def test_the_rates_are_the_ones_the_nesp32_sends_at():
    """Its JUKE service names a sound's rate by its place in this list
    (nesp32's juke.c), and the ROM has a routine for each."""
    assert pcm.PERIODS == (21, 16, 14, 12, 10, 8, 7)
    assert len(pcm.PERIODS) == p.NESP_JUKE_SOUND_RATES
    assert (pcm.TRACKED, pcm.LEAD) == (p.NESP_SOUND_TRACKED, p.NESP_SOUND_LEAD)
    assert pcm.LAST_BYTE == bytes((p.NESP_JUKE_SOUND_LAST,))
    assert pcm.FRAME_BITS == p.NESP_TO_NES_BITS and pcm.PERIODS[0] == p.NESP_PERIOD


@pytest.mark.parametrize("rate", RATES)
def test_every_sample_reaches_the_dac_at_every_start_phase(link_rom, rate):
    samples = levels(0x31 + rate)
    for phase in PHASES:
        machine = play(link_rom, rate, samples, phase, last=0x55)
        assert played_levels(machine) == samples + [0x55], "phase %.1f" % phase
        # All but the last carry the bit that keeps the stream going.
        assert all(value & pcm.MORE for _, value in machine.level_log[:-1])
        assert machine.level_log[-1][1] == 0x55


@pytest.mark.parametrize("rate", HUNTED)
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


@pytest.mark.parametrize("rate", HUNTED)
def test_samples_come_out_a_byte_apart_give_or_take_the_hunt(link_rom, rate):
    """The nesp32's UART is the clock. A write comes right after its byte's
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
def test_a_clock_1_percent_off_plays_every_sample(link_rom, rate, clock_error):
    samples = levels(0x64 + rate)
    for phase in (0, 8.5):
        assert played_levels(play(link_rom, rate, samples, phase, clock_error)) == samples + [0]


def test_a_pause_in_the_samples_holds_the_level_and_loses_nothing(link_rom):
    """At the rates that hunt for each start bit. The tracking routines go
    by the clock, and a nesp32 leaves no gap."""
    rate = HUNTED[-1]
    samples = levels(0x75)
    machine = at_rest(link_rom)
    machine.level_log = []
    wire = machine.port.wire
    resume = wire.send(pcm.encode(samples[:100]), START, pcm.PERIODS[rate])
    wire.send(pcm.encode(samples[100:]) + pcm.LAST_BYTE, resume + 20000.5, pcm.PERIODS[rate])
    machine.call("pcm_stream_%d" % rate, limit=2_000_000)
    assert played_levels(machine) == samples + [0]
    times = [cycle for cycle, _ in machine.level_log]
    assert times[100] - times[99] > 20000   # nothing was written in between


@pytest.mark.parametrize("rate", TRACKED)
def test_a_tracking_routine_samples_within_a_cycle_or_two_of_mid_bit(link_rom, rate):
    """Once it has settled on the lead, each byte's samples are where its
    bits' middles are, give or take the cycle the look moves by and the
    one a gap of 7 cannot be; and a byte is a byte long, a cycle either
    way. The lead's bytes go to no DAC."""
    period = pcm.PERIODS[rate]
    samples = levels(0x47 + rate, 60)
    for phase in PHASES:
        machine = play(link_rom, rate, samples, phase)
        assert played_levels(machine) == samples + [0]
        reads = machine.read_log
        detect = next(i for i, (_, level) in enumerate(reads) if level == SPACE)
        # The reads are the lead's and the samples', each byte a look and
        # 8 samples, after the hunt that found the first.
        bytes_in = [reads[detect + 1 + 9 * k:detect + 10 + 9 * k] for k in range(pcm.LEAD + 50)]
        worst = 0.0
        for k, byte_reads in enumerate(bytes_in[pcm.LEAD:], pcm.LEAD):
            begin = START + phase + k * pcm.FRAME_BITS * period
            centers = [begin + (1.5 + bit) * period for bit in range(8)]
            worst = max(worst, max(abs(cycle - center)
                                   for (cycle, _), center in zip(byte_reads, centers)))
        assert worst <= 2.5, "phase %.1f" % phase
        lags = [cycle - (START + phase + (pcm.LEAD + index) * pcm.FRAME_BITS * period)
                for index, (cycle, _) in enumerate(machine.level_log)]
        assert max(lags) - min(lags) <= 3


def test_filler_at_the_links_rate_ends_a_stream_at_every_rate(link_rom):
    """What a nesp32 sends when it starts: twelve zero bytes at the link's
    rate, which is the slowest of a sound's. A tracking routine plays the
    silence before it as bytes of mark, at the DAC's middle, and is ended
    all the same."""
    for rate in RATES:
        period = pcm.PERIODS[rate]
        machine = at_rest(link_rom)
        machine.level_log = []
        wire = machine.port.wire
        end = wire.send(pcm.lead(period) + pcm.encode(levels(0x06, 20)), START, period)
        wire.send(pcm.FILLER, end + 5000, p.NESP_PERIOD)
        machine.call("pcm_stream_%d" % rate, limit=2_000_000)
        assert played_levels(machine)[:20] == levels(0x06, 20)
        assert not machine.level_log[-1][1] & pcm.MORE
        if pcm.tracked(period):
            assert all(level == 0x40 for level in played_levels(machine)[20:-3])
        else:
            assert len(machine.level_log) == 21


# --- whole playlists --------------------------------------------------------------

def console(link_rom, tracks, loops=1, repeat=False, begin=True, go=None, **options):
    """A console on the link ROM, and a nesp32 with these (title, track)
    as its files, playing. go, if given, is what the line does to a reply
    that says GO, and how many times."""
    machine = LinkConsole(*link_rom, tracks=files(tracks), loops=loops, repeat=repeat, **options)
    machine.level_log = []
    machine.tracks = tracks
    if go is not None:
        machine.port.to_console = go_fault(machine, *go)
    if begin:
        start(machine)
    return machine


def sounds(machine):
    """How many sounds have been sent, whole or cut short: the line has
    been a run's and is the link's again."""
    return sum(1 for _, period in machine.port.rates[1::2] if period == p.NESP_PERIOD)


def asked(machine, kind=SOUND):
    return [payload for service, op, payload in machine.requests() if (service, op) == kind]


def hold_at_the_sound(machine):
    """Pause the nesp32 as the console comes to a sound's record, before it
    can ask for the sound: the only way to see it waiting, which GO would
    otherwise end at its first request."""
    wait_for(machine, lambda: machine.byte("sound_wanted"))
    machine.press_button(p.NESP_EVENT_BUTTON_A)


def music_is_exact(machine, stream):
    """Everything the NES played is what the stream says. After a sound
    record's frame the NES plays nothing until the sound is over and the
    music after it has refilled its buffer; those frames are not in the
    stream, and are passed over."""
    frames, _ = jbs.decode(stream)
    records = {index for index, frame in enumerate(frames)
               if frame and isinstance(frame[-1], jbs.SoundRecord)}
    expected = expected_frames(stream, None)
    played = iter(machine.played_frames())
    index = compared = 0
    for got in played:
        assert got == next(expected), "frame %d" % index
        compared += 1
        if index in records:
            for got in played:
                if got:
                    index += 1
                    assert got == next(expected), "frame %d" % index
                    compared += 1
                    break
        index += 1
    assert compared > 100 or not frames
    assert machine.byte("stream_error") == 0


def screen(nametable, column, row, width):
    start = 32 * row + column
    return nametable[start:start + width].decode("latin-1").strip("\x00 ")


@pytest.mark.parametrize("period", pcm.PERIODS)
def test_a_sound_track_plays_between_two_tracks_of_music(link_rom, demo, period):
    voice = sound(3, 2500, period)
    tracks = [("Demo - One", demo), ("Voices - Hello", voice), ("Demo - Two", demo)]
    machine = console(link_rom, tracks)
    wait_for(machine, lambda: sounds(machine))
    before = len(machine.played_frames())
    machine.run(300)
    assert played_levels(machine) == levels(3, 2500) + [0]
    assert len(machine.played_frames()) > before + 200      # and the music went on
    music_is_exact(machine, playlist_stream(tracks, loops=1, end=True))
    assert machine.word("link_failed") == 0 and machine.word("underruns") == 0
    assert machine.stick.juke_resent == 0
    # The record came after the first track's last frame, and it asked once.
    assert [payload[1] for payload in asked(machine)] == [voice.rate]
    assert [rate for _, rate in machine.port.rates] == [period, p.NESP_PERIOD]
    assert machine.stick.juke_index == 2


def test_the_console_does_nothing_else_while_a_sound_plays(link_rom, demo):
    tracks = [("Demo - One", demo), ("Voices - Hello", sound(4, 4000)), ("Demo - Two", demo)]
    machine = console(link_rom, tracks)
    wait_for(machine, lambda: sounds(machine))
    machine.run(60)
    begun, period, samples = machine.port.runs[0]
    end = begun + len(samples) * pcm.FRAME_BITS * period
    first, last = machine.level_log[0][0], machine.level_log[-1][0]
    assert begun < first and last < end + 16 * pcm.FRAME_BITS
    # Nothing came from the console from the reply that said GO until the
    # samples were over, not even its controller read: that silence is how
    # the nesp32 knew to send them.
    go = [at for request, at, _ in machine.answers if request[:2] == SOUND][-1]
    assert not [cycle for cycle in machine.port.tap.times if go + 3000 < cycle < end]
    # And then it asked for the stream again, and was told of a new epoch.
    kinds = [(service, op) for service, op, _ in machine.requests()]
    assert kinds[len(kinds) - kinds[::-1].index(SOUND)] == STREAM
    assert machine.byte("link_epoch") == asked(machine)[-1][0] + 1


def test_the_screen_names_the_sound_before_it_stands_still(link_rom, demo):
    voice = sound(5, 6102)      # 0.6 s at 10169 a second: 36 frames
    machine = console(link_rom, [("Demo - One", demo), ("Voices - Hello", voice)])
    wait_for(machine, lambda: sounds(machine))
    shown = machine.sound_screens[0]
    assert screen(shown, gen_ui.GAME_COLUMN, gen_ui.GAME_ROW, gen_ui.TITLE_MAX) == "Voices"
    assert screen(shown, gen_ui.TITLE_COLUMN, gen_ui.TITLE_ROW, gen_ui.TITLE_MAX) == "Hello"
    assert screen(shown, gen_ui.STATUS_COLUMN, gen_ui.STATUS_ROW,
                  gen_ui.STATUS_WIDTH) == "SAMPLED SOUND"
    assert screen(shown, gen_ui.TIME_COLUMN, gen_ui.TIME_ROW,
                  len(gen_ui.TIME_TEMPLATE)) == "0:00 / 0:00"
    assert machine.memory[PPUCTRL] & PPUCTRL_NMI    # and it is moving again


def test_the_bars_are_cleared_before_the_screen_stands_still(link_rom, demo):
    """A sound follows the music's last frame at once, with its notes'
    bars still up. They would stay up for the whole sound."""
    machine = console(link_rom, [("Demo - One", demo), ("Voices - Hello", sound(17))])
    wait_for(machine, lambda: sounds(machine))
    shown = machine.sound_screens[0]
    for row in range(gen_ui.BAR_ROW, gen_ui.BAR_ROW + gen_ui.BAR_ROWS):
        begin = 32 * row + gen_ui.BAR_COLUMN
        assert shown[begin:begin + gen_ui.BAR_COUNT] == bytes(gen_ui.BAR_COUNT), "row %d" % row
    assert all(machine.byte("ui_level", bar) == 0 for bar in range(gen_ui.BAR_COUNT))


def test_a_sound_can_be_the_whole_playlist_and_repeat(link_rom):
    machine = console(link_rom, [("Voices - Hello", sound(6, 1500))], repeat=True)
    wait_for(machine, lambda: sounds(machine) >= 3)
    machine.run(30)
    whole = levels(6, 1500) + [0]
    heard = played_levels(machine)
    assert len(heard) >= 3 * len(whole) and heard[:3 * len(whole)] == whole * 3
    assert machine.byte("stream_error") == 0


def test_a_sound_after_the_last_music_ends_the_playlist_quietly(link_rom, demo):
    tracks = [("Demo - One", demo), ("Voices - Hello", sound(7))]
    machine = console(link_rom, tracks)
    wait_for(machine, lambda: sounds(machine))
    machine.run(200)
    assert played_levels(machine) == levels(7) + [0]
    assert machine.byte("sound_wanted") == 0 and machine.byte("ended") == 1
    assert len(asked(machine)) == 1 and sounds(machine) == 1
    music_is_exact(machine, playlist_stream(tracks, loops=1, end=True))


# --- what the line can do to the reply that says GO -----------------------------------

def go_fault(machine, action, times=1):
    """A fault for the Port's to_console that acts on the first replies
    that say GO and passes the rest."""
    left = [times]

    def fault(reply):
        if (machine.answering[:2] == SOUND and left[0]
                and nesp.parse(reply).payload[1] == p.NESP_SOUND_GO):
            left[0] -= 1
            return action(reply)
        return reply

    return fault


@pytest.mark.parametrize("action", [
    lambda reply: None,                                                     # lost
    lambda reply: reply[:5] + bytes((reply[5] ^ 0x04,)) + reply[6:],        # damaged
    lambda reply: reply[:4],                    # cut short: the next vblank ends the wait
], ids=["lost", "damaged", "cut short"])
def test_a_go_that_does_not_arrive_is_asked_for_again(link_rom, demo, action):
    """The nesp32 waits before it sends samples, in case the console did
    not hear. It did not, and asks again a frame later; the wait starts
    again, and the sound then plays once, whole."""
    tracks = [("Demo - One", demo), ("Voices - Hello", sound(8, 1200)), ("Demo - Two", demo)]
    machine = console(link_rom, tracks, go=(action, 2))
    wait_for(machine, lambda: sounds(machine))
    machine.run(200)
    assert sounds(machine) == 1
    assert played_levels(machine) == levels(8, 1200) + [0]
    assert machine.word("link_failed") == 2
    assert len(asked(machine)) == 3 and len(set(asked(machine))) == 1
    music_is_exact(machine, playlist_stream(tracks, loops=1, end=True))


@pytest.mark.parametrize("turnaround_ms", [1.0, 2.0, 3.0])
def test_a_slow_nesp32_still_gets_its_go_through(link_rom, demo, turnaround_ms):
    tracks = [("Demo - One", demo), ("Voices - Hello", sound(9, 1200)), ("Demo - Two", demo)]
    machine = console(link_rom, tracks, turnaround=ms(turnaround_ms))
    wait_for(machine, lambda: sounds(machine))
    machine.run(200)
    assert sounds(machine) == 1
    assert played_levels(machine) == levels(9, 1200) + [0]
    music_is_exact(machine, playlist_stream(tracks, loops=1, end=True))


@pytest.mark.parametrize("clock_error", [-0.01, 0.01])
def test_a_nesp32_whose_clock_is_1_percent_off_plays_a_sound_track(link_rom, demo, clock_error):
    tracks = [("Demo - One", demo), ("Voices - Hello", sound(10, 3000, pcm.PERIODS[-1]))]
    machine = console(link_rom, tracks, clock_error=clock_error)
    wait_for(machine, lambda: sounds(machine))
    machine.run(100)
    assert played_levels(machine) == levels(10, 3000) + [0]


def test_a_sound_goes_through_a_noisy_line_whole(link_rom, demo):
    """The samples themselves have no check on them: a run is the wire as
    it is. What the line must not do is leave the two ends disagreeing
    about whether a sound is on."""
    rng = random.Random(5)

    def noise(reply):
        if rng.random() >= 0.15:
            return reply
        data = bytearray(reply)
        data[rng.randrange(len(data))] ^= 1 << rng.randrange(8)
        return bytes(data)

    tracks = [("Demo - One", demo), ("Voices - Hello", sound(18, 1200)), ("Demo - Two", demo)]
    machine = console(link_rom, tracks, to_console=noise)
    wait_for(machine, lambda: sounds(machine))
    machine.run(200)
    assert sounds(machine) == 1 and played_levels(machine) == levels(18, 1200) + [0]
    music_is_exact(machine, playlist_stream(tracks, loops=1, end=True))


# --- sounds that are not played -------------------------------------------------------

def test_a_console_whose_port_reads_otherwise_refuses_and_the_music_goes_on(link_rom, demo):
    """The routines count on the port's unused bits. A console where they
    read something else says so in its request, and the nesp32 passes the
    sound over."""
    tracks = [("Demo - One", demo), ("Voices - Hello", sound(11)), ("Demo - Two", demo)]
    machine = console(link_rom, tracks)
    machine.port_bits = 0x00
    wait_for(machine, lambda: asked(machine))
    before = len(machine.played_frames())
    machine.run(300)
    assert [payload[1] for payload in asked(machine)] == [p.NESP_JUKE_SOUND_REFUSED]
    assert sounds(machine) == 0 and machine.level_log == []
    assert machine.stick.juke_index == 2 and len(machine.played_frames()) > before + 200
    assert machine.byte("sound_wanted") == 0
    music_is_exact(machine, playlist_stream(tracks, loops=1, end=True))


def test_a_paused_nesp32_holds_a_sound_until_it_is_resumed(link_rom):
    machine = console(link_rom, [("Voices - Hello", sound(14, 900))])
    hold_at_the_sound(machine)
    machine.run(60)
    # Paused, the console asks for the stream, which says so, and for the
    # sound only once it is told otherwise.
    assert len(asked(machine)) <= 1 and sounds(machine) == 0 and machine.byte("paused")
    assert machine.word("link_failed") == 0 and machine.port.rates == []
    machine.press_button(p.NESP_EVENT_BUTTON_A)
    wait_for(machine, lambda: sounds(machine))
    machine.run(30)
    assert played_levels(machine) == levels(14, 900) + [0]


def test_the_controller_can_skip_a_sound_that_has_not_started(link_rom, demo):
    tracks = [("Voices - Hello", sound(15, 900)), ("Demo - One", demo)]
    machine = console(link_rom, tracks)
    hold_at_the_sound(machine)
    wait_for(machine, lambda: asked(machine))
    press(machine, PAD_RIGHT, frames=5)
    machine.run(200)
    assert sounds(machine) == 0 and machine.level_log == []
    assert machine.stick.juke_index == 1 and len(machine.played_frames()) > 100
    assert machine.byte("sound_wanted") == 0
    # The record's own frame silenced the APU, and then nothing played
    # until the next track did, from its beginning.
    got = machine.played_frames()
    music = next(index for index, frame in enumerate(got) if len(frame) > 1)
    assert got[:music] == [[(0x15, 0x00)]] + [[]] * (music - 1)
    assert got[music:music + 100] == frames_of(track_stream(*tracks[1], 1), 100)


@pytest.mark.parametrize("button, state, track", [
    (p.NESP_EVENT_BUTTON_A, "stopped", 1),      # the nesp32's button does not pause one
    (p.NESP_EVENT_BUTTON_B, "playing", 0),
    (p.NESP_EVENT_BUTTON_POWER, "playing", 2),
])
def test_a_button_on_the_nesp32_ends_a_sound_and_does_what_it_does(link_rom, demo, button, state,
                                                                    track):
    """The console hears nothing while a sound plays. The nesp32 ends the sound
    with the byte that leaves the DAC at rest, and the console comes back
    to find the music stopped, or another track playing."""
    voice = sound(19, 6000)
    tracks = [("Demo - One", demo), ("Voices - Hello", voice), ("Short - Two", demo)]
    machine = console(link_rom, tracks)
    wait_for(machine, lambda: machine.byte("sound_wanted"))
    played = len(machine.played_frames())
    pressed = []

    def press_when_under_way():
        if machine.port.runs and len(machine.port.runs[-1][2]) > 1000 and not pressed:
            pressed.append(machine.now)
            machine.press_button(button)
        elif not pressed:
            machine.at(machine.now + ms(5), press_when_under_way)
    machine.at(machine.now, press_when_under_way)
    wait_for(machine, lambda: sounds(machine))
    machine.run(3)
    assert machine.stick.juke_index == track    # counted from the sound, as it was playing
    machine.run(40)
    heard = played_levels(machine)
    assert 1000 < len(heard) < 6000
    assert heard == levels(19, 6000)[:len(heard) - 1] + [0]
    assert machine.memory[PPUCTRL] & PPUCTRL_NMI and machine.byte("sound_wanted") == 0
    if state == "stopped":
        assert machine.byte("link_state") == LINK_STOPPED and machine.byte("playing") == 0
        assert len(machine.played_frames()) <= played + 60
    else:
        machine.run_until_played(played + 150)
        assert machine.byte("stream_error") == 0


# --- button A, which pauses ----------------------------------------------------------

def pause_under_way(machine, after=1500, buttons=PAD_A, release=True):
    """Hold buttons on the controller from when this much of a sound has
    been sent until the console has left it, and a little longer."""
    def hold():
        if len(machine.port.runs) > count and len(machine.port.runs[-1][2]) > after:
            machine.pad = buttons
        else:
            machine.at(machine.now + ms(5), hold)
    count = sounds(machine)
    machine.at(machine.now, hold)
    wait_for(machine, lambda: sounds(machine) > count)
    machine.run(3)
    if release:
        machine.pad = 0
        machine.run(2)                          # the console sees it let go


def heard_before_the_pause(machine, wanted):
    """How many of the sound's samples reached the DAC before the console
    left it; after them it brought the DAC to its rest a step at a time."""
    heard = played_levels(machine)
    count = 0
    while count < len(heard) and heard[count] == wanted[count]:
        count += 1
    assert heard[count:] == list(range(wanted[count - 1] - 1, -1, -1))
    return count


@pytest.mark.parametrize("period", pcm.PERIODS)
def test_a_pauses_a_sound_and_a_again_plays_the_rest_of_it(link_rom, demo, period):
    wanted = levels(21, 9000)
    tracks = [("Demo - One", demo), ("Voices - Hello", sound(21, 9000, period)),
              ("Demo - Two", demo)]
    machine = console(link_rom, tracks)
    pause_under_way(machine)
    count = heard_before_the_pause(machine, wanted)
    assert 1000 < count < 4500
    wait_for(machine, lambda: machine.byte("paused"), limit=30)
    assert machine.memory[PPUCTRL] & PPUCTRL_NMI and machine.byte("sound_wanted")
    asked_before = len(asked(machine))
    machine.run(60)
    # Paused, it asks for the stream, which says so, and not for the sound.
    assert machine.byte("paused") and sounds(machine) == 1
    assert len(asked(machine)) == asked_before and machine.stick.juke_index == 1
    assert machine.word("link_failed") == 0
    # Played again, it goes on from where the console stopped listening,
    # give or take what the nesp32 can tell of that, and from the DAC's rest.
    machine.level_log = []
    press(machine, PAD_A)
    wait_for(machine, lambda: sounds(machine) == 2)
    machine.run(30)
    rest = played_levels(machine)
    at = len(wanted) + 1 - len(rest)
    rate = pcm.sample_rate(period)
    assert abs(at - count) < 0.02 * rate
    ramp = int(rate / 50)
    assert rest[ramp:] == wanted[at + ramp:] + [0]
    assert all(got <= level for got, level in zip(rest[:ramp], wanted[at:]))
    assert rest[0] == 0 and rest[:ramp] != wanted[at:at + ramp]
    # And then the music after it, as if nothing had happened.
    assert machine.byte("sound_wanted") == 0 and not machine.byte("paused")
    played = len(machine.played_frames())
    machine.run_until_played(played + 150)
    assert machine.stick.juke_index == 2 and machine.byte("stream_error") == 0


def test_a_paused_sound_shows_as_paused_music_does_and_then_as_it_did(link_rom):
    machine = console(link_rom, [("Voices - Hello", sound(27, 9000))])
    pause_under_way(machine)
    wait_for(machine, lambda: machine.byte("paused"), limit=30)
    machine.run(10)
    shown = set()
    for _ in range(64):                         # a flash and more
        machine.run(1)
        shown.add(machine.nametable())
    assert len(shown) == 2                      # the clock flashes, and nothing else moves
    assert all(b"SAMPLED SOUND" not in picture for picture in shown)
    press(machine, PAD_A)
    wait_for(machine, lambda: sounds(machine) == 2)
    # The screen that stood still through the rest of it is the one that
    # stood still through the first of it, clock and all.
    assert len(machine.sound_screens) == 2
    assert machine.sound_screens[1] == machine.sound_screens[0]
    assert b"SAMPLED SOUND" in machine.sound_screens[1]


def test_a_sound_can_be_paused_more_than_once(link_rom):
    wanted = levels(22, 9000)
    machine = console(link_rom, [("Voices - Hello", sound(22, 9000))])
    pause_under_way(machine)
    wait_for(machine, lambda: machine.byte("paused"), limit=30)
    press(machine, PAD_START)                   # Start plays too
    pause_under_way(machine)
    wait_for(machine, lambda: machine.byte("paused"), limit=30)
    machine.level_log = []
    press(machine, PAD_A)
    wait_for(machine, lambda: sounds(machine) == 3)
    machine.run(30)
    rest = played_levels(machine)
    assert 1000 < len(rest) < 6500 and rest[-500:] == wanted[-499:] + [0]


@pytest.mark.parametrize("button, track", [(PAD_RIGHT, 2), (PAD_LEFT, 0)])
def test_the_track_can_be_changed_while_a_sound_is_paused(link_rom, demo, button, track):
    tracks = [("Demo - One", demo), ("Voices - Hello", sound(23, 9000)), ("Demo - Two", demo)]
    machine = console(link_rom, tracks)
    pause_under_way(machine)
    wait_for(machine, lambda: machine.byte("paused"), limit=30)
    played = len(machine.played_frames())
    logged = len(machine.level_log)
    press(machine, button, frames=5)
    assert machine.stick.juke_index == track
    machine.run_until_played(played + 150)
    assert sounds(machine) == 1
    assert machine.byte("sound_wanted") == 0 and not machine.byte("paused")
    assert len(machine.level_log) == logged and machine.byte("stream_error") == 0


def test_the_press_that_pauses_a_sound_is_not_taken_for_one_that_plays(link_rom):
    machine = console(link_rom, [("Voices - Hello", sound(24, 9000))])
    pause_under_way(machine, release=False)     # still down, a second and more
    machine.run(90)
    assert machine.byte("paused") and sounds(machine) == 1
    machine.pad = 0
    machine.run(30)
    assert machine.byte("paused") and sounds(machine) == 1


def test_a_held_down_does_not_end_a_sound_as_it_begins(link_rom):
    machine = console(link_rom, [("Voices - Hello", sound(25, 3000))])
    hold_at_the_sound(machine)
    wait_for(machine, lambda: machine.byte("paused"), limit=30)
    machine.pad = PAD_A                         # played again with A, which stays down
    wait_for(machine, lambda: not machine.byte("paused"), limit=30)
    machine.run(60)
    assert sounds(machine) == 0 and machine.port.rates == []
    machine.pad = 0
    wait_for(machine, lambda: sounds(machine))
    machine.run(10)
    assert played_levels(machine) == levels(25, 3000) + [0]


def test_no_other_button_is_looked_at_while_a_sound_plays(link_rom):
    machine = console(link_rom, [("Voices - Hello", sound(26, 4000))])
    wait_for(machine, lambda: machine.port.runs)
    machine.pad = 0xFF & ~PAD_A
    wait_for(machine, lambda: sounds(machine))
    machine.pad = 0
    machine.run(10)
    assert played_levels(machine) == levels(26, 4000) + [0]


def test_filler_frees_a_console_left_in_the_middle_of_a_sound(link_rom, demo):
    """The routines have no timeout. A console whose nesp32 lost its power
    partway through a sound waits for the rest until one starts up, whose
    first bytes it takes for the sound's last; and then it says hello."""
    tracks = [("Voices - Hello", sound(16, 3000)), ("Demo - One", demo)]
    machine = console(link_rom, tracks)

    back = []

    def come_back():
        machine.power_cycle()
        back.append(machine.now)

    def die_partway():
        if machine.port.runs and len(machine.port.runs[-1][2]) > 400:
            machine.power_off()
            machine.at(machine.now + ms(300), come_back)
        else:
            machine.at(machine.now + ms(5), die_partway)
    machine.at(machine.now, die_partway)
    wait_for(machine, lambda: back and machine.stick.hellos == 1)
    sent = len(machine.port.runs[0][2])
    heard = played_levels(machine)
    assert 400 < sent < 3000 and heard[:sent] == levels(16, 3000)[:sent]
    assert len(machine.level_log) == sent + 1       # the filler's first byte ended it
    assert not machine.level_log[-1][1] & pcm.MORE
    assert machine.memory[PPUCTRL] & PPUCTRL_NMI
    greet(machine)
    machine.press_button(p.NESP_EVENT_BUTTON_POWER)  # on to the music
    machine.run_until_played(100)
    assert machine.byte("stream_error") == 0
