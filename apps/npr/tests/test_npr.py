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
from nes_harness import (PAD_A, PAD_B, PAD_DOWN, PAD_LEFT, PAD_RIGHT, PAD_SELECT, PAD_START,
                         PAD_UP, PPUADDR, PPUCTRL, PPUDATA, VBLANK_CYCLES)
from radio import PPUSCROLL, Radio, ms

import gen_news
import gen_screen

TUNER = p.NESP_SVC_TUNER
PERIOD = p.NESP_TUNER_PERIOD
NEWS_PERIOD = p.NESP_TUNER_NEWS_PERIOD
NEWS_RATE = pcm.sample_rate(NEWS_PERIOD)
STATION_URL = "https://npr-ice.streamguys1.com/live.mp3"
RATE = pcm.sample_rate(PERIOD)
SAMPLE_CYCLES = PERIOD * pcm.FRAME_BITS         # a byte on the line
TONE_HZ, TONE_LEVEL = 1000, 0.475               # nesp32's tests/fixtures/README.md
FOOT = dict(gen_screen.FOOT_TEXT)


@pytest.fixture
def radio(rom):
    def make(**options):
        return Radio(*rom, **options)
    return make


def on_air(machine, tone):
    """Press Start, give the nesp32 the stream, and run until the console
    is in the sound."""
    machine.until(lambda: machine.off, limit=60)
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
    machine.until(lambda: machine.off, limit=60)
    service, op, payload = machine.requests()[0]
    assert (service, op) == (p.NESP_SVC_SYS, p.NESP_SYS_HELLO)
    assert payload == bytes((p.NESP_PROTOCOL,)) + b"NPR " + bytes((1, 31, TUNER, p.NESP_SVC_RAW))
    assert machine.stick.app == (b"NPR ", 1)
    assert machine.stick.active(TUNER) and machine.stick.active(p.NESP_SVC_RAW)
    assert machine.stick.hellos == 1
    assert machine.foot() == FOOT["SELECT"]    # built by itself: B has no menu to go back to


def test_nothing_is_fetched_until_start_is_pressed(radio):
    machine = radio()
    machine.wait(120)
    assert machine.off
    assert machine.stick.fetches == 0 and not machine.level_log
    assert machine.asked(p.NESP_TUNER_STATE) > 100      # it asks every frame
    assert machine.word("link_failed") == 0


@pytest.mark.parametrize("button", [PAD_START, PAD_A])
def test_start_tunes_and_a_second_press_gives_it_up(radio, tone, button):
    machine = radio()
    machine.until(lambda: machine.off, limit=60)
    machine.press(button)
    machine.until(lambda: machine.status == "TUNING", limit=30)
    assert machine.stick.fetches == 1 and machine.asked(p.NESP_TUNER_PLAY) == 1
    machine.air(tone[:8192])                    # some, and not enough
    machine.wait(30)
    assert machine.status == "TUNING" and not machine.deaf
    machine.press(button)
    machine.until(lambda: machine.off, limit=30)
    assert machine.asked(p.NESP_TUNER_STOP) == 1 and not machine.stick.fetching


def test_without_wifi_the_screen_says_so(radio):
    machine = radio(wifi=p.NESP_WIFI_IDLE)
    machine.until(lambda: machine.off, limit=60)
    machine.press(PAD_START)
    machine.until(lambda: machine.status == "NO WI-FI", limit=30)
    assert machine.stick.fetches == 0


def test_a_station_that_cannot_be_had_says_why_and_can_be_tried_again(radio, tone):
    machine = radio()
    machine.until(lambda: machine.off, limit=60)
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
    # Every sample the nesp32 has sent that has had time to arrive, in order,
    # after the bytes the routine settles on and does not play.
    lead = machine.port.runs[-1][2][:pcm.LEAD]
    assert lead == pcm.lead(PERIOD)
    sent = pcm.decode(machine.port.runs[-1][2][len(lead):])
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


def stop(machine):
    """Hold A until the console has left the sound, then let go."""
    machine.pad = PAD_A
    machine.until(lambda: not machine.deaf, limit=60)
    machine.wait(3)
    machine.pad = 0
    machine.wait(2)                             # the console sees it let go


