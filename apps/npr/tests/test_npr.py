"""The NPR ROM against a nesp32 over the simulated serial line.

The test is the Internet: it hands the nesp32 the station's stream, an MP3
of a tone. What must come of it is that tone on the console's DAC, every
sample the nesp32 sent, once and in order and at the UART's pace; and a
console that always comes back from a sound to a link that works.
"""

import math

import nesp
import nesp_proto as p
import pytest

import pcm
import wav2pcm
from nes_harness import PAD_A, PAD_START
from radio import Radio, ms

TUNER = p.NESP_SVC_TUNER
PERIOD = p.NESP_TUNER_PERIOD
RATE = pcm.sample_rate(PERIOD)
SAMPLE_CYCLES = PERIOD * pcm.FRAME_BITS         # a byte on the line
TONE_HZ, TONE_LEVEL = 1000, 0.475               # nesp32's tests/fixtures/README.md


@pytest.fixture
def radio(rom):
    def make(**options):
        return Radio(*rom, **options)
    return make


def on_air(machine, tone):
    """Press Start, give the nesp32 the stream, and run until the console
    is in the sound."""
    machine.until(lambda: machine.status == "PRESS START", limit=60)
    machine.press(PAD_START)
    machine.until(lambda: machine.stick.fetches == 1, limit=30)
    machine.air(tone)
    machine.until(lambda: machine.deaf, limit=60)
    return machine


def played(machine):
    """The levels the console's DAC was set to."""
    return [value & 0x7F for _, value in machine.level_log]


def tone_amplitude(levels):
    samples = [2 * wav2pcm.DAC[level] / wav2pcm.DAC[-1] - 1 for level in levels]
    mean = sum(samples) / len(samples)
    angle = 2 * math.pi * TONE_HZ / RATE
    cosine = sum((s - mean) * math.cos(angle * n) for n, s in enumerate(samples))
    sine = sum((s - mean) * math.sin(angle * n) for n, s in enumerate(samples))
    return math.hypot(cosine, sine) * 2 / len(samples)


# --- hello, and tuning -------------------------------------------------------------------


def test_the_rom_says_who_it_is_and_what_it_needs(radio):
    machine = radio()
    machine.until(lambda: machine.status == "PRESS START", limit=60)
    service, op, payload = machine.requests()[0]
    assert (service, op) == (p.NESP_SVC_SYS, p.NESP_SYS_HELLO)
    assert payload == bytes((p.NESP_PROTOCOL,)) + b"NPR " + bytes((1, 31, TUNER, p.NESP_SVC_RAW))
    assert machine.stick.app == (b"NPR ", 1)
    assert machine.stick.active(TUNER) and machine.stick.active(p.NESP_SVC_RAW)
    assert machine.stick.hellos == 1
    assert machine.screen_text(7, 11, 18) == "NPR PROGRAM STREAM"


def test_nothing_is_fetched_until_start_is_pressed(radio):
    machine = radio()
    machine.wait(120)
    assert machine.status == "PRESS START"
    assert machine.stick.fetches == 0 and not machine.level_log
    assert machine.asked(p.NESP_TUNER_STATE) > 100      # it asks every frame
    assert machine.word("link_failed") == 0


@pytest.mark.parametrize("button", [PAD_START, PAD_A])
def test_start_tunes_and_a_second_press_gives_it_up(radio, tone, button):
    machine = radio()
    machine.until(lambda: machine.status == "PRESS START", limit=60)
    machine.press(button)
    machine.until(lambda: machine.status == "TUNING", limit=30)
    assert machine.stick.fetches == 1 and machine.asked(p.NESP_TUNER_PLAY) == 1
    machine.air(tone[:8192])                    # some, and not enough
    machine.wait(30)
    assert machine.status == "TUNING" and not machine.deaf
    machine.press(button)
    machine.until(lambda: machine.status == "PRESS START", limit=30)
    assert machine.asked(p.NESP_TUNER_STOP) == 1 and not machine.stick.fetching


def test_without_wifi_the_screen_says_so(radio):
    machine = radio(wifi=p.NESP_WIFI_IDLE)
    machine.until(lambda: machine.status == "PRESS START", limit=60)
    machine.press(PAD_START)
    machine.until(lambda: machine.status == "NO WI-FI", limit=30)
    assert machine.stick.fetches == 0


