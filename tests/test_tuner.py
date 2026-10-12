"""TUNER: a radio station from the Internet as sampled sound (tuner.c).

The test is the Internet: it hands the nesp32 the station's stream, an MP3
of a tone (fixtures/README.md), in the pieces a fetch brings. What the
nesp32 then puts on the line is read back as the console's DAC would have
it, with the jukebox's own tools.
"""

import math
import os
import re
import sys

import pytest

import nesp_proto as p

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "apps", "jukebox", "tools"))

import pcm  # noqa: E402
import wav2pcm  # noqa: E402

TUNER, RAW = p.NESP_SVC_TUNER, p.NESP_SVC_RAW
OFF, NO_WIFI, TUNING = p.NESP_TUNER_OFF, p.NESP_TUNER_NO_WIFI, p.NESP_TUNER_TUNING
READY, FAILED, PAUSED = p.NESP_TUNER_READY, p.NESP_TUNER_FAILED, p.NESP_TUNER_PAUSED
WAIT, GO, GONE = p.NESP_SOUND_WAIT, p.NESP_SOUND_GO, p.NESP_SOUND_GONE
PERIOD = p.NESP_TUNER_PERIOD
NEWS_URL = "https://feeds.npr.org/1001/rss.xml"
STATION_URL = "https://npr-ice.streamguys1.com/live.mp3"
HIGH, NEWS = p.NESP_TUNER_MODE_HIGH, p.NESP_TUNER_MODE_NEWS
NEWS_PERIOD = p.NESP_TUNER_NEWS_PERIOD
NEWS_RATE = pcm.sample_rate(NEWS_PERIOD)
HOME, SHOW, END, IDLE = (p.NESP_TUNER_NEWS_HOME, p.NESP_TUNER_NEWS_SHOW, p.NESP_TUNER_NEWS_END,
                         p.NESP_TUNER_NEWS_IDLE)
ROWS, COLUMNS = p.NESP_TUNER_NEWS_ROWS, p.NESP_TUNER_NEWS_COLUMNS
with open(os.path.join(os.path.dirname(__file__), "fixtures", "npr_news.xml"), "rb") as _handle:
    FEED = _handle.read()
RATE = pcm.sample_rate(PERIOD)              # samples a second on the wire
RAMP = int(RATE) // 50                      # 20 ms
LAST = p.NESP_JUKE_SOUND_LAST
# The fixture's tone, as it comes out of a decoder: the encoder took its
# half of full scale down a twentieth, and added a frame or two of silence.
TONE_HZ, TONE_LEVEL, TONE_SECONDS = 1000, 0.475, 4.0

with open(os.path.join(HERE, "fixtures", "tone_1khz.mp3"), "rb") as handle:
    TONE = handle.read()


def levels(sent):
    """What the console's DAC is set to by each byte of a run."""
    return [pcm.raw_byte(byte) & (pcm.LEVELS - 1) for byte in sent]


def heard(sent):
    """A run as sound, -1 to 1: each level through the DAC's curve."""
    return [2 * wav2pcm.DAC[level] / wav2pcm.DAC[-1] - 1 for level in levels(sent)]


def tone_in(samples, hertz=TONE_HZ, rate=RATE):
    """(the amplitude of a tone of this pitch in the samples, the RMS of
    everything else)."""
    count = len(samples)
    mean = sum(samples) / count
    angle = 2 * math.pi * hertz / rate
    cosine = sum((s - mean) * math.cos(angle * n) for n, s in enumerate(samples)) * 2 / count
    sine = sum((s - mean) * math.sin(angle * n) for n, s in enumerate(samples)) * 2 / count
    rest = [s - mean - cosine * math.cos(angle * n) - sine * math.sin(angle * n)
            for n, s in enumerate(samples)]
    return math.hypot(cosine, sine), math.sqrt(sum(r * r for r in rest) / count)


