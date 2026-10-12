"""The NPR ROM against a nesp32 over the simulated serial line.

The test is the Internet: it hands the nesp32 the station's stream, an MP3
of a tone. What must come of it is that tone on the console's DAC, every
sample the nesp32 sent, once and in order and at the UART's pace; and a
console that always comes back from a sound to a link that works.
"""

import bisect
import math

import nesp
import nesp_proto as p
import pytest

import pcm
import wav2pcm
from nes_harness import (PAD_A, PAD_DOWN, PAD_SELECT, PAD_START, PAD_UP, PPUADDR, PPUCTRL, PPUDATA,
                         VBLANK_CYCLES)
from radio import PPUSCROLL, Radio, ms

TUNER = p.NESP_SVC_TUNER
PERIOD = p.NESP_TUNER_PERIOD
NEWS_PERIOD = p.NESP_TUNER_NEWS_PERIOD
NEWS_RATE = pcm.sample_rate(NEWS_PERIOD)
NEWS_URL = "https://feeds.npr.org/1001/rss.xml"
STATION_URL = "https://npr-ice.streamguys1.com/live.mp3"
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
    assert machine.screen_text(10, 26, 12) == "A=PLAY/PAUSE"         # the foot of the screen


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
    machine.wait(2)                             # the console sees it let go


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


# --- the menu ----------------------------------------------------------------------------

MENU = ["", "", "> HIGH QUALITY, NO HEADLINES", "", "  MED QUALITY, HEADLINE NEWS", "", "", "", ""]
MENU_NEWS = ["", "", "  HIGH QUALITY, NO HEADLINES", "", "> MED QUALITY, HEADLINE NEWS", "", "", "", ""]
BLANK = [""] * 9


def middle(machine):
    return [line.rstrip() for line in machine.page()]


def plays(machine):
    """The modes of the PLAYs the console has sent."""
    return [bytes(payload) for service, op, payload in machine.requests()
            if (service, op) == (TUNER, p.NESP_TUNER_PLAY)]


def test_it_starts_with_a_menu_of_two_and_the_first_chosen(radio):
    machine = radio()
    machine.until(lambda: machine.status == "PRESS START", limit=60)
    machine.wait(12)
    assert middle(machine) == MENU and machine.shown == 0x2000


@pytest.mark.parametrize("button", [PAD_DOWN, PAD_UP, PAD_SELECT])
def test_up_down_and_select_move_between_the_two(radio, button):
    machine = radio()
    machine.until(lambda: machine.status == "PRESS START", limit=60)
    machine.press(button)
    machine.wait(12)
    assert middle(machine) == MENU_NEWS
    machine.press(button)
    machine.wait(12)
    assert middle(machine) == MENU
    assert machine.stick.fetches == 0 and not plays(machine)    # nothing is chosen until Start


def test_start_plays_what_the_menu_has_and_the_menu_goes(radio, tone, feed):
    machine = radio()
    machine.until(lambda: machine.status == "PRESS START", limit=60)
    machine.press(PAD_START)
    machine.until(lambda: machine.stick.fetches == 1, limit=30)
    assert plays(machine) == [bytes((p.NESP_TUNER_MODE_HIGH,))]
    assert machine.stick.fetch_url == STATION_URL       # the station alone: no feed
    machine.wait(15)
    assert middle(machine) == BLANK and machine.status == "TUNING"
    machine.press(PAD_DOWN)                     # which does nothing now
    machine.wait(15)
    assert middle(machine) == BLANK
    machine.press(PAD_START)                    # given up: the menu again, as it was
    machine.until(lambda: machine.status == "PRESS START", limit=30)
    machine.wait(15)
    assert middle(machine) == MENU
    machine.press(PAD_DOWN)
    machine.press(PAD_A)
    machine.until(lambda: machine.stick.fetches == 2, limit=30)
    assert plays(machine)[-1] == bytes((p.NESP_TUNER_MODE_NEWS,))
    assert machine.stick.fetch_url == NEWS_URL


def test_a_station_that_fails_brings_the_menu_back(radio):
    machine = radio()
    machine.until(lambda: machine.status == "PRESS START", limit=60)
    machine.press(PAD_DOWN)
    machine.press(PAD_START)
    machine.until(lambda: machine.stick.fetches == 1, limit=30)
    machine.wait(15)
    assert middle(machine) == BLANK
    machine.stick.fetch_done(False, b"")        # no headlines: on to the station
    machine.until(lambda: machine.stick.fetches == 2, limit=30)
    machine.stick.fetch_done(False, b"THE SITE SAID 404")
    machine.until(lambda: machine.status == "THE SITE SAID 404", limit=30)
    machine.wait(15)
    assert middle(machine) == MENU_NEWS         # with what was chosen still chosen