def test_a_station_that_cannot_be_had_says_why_and_can_be_tried_again(radio, tone):
    machine = radio()
    machine.until(lambda: machine.status == "PRESS START", limit=60)
    machine.press(PAD_START)
    machine.until(lambda: machine.stick.fetches == 1, limit=30)
    machine.stick.fetch_done(False, b"THE SITE SAID 404")
    machine.until(lambda: machine.status == "THE SITE SAID 404", limit=30)
    machine.press(PAD_START)
    machine.until(lambda: machine.stick.fetches == 2, limit=30)
    machine.stick.fetch_done(False, b"THE SITE DID NOT ANSWER")
    machine.until(lambda: machine.status == "THE SITE DID NOT ANSWER", limit=30)


def test_no_nesp32_means_no_sound_and_no_hang(rom):
    machine = Radio(*rom, attached=False)
    machine.press(PAD_START)
    machine.wait(60)
    assert machine.status == "WAITING FOR LINK"
    assert not machine.deaf and not machine.level_log


def test_firmware_older_than_the_rom_is_told_apart_from_none(radio):
    def old(reply):
        answer = nesp.parse(reply)
        if answer.svc == p.NESP_SVC_SYS and len(answer.payload) >= 7:
            return nesp.reply_frame(p.NESP_SVC_SYS, p.NESP_ST_NO_SERVICE, answer.seq,
                                    answer.payload[:6] + bytes((1, TUNER)))
        return reply
    machine = radio(to_console=old)
    machine.wait(30)
    assert machine.status == "UPDATE NESP32" and machine.byte("greeted") == 0


# --- the sound ---------------------------------------------------------------------------


def test_the_station_plays_on_the_dac(radio, tone):
    machine = on_air(radio(), tone)
    assert machine.status == "ON THE AIR"       # said before the screen stood still
    assert machine.asked(p.NESP_TUNER_SOUND) == 1
    machine.advance(ms(700))
    assert machine.deaf
    levels = played(machine)
    assert len(levels) > 0.4 * RATE
    # Every sample the nesp32 has sent that has had time to arrive, in order.
    sent = pcm.decode(machine.port.runs[-1][2])
    assert levels == sent[:len(levels)] and len(sent) - len(levels) < 300
    # A sample for each byte on the line, when it comes.
    cycles = [cycle for cycle, _ in machine.level_log]
    gaps = [later - sooner for sooner, later in zip(cycles, cycles[1:])]
    assert min(gaps) >= SAMPLE_CYCLES - 8 and max(gaps) <= SAMPLE_CYCLES + 8
    assert tone_amplitude(levels[2000:]) == pytest.approx(TONE_LEVEL, abs=0.02)


def test_the_screen_stands_still_and_only_a_is_looked_at(radio, tone):
    machine = on_air(radio(), tone)
    picture = machine.nametable()
    asked = len(machine.requests())
    machine.pad = 0xFF & ~PAD_A                 # every other button
    machine.advance(ms(300))
    machine.pad = 0
    assert machine.deaf and machine.nametable() == picture
    assert len(machine.requests()) == asked     # nothing was said on the line


def pause(machine):
    """Hold A until the console has left the sound, then let go."""
    machine.pad = PAD_A
    machine.until(lambda: not machine.deaf, limit=60)
    machine.wait(3)
    machine.pad = 0


def test_a_pauses_the_station_and_a_again_plays_it_on(radio, tone):
    machine = on_air(radio(), tone)
    machine.advance(ms(300))
    before = len(machine.level_log)
    pause(machine)
    levels = played(machine)
    assert levels[-1] == 0                      # the DAC is left at its rest
    assert levels[-20:] == list(range(19, -1, -1))  # and came to it a step at a time
    assert len(levels) - before < 0.05 * RATE   # at once: A is looked at with every sample
    machine.until(lambda: machine.status == "PAUSED", limit=30)
    assert machine.port.period == p.NESP_PERIOD     # the line is the link's again
    assert machine.stick.fetching and machine.stick.fetches == 1
    failed = machine.word("link_failed")
    machine.wait(60)
    assert machine.status == "PAUSED" and machine.byte("sounds") == 1
    assert machine.word("link_failed") == failed
    # Played again: what the nesp32 held, with nothing tuned in anew.
    count = len(machine.level_log)
    machine.press(PAD_A)
    machine.until(lambda: machine.deaf, limit=60)
    assert machine.status == "ON THE AIR"
    machine.advance(ms(300))
    assert machine.deaf and machine.byte("sounds") == 2 and machine.stick.fetches == 1
    assert len(machine.level_log) > count + 0.1 * RATE


def test_start_plays_a_paused_station_too(radio, tone):
    machine = on_air(radio(), tone)
    machine.advance(ms(200))
    pause(machine)
    machine.until(lambda: machine.status == "PAUSED", limit=30)
    machine.press(PAD_START)
    machine.until(lambda: machine.deaf, limit=60)
    assert machine.byte("sounds") == 2 and machine.stick.fetches == 1