class Set:
    """The console's side, and the clock."""

    def __init__(self, stick, services=(RAW, TUNER)):
        self.stick = stick
        self.now = 0
        stick.set_wifi(p.NESP_WIFI_JOINED)
        # A UART takes what it has room for: about what leaves in a
        # millisecond, so that a millisecond of the clock is one of sound.
        stick.line.room = 20
        assert stick.hello(app=b"NPR ", services=services).ok

    def wait(self, ms=5):
        for _ in range(ms):
            self.now += 1
            self.stick.tick(self.now)

    def ask(self, op, payload=b""):
        reply = self.stick.ask(TUNER, op, payload)
        self.wait()
        assert reply.ok
        return reply.payload

    def state(self):
        return self.ask(p.NESP_TUNER_STATE)[0]

    def why(self):
        payload = self.ask(p.NESP_TUNER_STATE)
        return payload[0], bytes(payload[1:])

    def play(self):
        return self.ask(p.NESP_TUNER_PLAY)[0]

    def stop(self):
        return self.ask(p.NESP_TUNER_STOP)[0]

    def sound(self, rate=p.NESP_TUNER_RATE):
        payload = self.ask(p.NESP_TUNER_SOUND, bytes((rate,)))
        assert len(payload) == 2
        return payload[1]

    def air(self, data=TONE, fetch=None):
        """More of the station's stream, in the pieces a fetch brings.
        Returns whether the nesp32 still wants it."""
        wanted = True
        for start in range(0, len(data), 1024):
            wanted = self.stick.fetch_body(data[start:start + 1024], fetch)
        self.wait()
        return wanted

    def tune(self):
        """Play, and the stream until the station is ready."""
        assert self.play() == TUNING
        self.air()
        assert self.state() == READY

    def on_air(self):
        """A station playing: the console took GO, and is deaf."""
        self.tune()
        assert self.sound() == GO
        self.stick.line.sent.clear()
        self.wait(p.NESP_RAW_START_MS)

    def hear(self, ms):
        """Sit through this much of a run. Returns what came."""
        self.stick.line.sent.clear()
        self.wait(ms)
        return bytes(self.stick.line.sent)


@pytest.fixture
def radio(stick):
    return Set(stick)


# --- tuning ---------------------------------------------------------------------------


def test_it_answers_only_after_a_hello_asks_for_it(stick):
    assert stick.ask(TUNER, p.NESP_TUNER_STATE).status == p.NESP_ST_INACTIVE
    assert stick.hello(services=[RAW, TUNER]).ok
    reply = stick.ask(TUNER, p.NESP_TUNER_STATE)
    assert reply.ok and bytes(reply.payload) == bytes((OFF,))
    assert stick.fetches == 0                   # nothing until a button says so


def test_play_fetches_the_station(radio):
    assert radio.play() == TUNING
    assert radio.stick.fetches == 1
    assert radio.stick.fetch_url == "https://npr-ice.streamguys1.com/live.mp3"
    assert "nesp32" in radio.stick.fetch_agent
    assert radio.stick.shown(0) == "NPR" and radio.stick.shown(1) == "TUNING"
    assert radio.play() == TUNING               # asked again, it is the same fetch
    assert radio.stick.fetches == 1


def test_without_wifi_it_says_so(stick):
    radio = Set(stick)
    stick.set_wifi(p.NESP_WIFI_IDLE)
    assert radio.play() == NO_WIFI
    assert stick.fetches == 0
    stick.set_wifi(p.NESP_WIFI_JOINED)
    assert radio.play() == TUNING


def test_it_is_ready_when_two_seconds_are_held(radio):
    radio.play()
    half = len(TONE) // 2                       # under two seconds of sound
    radio.air(TONE[:half])
    assert radio.state() == TUNING
    assert 0 < radio.stick.tuner_held < RATE * p.NESP_TUNER_READY_MS / 1000
    assert radio.sound() == WAIT
    radio.air(TONE[half:])
    assert radio.state() == READY
    # All of the tone but what the decoder holds back to be sure of a frame.
    assert TONE_SECONDS - 0.5 < radio.stick.tuner_held / RATE < TONE_SECONDS
    assert radio.stick.shown(1) == "READY"


def test_a_stream_that_cannot_be_had_fails_and_can_be_tried_again(radio):
    radio.play()
    radio.stick.fetch_done(False, b"THE SITE SAID 404")
    assert radio.why() == (FAILED, b"THE SITE SAID 404")
    assert radio.stick.shown(1) == "THE SITE SAID 404"
    assert radio.sound() == GONE
    assert radio.play() == TUNING
    assert radio.stick.fetches == 2