# --- the station with the headlines --------------------------------------------------------

HEADLINES = ("A CONSOLE FROM 1985 LEARNS", "CAFE OWNERS WEIGH A LONGER", "SHORT ONE",
             "A SUMMARY THAT RUNS ON AND", "A FIFTH STORY THAT IS NOT")
FIRST = ["A CONSOLE FROM 1985 LEARNS", "TO READ THE NEWS", "",
         "ENGINEERS SAY THE MACHINE'S", "2 KILOBYTES OF MEMORY HOLD", "FOUR STORIES AT A TIME,",
         "\"WHICH IS PLENTY,\" ONE SAID", "& LAUGHED.", ""]
PAGE_MS = 550       # a page sent, 0.18 seconds, and drawn, four frames and the wait for the first


def news_on_air(machine, tone, feed=None):
    """Choose the station with the headlines, give the nesp32 their feed,
    or none, and the stream, and run until the console is in the sound."""
    machine.until(lambda: machine.status == "PRESS START", limit=60)
    count = machine.stick.fetches
    machine.press(PAD_DOWN)
    machine.press(PAD_START)
    machine.until(lambda: machine.stick.fetches == count + 1, limit=30)
    assert machine.stick.fetch_url == NEWS_URL
    if feed is None:
        machine.stick.fetch_done(False, b"THE SITE DID NOT ANSWER")
    else:
        machine.stick.fetch_body(feed)
        machine.stick.fetch_done()
    machine.until(lambda: machine.stick.fetches == count + 2, limit=30)
    machine.air(tone)
    machine.until(lambda: machine.deaf, limit=120)
    return machine


def shown_page(machine):
    """Sit through a page being sent and drawn, and return what is shown."""
    machine.advance(ms(PAGE_MS))
    return middle(machine)


def turned(machine):
    """Have the nesp32 send its next page now, where it waits half a
    minute, and return it as shown."""
    machine.stick.tuner_turn()
    return shown_page(machine)


def vblanks(machine):
    """The PPU writes made with the NMI off, a list for each vblank."""
    out = []
    last = None
    for into, register, value in machine.ppu_writes:
        if last is None or into < last:
            out.append([])
        out[-1].append((register, value))
        last = into
    return out


def test_the_station_with_the_headlines_plays_at_its_own_rate(radio, tone, feed):
    machine = news_on_air(radio(), tone, feed)
    assert machine.status == "ON THE AIR"
    assert [bytes(payload) for service, op, payload in machine.requests()
            if (service, op) == (TUNER, p.NESP_TUNER_SOUND)] == [bytes((p.NESP_TUNER_NEWS_RATE,))]
    machine.advance(ms(900))
    assert machine.deaf and machine.port.runs[-1][1] == NEWS_PERIOD
    levels = played(machine)
    assert len(levels) > 0.5 * NEWS_RATE
    sent = pcm.decode(machine.port.runs[-1][2])
    assert levels == sent[:len(levels)] and len(sent) - len(levels) < 300
    cycles = [cycle for cycle, _ in machine.level_log]
    gaps = [later - sooner for sooner, later in zip(cycles, cycles[1:])]
    byte = NEWS_PERIOD * pcm.FRAME_BITS
    assert min(gaps) >= byte - 8 and max(gaps) <= byte + 8