def test_a_turns_the_station_off_and_brings_the_menu_back(radio, tone):
    machine = on_air(radio(), tone)
    machine.advance(ms(300))
    before = len(machine.level_log)
    stop(machine)
    levels = played(machine)
    assert levels[-1] == 0                      # the DAC is left at its rest
    assert levels[-20:] == list(range(19, -1, -1))  # and came to it a step at a time
    assert len(levels) - before < 0.05 * RATE   # at once: A is looked at with every sample
    machine.until(lambda: machine.off, limit=30)
    assert machine.port.period == p.NESP_PERIOD     # the line is the link's again
    assert machine.asked(p.NESP_TUNER_STOP) == 1 and not machine.stick.fetching
    failed = machine.word("link_failed")
    machine.wait(gen_news.ROWS + 30)
    assert middle(machine) == MENU and machine.foot() == FOOT["SELECT"]
    assert machine.byte("sounds") == 1 and machine.word("link_failed") == failed
    assert machine.asked(p.NESP_TUNER_PLAY) == 1        # and nothing played it again


def test_the_press_that_stops_is_not_taken_for_one_that_plays(radio, tone):
    machine = on_air(radio(), tone)
    machine.advance(ms(200))
    machine.pad = PAD_A                         # and held, a second and more
    machine.until(lambda: machine.off, limit=60)
    machine.wait(90)
    assert machine.off and not machine.deaf
    machine.pad = 0
    machine.wait(30)
    assert machine.off and machine.byte("sounds") == 1
    assert machine.asked(p.NESP_TUNER_PLAY) == 1


def test_a_held_down_does_not_end_the_sound_as_it_begins(radio, tone):
    machine = radio()
    machine.until(lambda: machine.off, limit=60)
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
    machine.until(lambda: machine.off, limit=30)
    assert machine.byte("sounds") == 1 and not machine.stick.fetching
    failed = machine.word("link_failed")
    machine.wait(60)
    assert machine.word("link_failed") == failed


def test_it_can_be_played_again(radio, tone):
    machine = on_air(radio(), tone)
    machine.advance(ms(200))
    machine.press_button(p.NESP_EVENT_BUTTON_A)
    machine.advance(ms(250))
    machine.until(lambda: machine.off, limit=30)
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
    machine.until(lambda: machine.off, limit=30)
    assert not machine.stick.fetching and machine.port.period == p.NESP_PERIOD


# --- the menu ----------------------------------------------------------------------------

SCREEN = gen_screen.build_screen()
STATION = {station[0]: index for index, station in enumerate(gen_screen.STATIONS)}


def station_middle(station=0, area=0):
    """The middle as the ROM draws it: the station's own lines, its letters
    big and where it is and what it plays, over the area's."""
    lines = list(gen_screen.areas()[area])
    for index, row in enumerate(gen_screen.STATION_LINES):
        lines[row] = SCREEN.station_rows[station][index].decode("latin-1")
    return [line.rstrip() for line in lines]


MENU = station_middle(0, 0)
MENU_NEWS = station_middle(0, 1)
BLANK = station_middle(0, 2)        # a station tuned in: the menu is off, the station's lines stay


def middle(machine):
    return [line.rstrip() for line in machine.page()]


def plays(machine):
    """The modes of the PLAYs the console has sent."""
    return [bytes(payload) for service, op, payload in machine.requests()
            if (service, op) == (TUNER, p.NESP_TUNER_PLAY)]


def test_it_starts_with_a_menu_of_two_and_the_first_chosen(radio):
    machine = radio()
    machine.until(lambda: machine.off, limit=60)
    machine.wait(12)
    assert middle(machine) == MENU and machine.shown == 0x2000


@pytest.mark.parametrize("button", [PAD_DOWN, PAD_UP, PAD_SELECT])
def test_up_down_and_select_move_between_the_two(radio, button):
    machine = radio()
    machine.until(lambda: machine.off, limit=60)
    machine.press(button)
    machine.wait(12)
    assert middle(machine) == MENU_NEWS
    machine.press(button)
    machine.wait(12)
    assert middle(machine) == MENU
    assert machine.stick.fetches == 0 and not plays(machine)    # nothing is chosen until Start


def test_start_plays_what_the_menu_has_and_the_menu_goes(radio, tone):
    machine = radio()
    machine.until(lambda: machine.off, limit=60)
    machine.press(PAD_START)
    machine.until(lambda: machine.stick.fetches == 1, limit=30)
    assert plays(machine) == [bytes((p.NESP_TUNER_MODE_HIGH,))]
    assert machine.stick.fetch_url == STATION_URL
    machine.wait(15)
    assert middle(machine) == BLANK and machine.status == "TUNING"
    machine.press(PAD_DOWN)                     # which does nothing now
    machine.wait(15)
    assert middle(machine) == BLANK
    machine.press(PAD_START)                    # given up: the menu again, as it was
    machine.until(lambda: machine.off, limit=30)
    machine.wait(15)
    assert middle(machine) == MENU
    machine.press(PAD_DOWN)
    machine.press(PAD_A)
    machine.until(lambda: machine.stick.fetches == 2, limit=30)
    assert plays(machine)[-1] == bytes((p.NESP_TUNER_MODE_NEWS,))
    assert machine.stick.fetch_url == STATION_URL       # with what it is playing: the same