def test_a_fetch_that_cannot_start_fails(radio):
    radio.stick.refuse_fetches()
    assert radio.play() == FAILED
    assert radio.why() == (FAILED, b"THE NESP32 IS BUSY")


def test_stop_gives_the_stream_up(radio):
    radio.tune()
    old = radio.stick.fetch_id
    assert radio.stop() == OFF
    assert radio.stick.fetch_stops >= 1 and radio.stick.tuner_held == 0
    assert not radio.air(TONE[:4096], fetch=old)    # what was on its way is not wanted
    assert radio.stick.tuner_held == 0
    assert radio.sound() == GONE


def test_a_stream_that_is_not_mp3_plays_nothing(radio):
    radio.play()
    radio.air(bytes(range(256)) * 64)
    assert radio.state() == TUNING and radio.stick.tuner_held == 0


def test_a_full_ring_loses_its_oldest_second(radio):
    radio.play()
    for _ in range(5):                          # 19 seconds, into a ring of under 13
        radio.air()
    held, dropped = radio.stick.tuner_held, radio.stick.tuner_dropped
    assert held <= 256 * 1024 and held > 256 * 1024 - 2 * RATE
    assert dropped > 0 and dropped % int(RATE) == 0
    assert held + dropped == pytest.approx(5 * TONE_SECONDS * RATE, rel=0.03)
    assert radio.state() == READY


def test_with_little_memory_the_ring_is_smaller(stick):
    stick.alloc_most(128 * 1024)
    radio = Set(stick)
    radio.play()
    for _ in range(3):
        radio.air()
    assert 128 * 1024 - 2 * RATE < stick.tuner_held <= 128 * 1024


def test_with_no_memory_it_fails(stick):
    stick.alloc_most(1024)
    radio = Set(stick)
    assert radio.play() == FAILED
    assert radio.why() == (FAILED, b"THE NESP32 IS OUT OF MEMORY")


# --- the sound ------------------------------------------------------------------------


def test_the_station_goes_as_a_run_at_its_rate(radio):
    radio.tune()
    line = radio.stick.line
    assert radio.sound() == GO
    radio.wait(p.NESP_RAW_START_MS - 10)
    assert line.rates == [PERIOD] and not line.sent     # not before its time
    sent = radio.hear(1000)
    # The screen says so, and no more; how the ring fares is in the log.
    assert radio.stick.shown(1) == "ON THE AIR"
    assert re.fullmatch(r"npr: on the air, \d+s held, dry 0, cut 0", radio.stick.watched)
    assert 0.9 * RATE < len(sent) < 1.1 * RATE
    assert all(pcm.raw_byte(byte) & pcm.MORE for byte in sent)      # none is the last


def test_what_the_console_plays_is_the_tone(radio):
    radio.on_air()
    radio.wait(100)                             # past the ramp
    amplitude, rest = tone_in(heard(radio.hear(1000)))
    assert amplitude == pytest.approx(TONE_LEVEL, abs=0.01)
    assert rest < 0.012                         # 7 bits, through a curve