def test_the_first_headline_comes_with_the_sound_and_is_drawn_out_of_sight(radio, tone, feed):
    machine = news_on_air(radio(), tone, feed)
    assert middle(machine) == BLANK and machine.shown == 0x2000
    machine.read_log = []
    assert shown_page(machine) == FIRST and machine.shown == 0x2800
    assert machine.status == "ON THE AIR"       # the header and the status line are on both
    assert machine.nametable(0x2800)[:32 * 10] == machine.nametable(0x2000)[:32 * 10]
    assert [line.rstrip() for line in machine.page(0x2000)] == BLANK

    # Not a sample was lost to it, nor moved: each of a byte's eight looks
    # at the line is 14 cycles after the one before.
    levels = played(machine)
    sent = pcm.decode(machine.port.runs[-1][2])
    assert levels == sent[:len(levels)]
    looks = [cycle for cycle, _ in machine.read_log]
    for write, _ in machine.level_log[-4000:]:
        last = bisect.bisect_left(looks, write)
        byte = looks[last - 8:last]
        assert [later - sooner for sooner, later in zip(byte, byte[1:])] == [NEWS_PERIOD] * 7

    # Every write to the PPU was inside a vblank, with time to spare, and
    # each vblank that moved the PPU's address put the scroll back after.
    assert not machine.ppu_strays
    assert max(into for into, _, _ in machine.ppu_writes) < VBLANK_CYCLES - 150
    drawn = [writes for writes in vblanks(machine) if writes]
    assert len(drawn) == 4                      # four vblanks a page
    for index, writes in enumerate(drawn):
        ctrl = 2 if index == 3 else 0           # the new nametable from the page's last vblank
        assert writes[-3:] == [(PPUSCROLL, 0), (PPUSCROLL, 0), (PPUCTRL, ctrl)]
        assert all(register in (PPUADDR, PPUDATA) for register, _ in writes[:-3])
    assert sum(1 for writes in drawn for register, _ in writes if register == PPUDATA) == 9 * 28


def test_every_story_in_the_feed_comes_round(radio, tone, feed):
    machine = news_on_air(radio(), tone, feed)
    pages = [shown_page(machine)]
    shown = [machine.shown]
    for _ in range(5):
        pages.append(turned(machine))
        shown.append(machine.shown)
    assert machine.deaf and not machine.ppu_strays
    assert tuple(page[0] for page in pages[:5]) == HEADLINES
    assert pages[5] == pages[0]                 # and round again
    assert shown == [0x2800, 0x2000, 0x2800, 0x2000, 0x2800, 0x2000]
    levels = played(machine)
    sent = pcm.decode(machine.port.runs[-1][2])
    assert levels == sent[:len(levels)]


@pytest.mark.parametrize("clock_error", [-0.01, 0.01])
def test_the_headlines_come_from_a_nesp32_whose_clock_is_1_percent_off(radio, tone, feed,
                                                                       clock_error):
    machine = news_on_air(radio(clock_error=clock_error), tone, feed)
    pages = [shown_page(machine)] + [turned(machine) for _ in range(2)]
    assert tuple(page[0] for page in pages) == HEADLINES[:3]
    levels = played(machine)
    sent = pcm.decode(machine.port.runs[-1][2])
    assert levels == sent[:len(levels)] and not machine.ppu_strays
    assert max(into for into, _, _ in machine.ppu_writes) < VBLANK_CYCLES - 100


def test_with_no_headlines_the_station_plays_all_the_same(radio, tone):
    machine = news_on_air(radio(), tone)        # the feed could not be had
    machine.advance(ms(900))
    assert machine.deaf and machine.status == "ON THE AIR"
    assert middle(machine) == BLANK and not machine.ppu_writes and not machine.ppu_strays
    levels = played(machine)
    sent = pcm.decode(machine.port.runs[-1][2])
    assert len(levels) > 0.5 * NEWS_RATE and levels == sent[:len(levels)]


def test_a_pause_keeps_the_page_and_playing_again_goes_on_from_it(radio, tone, feed):
    machine = news_on_air(radio(), tone, feed)
    shown_page(machine)
    second = turned(machine)
    pause(machine)
    machine.until(lambda: machine.status == "PAUSED", limit=30)
    machine.wait(30)
    assert middle(machine) == second and machine.shown == 0x2000
    machine.level_log.clear()
    machine.press(PAD_A)
    machine.until(lambda: machine.deaf, limit=60)
    assert machine.status == "ON THE AIR" and middle(machine) == second
    # The same page is sent again, and drawn again on the other nametable.
    assert shown_page(machine) == second and machine.shown == 0x2800
    assert turned(machine)[0] == HEADLINES[2] and machine.shown == 0x2000
    assert not machine.ppu_strays and machine.stick.fetches == 2