def turn(machine, *buttons):
    """Left or Right, a press each, let go between."""
    for button in buttons:
        machine.press(button)
        machine.wait(2)


def urls(machine):
    """The URLs the console has sent: (AT, text)."""
    return [(payload[0], bytes(payload[1:]).decode()) for service, op, payload in machine.requests()
            if (service, op) == (TUNER, p.NESP_TUNER_URL)]


@pytest.mark.parametrize("button, name, url", [
    (PAD_RIGHT, "WNYC", "https://fm939.wnyc.org/wnycfm"),
    (PAD_LEFT, "SOMAFM", "https://ice2.somafm.com/groovesalad-128-mp3"),
])
def test_left_and_right_go_round_the_stations_and_start_plays_the_one_shown(radio, button, name,
                                                                            url):
    machine = radio()
    machine.until(lambda: machine.off, limit=60)
    machine.press(button)
    machine.wait(12)
    assert middle(machine) == station_middle(STATION[name])
    machine.press(PAD_START)
    machine.until(lambda: machine.stick.fetches == 1, limit=30)
    assert machine.stick.fetch_url == url
    # In pieces, from the first, and then PLAY.
    sent = urls(machine)
    assert [at for at, _ in sent] == list(range(0, len(url), 24))
    assert "".join(text for _, text in sent) == url
    assert plays(machine) == [bytes((p.NESP_TUNER_MODE_HIGH,))]


def test_the_list_goes_round_both_ways(radio):
    machine = radio()
    machine.until(lambda: machine.off, limit=60)
    turn(machine, PAD_LEFT, PAD_RIGHT)
    machine.wait(12)
    assert middle(machine) == MENU
    turn(machine, PAD_LEFT, PAD_RIGHT, PAD_RIGHT)       # past the last, the first
    machine.wait(12)
    assert middle(machine) == station_middle(STATION["WNYC"])


OAM, OAMDMA = 0x0400, 0x4014


def needle(machine):
    """The needle's sprites as OAM has them: (y, tile, attributes, x)."""
    return [tuple(machine.memory[OAM + 4 * index + part] for part in range(4))
            for index in range(3)]


def test_the_dial_s_needle_is_at_the_station_s_frequency_or_off_the_screen(radio):
    machine = radio()
    dmas = []
    machine.memory.subscribe_to_write([OAMDMA], lambda address, value: dmas.append(value))
    machine.until(lambda: machine.off, limit=60)
    machine.wait(gen_news.ROWS + 5)                                 # the screen drawn
    assert all(y == 0xFF for y, _, _, _ in needle(machine))        # NPR: on the Internet only
    assert machine.byte("needle_dirty") == 0                       # sent
    sent = len(dmas)
    turn(machine, PAD_RIGHT)                                        # WNYC, 93.9
    machine.wait(2)
    tile, end = SCREEN.needle
    x = gen_screen.needle_x(gen_screen.STATIONS[STATION["WNYC"]])
    assert x == gen_screen.scale_x(93.9) - 3
    assert needle(machine) == [(gen_screen.NEEDLE_TOP - 1, tile, 0, x),
                               (gen_screen.NEEDLE_TOP + 7, tile, 0, x),
                               (gen_screen.NEEDLE_TOP + 15, end, 0, x)]
    assert dmas[sent:] == [OAM >> 8] and machine.byte("needle_dirty") == 0
    turn(machine, PAD_LEFT)
    machine.wait(2)
    assert all(y == 0xFF for y, _, _, _ in needle(machine))


def test_a_long_address_goes_in_pieces_and_the_station_plays_with_its_titles(radio, tone):
    url = "https://playerservices.streamtheworld.com/api/livestream-redirect/KUSCMP128.mp3"
    machine = radio()
    machine.until(lambda: machine.off, limit=60)
    turn(machine, *[PAD_RIGHT] * 4)
    machine.press(PAD_DOWN)
    machine.wait(12)
    assert middle(machine) == station_middle(STATION["KUSC"], 1)
    machine.press(PAD_START)
    machine.until(lambda: machine.stick.fetches == 1, limit=30)
    assert machine.stick.fetch_url == url and machine.stick.fetch_wants_icy
    assert [at for at, _ in urls(machine)] == [0, 24, 48, 72]