def test_the_press_that_pauses_is_not_taken_for_one_that_plays(radio, tone):
    machine = on_air(radio(), tone)
    machine.advance(ms(200))
    machine.pad = PAD_A                         # and held, a second and more
    machine.until(lambda: machine.status == "PAUSED", limit=60)
    machine.wait(90)
    assert machine.status == "PAUSED" and not machine.deaf
    machine.pad = 0
    machine.wait(30)
    assert machine.status == "PAUSED" and machine.byte("sounds") == 1


def test_a_held_down_does_not_end_the_sound_as_it_begins(radio, tone):
    machine = radio()
    machine.until(lambda: machine.status == "PRESS START", limit=60)
    machine.pad = PAD_A                         # tuned in with A, which stays down
    machine.until(lambda: machine.stick.fetches == 1, limit=30)
    machine.air(tone)
    machine.until(lambda: machine.status == "ON THE AIR", limit=60)
    machine.wait(30)
    assert not machine.deaf and machine.asked(p.NESP_TUNER_SOUND) == 0
    machine.pad = 0
    machine.until(lambda: machine.deaf, limit=30)
    machine.advance(ms(300))
    assert machine.deaf and machine.byte("sounds") == 1


def test_the_nesp32s_button_turns_a_paused_station_off(radio, tone):
    machine = on_air(radio(), tone)
    machine.advance(ms(200))
    pause(machine)
    machine.until(lambda: machine.status == "PAUSED", limit=30)
    machine.press_button(p.NESP_EVENT_BUTTON_A)
    machine.until(lambda: machine.status == "PRESS START", limit=30)
    assert not machine.stick.fetching


def test_a_station_lost_while_it_is_paused_says_why(radio, tone):
    machine = on_air(radio(), tone)
    machine.advance(ms(200))
    pause(machine)
    machine.until(lambda: machine.status == "PAUSED", limit=30)
    machine.stick.fetch_done(False, b"THE CONNECTION DROPPED")
    machine.until(lambda: machine.status == "THE CONNECTION DROPPED", limit=30)


def test_the_nesp32s_button_ends_the_sound_and_the_link_goes_on(radio, tone):
    machine = on_air(radio(), tone)
    machine.advance(ms(300))
    machine.press_button(p.NESP_EVENT_BUTTON_A)
    machine.advance(ms(250))
    assert not machine.deaf
    levels = played(machine)
    assert levels[-1] == 0                      # the DAC is left at its rest
    fall = levels[-200:]
    assert fall == sorted(fall, reverse=True)   # and came to it by a ramp
    machine.until(lambda: machine.status == "PRESS START", limit=30)
    assert machine.byte("sounds") == 1 and not machine.stick.fetching
    failed = machine.word("link_failed")
    machine.wait(60)
    assert machine.word("link_failed") == failed


def test_it_can_be_played_again(radio, tone):
    machine = on_air(radio(), tone)
    machine.advance(ms(200))
    machine.press_button(p.NESP_EVENT_BUTTON_A)
    machine.advance(ms(250))
    machine.until(lambda: machine.status == "PRESS START", limit=30)
    count = len(machine.level_log)
    machine.press(PAD_START)
    machine.until(lambda: machine.stick.fetches == 2, limit=30)
    machine.air(tone)
    machine.until(lambda: machine.deaf, limit=60)
    machine.advance(ms(300))
    assert machine.byte("sounds") == 2 and len(machine.level_log) > count + 1000


def test_a_stream_that_is_lost_is_played_out_and_the_screen_says_why(radio, tone):
    machine = on_air(radio(), tone[:len(tone) * 2 // 3])    # a little over two seconds
    machine.stick.fetch_done(False, b"THE CONNECTION DROPPED")
    machine.advance(ms(3200))
    assert not machine.deaf
    levels = played(machine)
    assert len(levels) > 2 * RATE and levels[-1] == 0
    machine.until(lambda: machine.status == "THE CONNECTION DROPPED", limit=30)


def test_a_console_that_is_reset_in_a_sound_is_heard_and_greeted_again(radio, tone):
    machine = on_air(radio(), tone)
    machine.advance(ms(300))
    machine.reset()
    machine.advance(ms(100))                    # its hello, into a line that is the run's
    machine.until(lambda: machine.stick.hellos == 2, limit=60)
    machine.until(lambda: machine.status == "PRESS START", limit=30)
    assert not machine.stick.fetching and machine.port.period == p.NESP_PERIOD