@pytest.mark.parametrize("at", ["a page being sent", "a page being drawn"])
def test_a_pause_in_the_middle_of_a_page_leaves_the_screen_whole(radio, tone, feed, at):
    machine = news_on_air(radio(), tone, feed)
    first = shown_page(machine)
    machine.stick.tuner_turn()
    if at == "a page being sent":
        machine.advance(ms(90))
    else:
        count = len(vblanks(machine))
        for _ in range(400):
            if len(vblanks(machine)) >= count + 2:
                break
            machine.advance(ms(1))
        else:
            raise AssertionError("no page was begun")
    pause(machine)
    machine.until(lambda: machine.status == "PAUSED", limit=30)
    machine.wait(10)
    assert middle(machine) == first and machine.shown == 0x2800     # the new one is out of sight
    machine.level_log.clear()
    machine.press(PAD_A)
    machine.until(lambda: machine.deaf, limit=60)
    assert shown_page(machine)[:3] == [
        "CAFE OWNERS WEIGH A LONGER", "HEADLINE THAN THREE LINES OF", "TWENTY-EIGHT CHARACTERS..."]
    assert not machine.ppu_strays


def test_the_nesp32s_button_ends_the_sound_with_the_headlines_too(radio, tone, feed):
    machine = news_on_air(radio(), tone, feed)
    shown_page(machine)
    machine.press_button(p.NESP_EVENT_BUTTON_A)
    machine.advance(ms(300))
    assert not machine.deaf
    levels = played(machine)
    assert levels[-1] == 0                      # the DAC is left at its rest
    fall = levels[-100:]
    assert fall == sorted(fall, reverse=True)   # and came to it by a ramp
    machine.until(lambda: machine.status == "PRESS START", limit=30)
    machine.wait(15)
    assert middle(machine) == MENU_NEWS and machine.shown == 0x2000
    assert not machine.stick.fetching
    failed = machine.word("link_failed")
    machine.wait(60)
    assert machine.word("link_failed") == failed


def test_a_stream_that_is_lost_with_the_headlines_is_played_out(radio, tone, feed):
    machine = news_on_air(radio(), tone[:len(tone) * 2 // 3], feed)
    machine.stick.fetch_done(False, b"THE CONNECTION DROPPED")
    machine.advance(ms(4500))
    assert not machine.deaf and played(machine)[-1] == 0
    machine.until(lambda: machine.status == "THE CONNECTION DROPPED", limit=30)


def test_tuned_in_again_the_headlines_are_fetched_again(radio, tone, feed):
    machine = news_on_air(radio(), tone, feed)
    shown_page(machine)
    turned(machine)
    machine.press_button(p.NESP_EVENT_BUTTON_A)
    machine.advance(ms(300))
    machine.until(lambda: machine.status == "PRESS START", limit=30)
    machine.wait(15)
    machine.press(PAD_START)                    # the menu is where it was left
    machine.until(lambda: machine.stick.fetches == 3, limit=30)
    machine.stick.fetch_body(feed.replace(b"A console from 1985", b"Another one from 1990"))
    machine.stick.fetch_done()
    machine.until(lambda: machine.stick.fetches == 4, limit=30)
    machine.air(tone)
    machine.until(lambda: machine.deaf, limit=120)
    assert middle(machine) == BLANK and machine.shown == 0x2000
    assert shown_page(machine)[0] == "ANOTHER ONE FROM 1990 LEARNS"


def test_a_console_reset_in_the_sound_with_the_headlines_is_greeted_again(radio, tone, feed):
    machine = news_on_air(radio(), tone, feed)
    shown_page(machine)
    machine.reset()
    machine.advance(ms(100))
    machine.until(lambda: machine.stick.hellos == 2, limit=60)
    machine.until(lambda: machine.status == "PRESS START", limit=30)
    machine.wait(15)
    assert middle(machine) == MENU and machine.shown == 0x2000
    assert not machine.stick.fetching and machine.port.period == p.NESP_PERIOD


@pytest.mark.parametrize("news", [False, True])
def test_a_console_left_in_the_sound_is_freed_by_a_nesp32_starting_up(radio, tone, feed, news):
    """The routines have no timeout. A console whose nesp32 lost its power
    waits for the rest until one starts up, whose first bytes, twelve of 0
    at the link's rate, it takes for the sound's end: a byte with no more
    to come, or with the headlines a character that is none of theirs."""
    machine = news_on_air(radio(), tone, feed) if news else on_air(radio(), tone)
    machine.advance(ms(700))
    machine.power_off()
    machine.advance(ms(400))
    assert machine.deaf
    machine.power_cycle()
    machine.until(lambda: machine.stick.hellos == 1, limit=60)
    assert not machine.deaf
    machine.until(lambda: machine.status == "PRESS START", limit=30)