def test_the_menu_does_not_change_the_station_while_one_is_tuned_in(radio, tone):
    machine = radio()
    machine.until(lambda: machine.off, limit=60)
    machine.press(PAD_START)
    machine.until(lambda: machine.stick.fetches == 1, limit=30)
    machine.press(PAD_RIGHT)
    machine.wait(15)
    assert middle(machine) == BLANK and machine.byte("station") == 0


def test_a_station_that_fails_brings_the_menu_back(radio):
    machine = radio()
    machine.until(lambda: machine.off, limit=60)
    machine.press(PAD_DOWN)
    machine.press(PAD_START)
    machine.until(lambda: machine.stick.fetches == 1, limit=30)
    machine.wait(15)
    assert middle(machine) == BLANK
    machine.stick.fetch_done(False, b"THE SITE SAID 404")
    machine.until(lambda: machine.status == "THE SITE SAID 404", limit=30)
    machine.wait(15)
    assert middle(machine) == MENU_NEWS         # with what was chosen still chosen


# --- the station with what it is playing ------------------------------------------------

EVERY = 1000        # bytes of sound between the stream's blocks of titles
TITLES = ("Dark Chisme - Suffer Like Me", "Badmarsh & Shri - Into the Sunset",
          "Olivier Deriviere - The Land")
ARTISTS = ("DARK CHISME", "BADMARSH & SHRI", "OLIVIER DERIVIERE")
NOW_PLAYING = ["NOW PLAYING", "", "DARK CHISME", "", "", "", "SUFFER LIKE ME", "", ""]
PAGE_MS = 550       # a page sent, 0.18 seconds, and drawn, four frames and the wait for the first