def test_the_sound_rises_from_the_dacs_rest(radio):
    radio.tune()
    assert radio.sound() == GO
    radio.stick.line.sent.clear()
    radio.wait(p.NESP_RAW_START_MS + 60)
    played = levels(radio.stick.line.sent)
    assert played[0] == 0
    assert max(played[:RAMP // 4]) < max(played[RAMP // 2:RAMP]) < max(played[RAMP:])
    middle = wav2pcm.nearest_level(0.5)
    assert min(played[RAMP:]) < middle < max(played[RAMP:])


def test_go_asked_for_again_starts_the_wait_again(radio):
    radio.tune()
    assert radio.sound() == GO
    radio.wait(p.NESP_RAW_LISTEN_MS - 20)
    assert radio.sound() == GO                  # the console did not hear
    radio.wait(p.NESP_RAW_LISTEN_MS - 20)
    assert radio.stick.line.rates == [] and not radio.stick.line.sent
    radio.wait(p.NESP_RAW_START_MS)
    assert radio.stick.line.rates == [PERIOD] and radio.stick.line.sent


def test_a_console_that_asks_for_something_else_is_not_sent_it(radio):
    radio.tune()
    assert radio.sound() == GO
    assert radio.state() == READY               # so it is not waiting for samples
    radio.wait(p.NESP_RAW_START_MS + 50)
    assert radio.stick.line.rates == [] and not radio.stick.line.sent
    assert radio.sound() == GO                  # and may ask for them yet


@pytest.mark.parametrize("rate", [1, p.NESP_JUKE_SOUND_REFUSED])
def test_a_console_that_cannot_play_it_is_told_why(radio, rate):
    radio.tune()
    assert radio.sound(rate) == GONE
    assert radio.why() == (FAILED, b"THIS NES CANNOT PLAY IT")
    assert radio.stick.line.rates == []


def test_a_rom_that_did_not_ask_for_raw_gets_no_sound(stick):
    radio = Set(stick, services=(TUNER,))
    radio.tune()
    assert radio.sound() == GONE
    assert radio.why() == (FAILED, b"THE NESP32 CANNOT SEND IT")


def test_a_dry_ring_holds_the_dac_until_a_second_has_come(radio):
    radio.on_air()
    sent = radio.hear(5000)                     # all that was held, and then nothing new
    assert radio.stick.tuner_dry == 1 and radio.stick.tuner_held == 0
    assert len(set(sent[-1000:])) == 1          # the level it stopped at, over and over
    assert pcm.raw_byte(sent[-1]) & pcm.MORE
    assert radio.stick.line.rates == [PERIOD]   # and the run goes on
    radio.air(TONE[:len(TONE) // 8])            # under a second: not enough to go on with
    assert len(set(radio.hear(200))) == 1
    radio.air()
    again = heard(radio.hear(1000)[-5000:])
    assert (max(again) - min(again)) / 2 == pytest.approx(TONE_LEVEL, abs=0.03)
    assert radio.stick.tuner_dry == 1


def test_a_stream_that_is_lost_is_played_out_and_the_run_ends(radio):
    radio.on_air()
    radio.stick.fetch_done(False, b"THE CONNECTION DROPPED")
    sent = radio.hear(5000)
    line = radio.stick.line
    assert line.rates == [PERIOD, p.NESP_PERIOD]        # the line is the link's again
    assert sent[-1] == LAST and LAST not in sent[:-1]
    assert len(sent) > 2 * RATE                 # what was held was played first
    fall = levels(sent[-1 - RAMP:-1])
    assert fall == sorted(fall, reverse=True) and fall[-1] == 0
    assert levels(sent[-1:]) == [0]             # the DAC is left at its rest
    assert radio.why() == (FAILED, b"THE CONNECTION DROPPED")
    assert radio.stick.tuner_dry == 0


def test_a_station_that_ends_by_itself_is_lost_too(radio):
    radio.on_air()
    radio.stick.fetch_done(True)
    radio.hear(5000)
    assert radio.why() == (FAILED, b"THE STATION WENT OFF THE AIR")


def test_the_nesp32s_button_ends_the_sound(radio):
    radio.on_air()
    radio.wait(200)
    radio.stick.event(p.NESP_EVENT_BUTTON_A)
    sent = radio.hear(200)
    assert sent[-1] == LAST
    assert len(sent) < 0.15 * RATE              # at once: the ramp, and what the UART held
    fall = levels(sent[-1 - RAMP:-1])
    assert fall == sorted(fall, reverse=True) and fall[-1] == 0
    assert radio.stick.line.rates == [PERIOD, p.NESP_PERIOD]
    assert radio.state() == OFF
    assert radio.stick.tuner_held == 0 and not radio.stick.fetching


def test_the_button_before_the_sound_begins_ends_it_as_it_begins(radio):
    """The console may have heard GO and gone deaf: it must be sent an end."""
    radio.tune()
    assert radio.sound() == GO
    radio.stick.event(p.NESP_EVENT_BUTTON_A)
    sent = radio.hear(p.NESP_RAW_START_MS + 100)
    assert sent[-1] == LAST and set(levels(sent)) == {0}
    assert radio.state() == OFF


def test_the_button_starts_and_stops_the_station(radio):
    radio.stick.event(p.NESP_EVENT_BUTTON_A)
    assert radio.state() == TUNING and radio.stick.fetches == 1
    radio.stick.event(p.NESP_EVENT_BUTTON_A)
    assert radio.state() == OFF
    # The other buttons are not the station's: the console hears of them.
    radio.stick.event(p.NESP_EVENT_BUTTON_B)
    reply = radio.stick.ask(p.NESP_SVC_SYS, p.NESP_SYS_EVENT)
    assert bytes(reply.payload)[:1] == bytes((p.NESP_EVENT_BUTTON_B,))


def test_a_console_heard_during_the_sound_pauses_the_station(radio):
    """A console that left the sound for a press of its button A says so,
    at the link's rate, into a line that is the run's."""
    radio.on_air()
    radio.wait(200)
    assert radio.stick.feed(b"\xfc" * p.NESP_SOUND_SAY) == b""
    sent = radio.hear(100)
    assert sent[-1] == LAST and len(sent) < 300         # no ramp: nobody is listening
    assert radio.stick.line.rates == [PERIOD, p.NESP_PERIOD]
    assert radio.state() == PAUSED and radio.stick.fetching and radio.stick.fetches == 1
    held = radio.stick.tuner_held
    assert held > RATE
    # It is fetched still, and the sound is not to be had until PLAY.
    assert radio.air(TONE[:len(TONE) // 4])
    assert radio.stick.tuner_held > held and radio.state() == PAUSED
    assert radio.sound() == GONE
    assert radio.play() == READY and radio.stick.fetches == 1
    assert radio.sound() == GO
    again = radio.hear(p.NESP_RAW_START_MS + 300)
    assert LAST not in again and len(again) > 0.25 * RATE
    assert levels(again[:1]) == [0]                     # from the DAC's rest, as the first time


def test_stop_and_the_button_turn_a_paused_station_off(radio):
    for off in (radio.stop, lambda: radio.stick.event(p.NESP_EVENT_BUTTON_A)):
        radio.on_air()
        radio.stick.feed(b"\xfc" * p.NESP_SOUND_SAY)
        radio.wait(100)
        assert radio.state() == PAUSED
        off()
        assert radio.state() == OFF and not radio.stick.fetching
        assert radio.stick.tuner_held == 0


def test_a_station_lost_while_it_is_paused_fails(radio):
    radio.on_air()
    radio.stick.feed(b"\xfc" * p.NESP_SOUND_SAY)
    radio.wait(100)
    assert radio.state() == PAUSED
    radio.stick.fetch_done(False, b"THE CONNECTION DROPPED")
    radio.wait()
    assert radio.why() == (FAILED, b"THE CONNECTION DROPPED")


def test_a_console_that_was_reset_in_the_sound_turns_the_station_off(radio):
    """Its hello, at the wrong rate, pauses; said again when the line is
    the link's, it starts the service from nothing."""
    radio.on_air()
    radio.wait(200)
    assert radio.stick.feed(b"\xf8\xe0\xf8\x80\xfe") == b""
    radio.wait(100)
    assert radio.stick.line.rates == [PERIOD, p.NESP_PERIOD]
    assert radio.stick.hello(app=b"NPR ", services=(RAW, TUNER)).ok
    assert radio.state() == OFF and not radio.stick.fetching


def test_a_stray_byte_during_the_sound_does_not_end_it(radio):
    radio.on_air()
    radio.stick.feed(b"\x00")
    radio.wait(2500)
    radio.stick.feed(b"\x00\x00")               # long after: they do not add up
    radio.wait(100)
    assert radio.stick.line.rates == [PERIOD]
    assert LAST not in radio.stick.line.sent


def test_a_hello_starts_it_from_nothing(radio):
    radio.tune()
    assert radio.stick.hello(app=b"NPR ", services=[RAW, TUNER]).ok
    assert radio.state() == OFF
    assert radio.stick.tuner_held == 0 and not radio.stick.fetching


def test_another_rom_takes_its_memory_back(radio):
    radio.tune()
    old = radio.stick.fetch_id
    held = radio.stick.allocated
    assert radio.stick.hello(services=[]).ok
    assert radio.stick.allocated == held - 1    # the ring; the decoder's is kept
    assert not radio.air(TONE[:4096], fetch=old)
    assert radio.stick.shown(0) == "" and radio.stick.shown(1) == ""


# --- the two modes, and the headlines --------------------------------------------------------

def characters(sent):
    """What a console makes of the eighth bit of a run's samples. Nothing
    is 1s; the first 0 after it begins a character, and eight bits make
    one, back to back until one is nothing again. Returns the characters
    that were not nothing, each run of them as bytes."""
    bits = [pcm.raw_byte(byte) >> 7 for byte in sent]
    out = []
    at = 0
    while at < len(bits):
        if bits[at]:
            at += 1
            continue
        burst = bytearray()
        while at + 8 <= len(bits):
            char = int("".join(map(str, bits[at:at + 8])), 2)
            at += 8
            if char >= 0x80:
                break
            burst.append(char)
        else:
            at = len(bits)
        out.append(bytes(burst))
    return out


def pages(bursts):
    """The pages in a run's characters, a list of lines each, and whatever
    else there was."""
    out, rest = [], []
    for burst in bursts:
        if burst[:1] == bytes((HOME,)) and burst[-1:] == bytes((SHOW,)):
            text = burst[1:-1]
            assert len(text) == ROWS * COLUMNS and all(0x20 <= char < 0x60 for char in text)
            out.append([text[row * COLUMNS:(row + 1) * COLUMNS].decode("ascii").rstrip()
                        for row in range(ROWS)])
        else:
            rest.append(burst)
    return out, rest


class NewsSet(Set):
    """A console that asks for the station with the headlines."""

    def __init__(self, stick):
        super().__init__(stick)
        stick.line.room = 12        # about what leaves in a millisecond at this rate

    def play(self, feed=FEED, fed=True):
        """PLAY with the headlines, and unless told not to, what becomes of
        their fetch: the feed, or none to be had."""
        state = self.ask(p.NESP_TUNER_PLAY, bytes((NEWS,)))[0]
        if fed and self.stick.fetching and self.stick.fetch_url == NEWS_URL:
            if feed is None:
                self.stick.fetch_done(False, b"THE SITE DID NOT ANSWER")
            else:
                for start in range(0, len(feed), 1024):
                    if not self.stick.fetch_body(feed[start:start + 1024]):
                        break
                self.stick.fetch_done()
            self.wait()
        return state

    def on_air(self, feed=FEED):
        assert self.play(feed) == TUNING
        self.air()
        assert self.state() == READY
        assert self.sound(p.NESP_TUNER_NEWS_RATE) == GO

    def hear(self, ms):
        """Sit through this much of a run, from the reply that agreed to
        it or from where the last of these left off. Returns what came:
        every byte, since the characters are counted from the run's
        first."""
        self.wait(ms)
        sent = bytes(self.stick.line.sent)
        self.stick.line.sent.clear()
        return sent


@pytest.fixture
def news(stick):
    return NewsSet(stick)


FIRST = ["A CONSOLE FROM 1985 LEARNS", "TO READ THE NEWS", "",
         "ENGINEERS SAY THE MACHINE'S", "2 KILOBYTES OF MEMORY HOLD", "FOUR STORIES AT A TIME,",
         "\"WHICH IS PLENTY,\" ONE SAID", "& LAUGHED.", ""]
STORIES = [
    FIRST,                  # entities, in a text that is not CDATA; the story itself left out
    # CDATA, with tags and UTF-8 in it; a headline of more than three lines.
    ["CAFE OWNERS WEIGH A LONGER", "HEADLINE THAN THREE LINES OF", "TWENTY-EIGHT CHARACTERS...",
     "", "THE CAFE - A FIXTURE OF THE", "NEIGHBORHOOD - REOPENED. IT", "IS SHORT.", "", ""],
    # The item with no headline was passed over; this one has no summary.
    ["SHORT ONE", "", "", "", "", "", "", "", ""],
    # A summary cut where the page ends.
    ["A SUMMARY THAT RUNS ON AND", "ON", "",
     "THIS SUMMARY IS FAR TOO LONG", "FOR THE SIX OR SEVEN LINES", "THAT A PAGE HAS LEFT UNDER",
     "ITS HEADLINE, SO IT HAS TO", "BE CUT SOMEWHERE, AND WHERE", "IT IS CUT IT ENDS WITH..."],
    ["A FIFTH STORY THAT IS NOT", "WANTED", "", "THERE ARE FOUR PAGES.", "", "", "", "", ""],
]
assert all(len(story) == ROWS for story in STORIES)


def test_play_with_no_mode_or_the_first_is_the_station_alone(radio):
    for payload in (b"", bytes((HIGH,))):
        assert radio.ask(p.NESP_TUNER_PLAY, payload)[0] == TUNING
        assert radio.stick.fetch_url == STATION_URL
        radio.stop()
    assert radio.stick.fetches == 2
    for payload in (b"\x02", b"\x00\x00"):
        assert radio.stick.ask(TUNER, p.NESP_TUNER_PLAY, payload).status == p.NESP_ST_BAD_ARG


def test_with_the_headlines_their_feed_is_fetched_and_then_the_station(news):
    assert news.play(fed=False) == TUNING
    assert news.stick.fetches == 1 and news.stick.fetch_url == NEWS_URL
    assert "nesp32" in news.stick.fetch_agent
    assert news.play(fed=False) == TUNING       # asked again, it is the same fetch
    news.wait(500)
    assert news.stick.fetches == 1              # and the station waits for it
    news.stick.fetch_body(FEED)
    news.stick.fetch_done()
    news.wait()
    assert news.stick.fetches == 2 and news.stick.fetch_url == STATION_URL
    assert news.state() == TUNING
    news.air()
    assert news.state() == READY


def test_the_station_with_the_headlines_goes_at_its_own_rate(news):
    news.play()
    news.air()
    assert news.sound(p.NESP_TUNER_RATE) == GONE        # the other mode's
    assert news.why() == (FAILED, b"THIS NES CANNOT PLAY IT")
    news.play()
    news.air()
    assert news.sound(p.NESP_TUNER_NEWS_RATE) == GO
    news.hear(p.NESP_RAW_START_MS)
    sent = news.hear(1000)
    assert news.stick.line.rates == [NEWS_PERIOD]
    assert 0.9 * NEWS_RATE < len(sent) < 1.15 * NEWS_RATE


def test_the_first_page_goes_as_the_run_begins_in_the_samples_eighth_bit(news):
    news.on_air()
    sent = news.hear(p.NESP_RAW_START_MS + 1500)
    chars = characters(sent)
    got, rest = pages(chars)
    assert got == [FIRST] and rest == []
    first = [pcm.raw_byte(byte) >> 7 for byte in sent].index(0)
    assert first == 8 * 8                               # after a few characters of nothing
    # And the sound is the sound: seven bits of every byte, as without.
    amplitude, noise = tone_in(heard(sent)[2000:], rate=NEWS_RATE)
    assert amplitude == pytest.approx(TONE_LEVEL, abs=0.02)


def test_a_page_every_half_minute_and_round_again(news):
    news.on_air()
    sent = news.hear(p.NESP_RAW_START_MS + 5 * p.NESP_TUNER_NEWS_TURN_MS + 3000)
    got, rest = pages(characters(sent))
    assert got == STORIES + [STORIES[0]] and rest == []
    # Half a minute from the start of one to the start of the next.
    bits = [pcm.raw_byte(byte) >> 7 for byte in sent]
    starts = [at for at in range(8, len(bits)) if not bits[at] and all(bits[at - 8:at])]
    gaps = {later - sooner for sooner, later in zip(starts, starts[1:])}
    assert len(starts) == 6 and all(0 <= gap - int(NEWS_RATE) * 30 < 8 for gap in gaps)


def test_the_feed_may_come_in_pieces_of_any_size(stick):
    whole = None
    for size in (1024, 1, 7, 100):
        news = NewsSet(stick)
        news.play(fed=False)
        for start in range(0, len(FEED), size):
            news.stick.fetch_body(FEED[start:start + size])
        news.stick.fetch_done()
        news.wait()
        news.air()
        assert news.sound(p.NESP_TUNER_NEWS_RATE) == GO
        got, _ = pages(characters(news.hear(p.NESP_RAW_START_MS + 1500)))
        whole = whole or got
        assert got == whole == [FIRST]
        stick.event(p.NESP_EVENT_BUTTON_A)      # off, for the next
        news.wait(400)


@pytest.mark.parametrize("feed", [None, b"", b"<html>Not found</html>"])
def test_with_no_feed_there_are_no_headlines_and_the_station_plays(news, feed):
    news.on_air(feed)
    assert news.stick.fetches == 2
    sent = news.hear(p.NESP_RAW_START_MS + 2000)
    assert characters(sent) == [] and len(sent) > 1.5 * NEWS_RATE


def test_one_story_is_shown_once(news):
    news.on_air(FEED[:FEED.index(b"<item>", FEED.index(b"<item>") + 1)] + b"</channel></rss>")
    got, rest = pages(characters(news.hear(p.NESP_RAW_START_MS + p.NESP_TUNER_NEWS_TURN_MS + 3000)))
    assert got == [FIRST, FIRST] and rest == []        # sent again: it is all there is


def test_the_button_ends_the_sound_with_a_character_at_the_dacs_rest(news):
    news.on_air()
    news.wait(p.NESP_RAW_START_MS + 100)        # in the middle of the first page
    news.stick.event(p.NESP_EVENT_BUTTON_A)
    sent = news.hear(400)
    assert news.stick.line.rates == [NEWS_PERIOD, p.NESP_PERIOD]
    bursts = characters(sent)
    # The page was cut short, at a character, and the one after says so.
    assert len(bursts) == 1 and bursts[0][0] == HOME and bursts[0][-1] == END
    assert SHOW not in bursts[0] and len(bursts[0]) < ROWS * COLUMNS
    # It came after the ramp, with the DAC at rest, and a few samples
    # follow it: the console takes each bit a sample late.
    bits = [pcm.raw_byte(byte) >> 7 for byte in sent]
    levels = [raw & 0x7F for raw in map(pcm.raw_byte, sent)]
    last = max(at for at, bit in enumerate(bits) if not bit)
    assert levels[last - 7:] == [0] * (len(levels) - last + 7) and len(levels) - last > 2
    assert news.state() == OFF and not news.stick.fetching


def test_a_stream_that_is_lost_ends_with_the_character_too(news):
    news.on_air()
    news.stick.fetch_done(False, b"THE CONNECTION DROPPED")
    sent = news.hear(p.NESP_RAW_START_MS + 5000)
    assert characters(sent)[-1] == bytes((END,))
    assert news.why() == (FAILED, b"THE CONNECTION DROPPED")


def test_played_again_after_a_pause_the_page_goes_again_and_has_its_half_minute(news):
    news.on_air()
    news.hear(p.NESP_RAW_START_MS + p.NESP_TUNER_NEWS_TURN_MS + 2000)   # the second page is up
    assert news.stick.feed(b"\xfc" * p.NESP_SOUND_SAY) == b""
    news.wait(100)
    assert news.state() == PAUSED
    assert news.ask(p.NESP_TUNER_PLAY, bytes((NEWS,)))[0] == READY
    assert news.stick.fetches == 2
    assert news.sound(p.NESP_TUNER_NEWS_RATE) == GO
    news.stick.line.sent.clear()
    got, rest = pages(characters(news.hear(p.NESP_RAW_START_MS + p.NESP_TUNER_NEWS_TURN_MS + 2000)))
    assert got == [STORIES[1], STORIES[2]] and rest == []


def test_tuned_in_again_the_headlines_are_fetched_again_from_the_first(news):
    news.on_air()
    news.hear(p.NESP_RAW_START_MS + p.NESP_TUNER_NEWS_TURN_MS + 2000)
    news.stick.event(p.NESP_EVENT_BUTTON_A)
    news.wait(400)
    assert news.state() == OFF
    news.stick.line.sent.clear()
    news.on_air(FEED.replace(b"A console from 1985", b"Another one from 1990"))
    assert news.stick.fetches == 4
    got, _ = pages(characters(news.hear(p.NESP_RAW_START_MS + 1500)))
    assert got[0][0] == "ANOTHER ONE FROM 1990 LEARNS"