class Icy:
    """A station's stream with its titles in it (ICY), as nesp32's
    tests/test_tuner.py has one: every EVERY bytes of the tone, a block,
    which has the title in the first of them and nothing in the rest."""

    def __init__(self, tone):
        self.tone, self.at = tone, 0

    def more(self, seconds, title=None):
        out = bytearray()
        for index in range(max(1, int(len(self.tone) / 4.0 * seconds) // EVERY)):
            sound = (self.tone + self.tone)[self.at:self.at + EVERY]
            self.at = (self.at + EVERY) % len(self.tone)
            block = b"\x00"
            if index == 0 and title is not None:
                text = b"StreamTitle='" + title.encode() + b"';"
                text += b"\x00" * (-len(text) % 16)
                block = bytes((len(text) // 16,)) + text
            out += sound + block
        return bytes(out)


def news_on_air(machine, tone, title=None, seconds=4.0):
    """Choose the station with what it is playing, give the nesp32 its
    stream, with this title in it or none, and run until the console is in
    the sound."""
    machine.until(lambda: machine.off, limit=60)
    count = machine.stick.fetches
    machine.press(PAD_DOWN)
    machine.press(PAD_START)
    machine.until(lambda: machine.stick.fetches == count + 1, limit=30)
    assert machine.stick.fetch_url == STATION_URL and machine.stick.fetch_wants_icy
    machine.icy = Icy(tone)
    if title is None:
        machine.stick.fetch_icy(0)
        machine.air(tone[:int(len(tone) * seconds / 4.0)])
    else:
        machine.stick.fetch_icy(EVERY)
        machine.air(machine.icy.more(seconds, title))
    machine.until(lambda: machine.deaf, limit=120)
    return machine


def retitled(machine, title):
    """The station plays something else: more of its stream says so."""
    machine.air(machine.icy.more(0.5, title))


def shown_page(machine):
    """Sit through a page being sent and drawn, and return what is shown."""
    machine.advance(ms(PAGE_MS))
    return middle(machine)


def turned(machine):
    """Have the nesp32 send a page that is waiting now, where it waits a
    couple of seconds from the last, and return it as shown."""
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


def test_the_station_with_its_titles_plays_at_its_own_rate(radio, tone, title):
    machine = news_on_air(radio(), tone, title)
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


def test_the_title_comes_with_the_sound_and_is_drawn_out_of_sight(radio, tone, title):
    machine = news_on_air(radio(), tone, title)
    assert middle(machine) == BLANK and machine.shown == 0x2000
    machine.read_log = []
    assert shown_page(machine) == NOW_PLAYING and machine.shown == 0x2800
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


def test_each_new_title_is_drawn_as_it_comes(radio, tone, title):
    machine = news_on_air(radio(), tone, title)
    pages = [shown_page(machine)]
    shown = [machine.shown]
    for new in TITLES[1:] + TITLES[:1]:
        retitled(machine, new)
        pages.append(turned(machine))
        shown.append(machine.shown)
    assert machine.deaf and not machine.ppu_strays
    assert tuple(page[2] for page in pages) == ARTISTS + ARTISTS[:1]
    assert shown == [0x2800, 0x2000, 0x2800, 0x2000]
    levels = played(machine)
    sent = pcm.decode(machine.port.runs[-1][2])
    assert levels == sent[:len(levels)]


@pytest.mark.parametrize("clock_error", [-0.01, 0.01])
def test_the_titles_come_from_a_nesp32_whose_clock_is_1_percent_off(radio, tone, title,
                                                                    clock_error):
    machine = news_on_air(radio(clock_error=clock_error), tone, title)
    pages = [shown_page(machine)]
    for new in TITLES[1:]:
        retitled(machine, new)
        pages.append(turned(machine))
    assert tuple(page[2] for page in pages) == ARTISTS
    levels = played(machine)
    sent = pcm.decode(machine.port.runs[-1][2])
    assert levels == sent[:len(levels)] and not machine.ppu_strays
    assert max(into for into, _, _ in machine.ppu_writes) < VBLANK_CYCLES - 100


def test_with_no_titles_the_station_plays_all_the_same(radio, tone):
    machine = news_on_air(radio(), tone)        # a stream that has none
    machine.advance(ms(900))
    assert machine.deaf and machine.status == "ON THE AIR"
    assert middle(machine) == BLANK and not machine.ppu_writes and not machine.ppu_strays
    levels = played(machine)
    sent = pcm.decode(machine.port.runs[-1][2])
    assert len(levels) > 0.5 * NEWS_RATE and levels == sent[:len(levels)]


@pytest.mark.parametrize("at", ["a page being sent", "a page being drawn"])
def test_a_in_the_middle_of_a_page_leaves_the_menu_whole(radio, tone, title, at):
    machine = news_on_air(radio(), tone, title)
    first = shown_page(machine)
    retitled(machine, TITLES[1])
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
    stop(machine)
    machine.until(lambda: machine.off, limit=30)
    machine.wait(gen_news.ROWS + 10)
    assert middle(machine) == MENU_NEWS and machine.shown == 0x2000
    assert not machine.ppu_strays


def test_the_nesp32s_button_ends_the_sound_with_the_titles_too(radio, tone, title):
    machine = news_on_air(radio(), tone, title)
    shown_page(machine)
    machine.press_button(p.NESP_EVENT_BUTTON_A)
    machine.advance(ms(300))
    assert not machine.deaf
    levels = played(machine)
    assert levels[-1] == 0                      # the DAC is left at its rest
    fall = levels[-100:]
    assert fall == sorted(fall, reverse=True)   # and came to it by a ramp
    machine.until(lambda: machine.off, limit=30)
    machine.wait(15)
    assert middle(machine) == MENU_NEWS and machine.shown == 0x2000
    assert not machine.stick.fetching
    failed = machine.word("link_failed")
    machine.wait(60)
    assert machine.word("link_failed") == failed


def test_a_stream_that_is_lost_with_its_titles_is_played_out(radio, tone, title):
    machine = news_on_air(radio(), tone, title, seconds=2.6)
    machine.stick.fetch_done(False, b"THE CONNECTION DROPPED")
    machine.advance(ms(4500))
    assert not machine.deaf and played(machine)[-1] == 0
    machine.until(lambda: machine.status == "THE CONNECTION DROPPED", limit=30)


def test_tuned_in_again_the_last_title_is_not_kept(radio, tone, title):
    machine = news_on_air(radio(), tone, title)
    shown_page(machine)
    machine.press_button(p.NESP_EVENT_BUTTON_A)
    machine.advance(ms(300))
    machine.until(lambda: machine.off, limit=30)
    machine.wait(15)
    machine.press(PAD_START)                    # the menu is where it was left
    machine.until(lambda: machine.stick.fetches == 2, limit=30)
    machine.stick.fetch_icy(EVERY)
    machine.air(Icy(tone).more(4.0, "Another One - From 1990"))
    machine.until(lambda: machine.deaf, limit=120)
    assert middle(machine) == BLANK and machine.shown == 0x2000
    assert shown_page(machine)[2] == "ANOTHER ONE"


def test_a_console_reset_in_the_sound_with_its_titles_is_greeted_again(radio, tone, title):
    machine = news_on_air(radio(), tone, title)
    shown_page(machine)
    machine.reset()
    machine.advance(ms(100))
    machine.until(lambda: machine.stick.hellos == 2, limit=60)
    machine.until(lambda: machine.off, limit=30)
    machine.wait(15)
    assert middle(machine) == MENU and machine.shown == 0x2000
    assert not machine.stick.fetching and machine.port.period == p.NESP_PERIOD


@pytest.mark.parametrize("news", [False, True])
def test_a_console_left_in_the_sound_is_freed_by_a_nesp32_starting_up(radio, tone, title, news):
    """The routines have no timeout. A console whose nesp32 lost its power
    waits for the rest until one starts up, whose first bytes, twelve of 0
    at the link's rate, it takes for the sound's end: a byte with no more
    to come, or with the headlines a character that is none of theirs."""
    machine = news_on_air(radio(), tone, title) if news else on_air(radio(), tone)
    machine.advance(ms(700))
    machine.power_off()
    machine.advance(ms(400))
    assert machine.deaf
    machine.power_cycle()
    machine.until(lambda: machine.stick.hellos == 1, limit=60)
    assert not machine.deaf
    machine.until(lambda: machine.off, limit=30)


# --- the foot, and B -----------------------------------------------------------------


def hint(machine, nametable=None):
    """What is over the foot."""
    return machine.screen_text(gen_screen.HINT_COLUMN, gen_screen.HINT_ROW, gen_screen.HINT_WIDTH,
                               nametable)


def test_the_foot_has_pictures_for_play_and_pause_and_on_the_air_says_a_stops(radio, tone):
    screen = gen_screen.build_screen()
    tiles = screen.chr()
    play, pause = (screen.icons[char] for char in (gen_screen.PLAY, gen_screen.PAUSE))
    assert play != pause and min(play, pause) >= 0x80        # none of the font's
    for tile, char in ((play, gen_screen.PLAY), (pause, gen_screen.PAUSE)):
        assert tiles[16 * tile:16 * tile + 16] == gen_screen.gen_ui.tile_bytes(
            gen_screen.icon_pixels(gen_screen.ICONS[char]))
    machine = radio()
    machine.until(lambda: machine.off, limit=60)
    assert machine.foot() == "A : SELECT"       # the menu's says what A does there
    assert hint(machine) == hint(machine, 0x2800) == gen_screen.HINT    # over it, the station
    on_air(machine, tone)
    assert hint(machine).strip() == hint(machine, 0x2800).strip() == ""  # which a station has not
    raw = machine.screen_text(gen_screen.FOOT_COLUMN, gen_screen.gen_ui.HELP_ROW,
                              gen_screen.FOOT_WIDTH)
    assert raw.strip() == "A : STOP"
    assert machine.screen_text(gen_screen.FOOT_COLUMN, gen_screen.gen_ui.HELP_ROW,
                               gen_screen.FOOT_WIDTH, 0x2800) == raw    # and on the other nametable


def test_b_does_nothing_on_the_menu_of_a_rom_on_no_cartridge(radio):
    machine = radio()
    machine.until(lambda: machine.off, limit=60)
    machine.press(PAD_B)
    machine.wait(30)
    assert machine.off and machine.foot() == FOOT["SELECT"]
    assert machine.byte("area") == 0 and machine.asked(p.NESP_TUNER_PLAY) == 0


def test_b_while_tuning_is_the_menu_again(radio, tone):
    machine = radio()
    machine.until(lambda: machine.off, limit=60)
    machine.press(PAD_DOWN)                     # the second line
    machine.press(PAD_START)
    machine.until(lambda: machine.status == "TUNING", limit=30)
    machine.until(lambda: machine.foot() == FOOT["BACK"], limit=30)
    machine.press(PAD_B)
    machine.until(lambda: machine.off, limit=30)
    assert machine.asked(p.NESP_TUNER_STOP) == 1 and not machine.stick.fetching
    machine.wait(gen_news.ROWS + 5)
    assert machine.page()[gen_screen.QUALITY_ROW] == gen_screen.QUALITY[1]
    assert machine.foot() == FOOT["SELECT"]


def test_on_the_air_the_foot_says_nothing_of_b(radio, tone):
    machine = on_air(radio(), tone)
    assert machine.foot() == FOOT["PLAIN"]      # B is not read in the sound
