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
STATION_URL = "https://npr-ice.streamguys1.com/live.mp3"
HIGH, NEWS = p.NESP_TUNER_MODE_HIGH, p.NESP_TUNER_MODE_NEWS
NEWS_PERIOD = p.NESP_TUNER_NEWS_PERIOD
NEWS_RATE = pcm.sample_rate(NEWS_PERIOD)
HOME, SHOW, END, IDLE = (p.NESP_TUNER_NEWS_HOME, p.NESP_TUNER_NEWS_SHOW, p.NESP_TUNER_NEWS_END,
                         p.NESP_TUNER_NEWS_IDLE)
ROWS, COLUMNS = p.NESP_TUNER_NEWS_ROWS, p.NESP_TUNER_NEWS_COLUMNS
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


def samples(run, period=PERIOD):
    """A run from its first byte, less the lead the console's routine
    settles on and does not play."""
    lead = pcm.lead(period)
    assert run[:len(lead)] == lead
    return run[len(lead):]


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
        # A UART takes what it has room for: what leaves in a millisecond,
        # so that a millisecond of the clock is one of sound. The room is a
        # millisecond's, however many writes it is taken in.
        line = stick.line
        if not hasattr(line, "paced"):     # once for a Stick that has more sets than one
            write = line.line_write

            def paced(data):
                count = write(data)
                line.room -= count
                return count

            line.line_write = line.paced = paced
        line.room = 0
        self.owed = 0.0
        assert stick.hello(app=b"NPR ", services=services).ok

    rate = RATE                     # samples a second: the mode's

    def wait(self, ms=5):
        line = self.stick.line
        for _ in range(ms):
            self.now += 1
            self.owed = min(self.owed, 1.0) + self.rate / 1000
            line.room = int(self.owed)
            self.stick.tick(self.now)
            self.owed -= int(self.owed) - line.room

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


OTHER_URL = "http://radio.example/stream.mp3"


def test_url_sets_the_station_the_next_play_tunes_in(radio):
    assert radio.ask(p.NESP_TUNER_URL, b"\x00" + OTHER_URL.encode())[0] == OFF
    assert radio.stick.fetches == 0             # nothing until PLAY
    assert radio.play() == TUNING
    assert radio.stick.fetch_url == OTHER_URL
    assert radio.stick.shown(0) == "RADIO"


def test_a_long_url_goes_in_pieces_and_each_ends_it_where_it_ends(radio):
    url = "https://example.com/" + "x" * 230
    for at in range(0, len(url), 100):
        radio.ask(p.NESP_TUNER_URL, bytes((at,)) + url[at:at + 100].encode())
    radio.ask(p.NESP_TUNER_URL, bytes((len(url) - 3,)) + b"mp3")   # sent again: the same
    url = url[:-3] + "mp3"
    assert radio.play() == TUNING
    assert radio.stick.fetch_url == url
    radio.stop()
    radio.ask(p.NESP_TUNER_URL, b"\x13/a.mp3")    # a piece cuts what was after it
    radio.play()
    assert radio.stick.fetch_url == "https://example.com/a.mp3"


def test_an_empty_url_is_npr_again(radio):
    radio.ask(p.NESP_TUNER_URL, b"\x00" + OTHER_URL.encode())
    radio.ask(p.NESP_TUNER_URL, b"\x00")
    radio.play()
    assert radio.stick.fetch_url == STATION_URL and radio.stick.shown(0) == "NPR"


@pytest.mark.parametrize("payload", [b"", bytes((201,)) + b"abc", bytes((200,)) + b"x" * 60, b"\x00a\x00b"])
def test_a_url_that_does_not_follow_on_or_is_too_long_is_refused(radio, payload):
    radio.ask(p.NESP_TUNER_URL, b"\x00" + b"y" * 100)
    radio.ask(p.NESP_TUNER_URL, b"\x64" + b"y" * 100)    # 200 of them
    assert radio.stick.ask(TUNER, p.NESP_TUNER_URL, payload).status == p.NESP_ST_BAD_ARG
    radio.play()
    assert radio.stick.fetch_url == "y" * 200      # and what was set stays


def test_play_with_another_url_retunes_and_with_the_same_goes_on(radio):
    radio.on_air()
    radio.wait(200)
    radio.stick.feed(b"\xfc" * p.NESP_SOUND_SAY)       # the console leaves the sound
    radio.hear(100)
    assert radio.state() == PAUSED
    assert radio.play() == READY                # the same station: from where it was
    assert radio.stick.fetches == 1
    radio.ask(p.NESP_TUNER_URL, b"\x00" + OTHER_URL.encode())
    assert radio.play() == TUNING               # another: tuned in afresh
    assert radio.stick.fetches == 2 and radio.stick.fetch_url == OTHER_URL


def test_a_hello_forgets_the_url(radio):
    radio.ask(p.NESP_TUNER_URL, b"\x00" + OTHER_URL.encode())
    assert radio.stick.hello(app=b"NPR ", services=(RAW, TUNER)).ok
    radio.play()
    assert radio.stick.fetch_url == STATION_URL


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
    played = levels(samples(radio.stick.line.sent))
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
    sent = samples(radio.hear(p.NESP_RAW_START_MS + 100))
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
    again = samples(radio.hear(p.NESP_RAW_START_MS + 300))
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


# --- the two modes, and what is playing ------------------------------------------------

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


EVERY = 1000            # bytes of sound between two blocks of titles: the stations' are 1024 to 16000


class Icy:
    """A station's stream with its titles in it (ICY): every EVERY bytes of
    the tone, a byte that is a block's length in 16s, and the block."""

    def __init__(self, every=EVERY):
        self.every = every
        self.at = 0                 # in the tone, which goes round

    def block(self, title):
        if title is None:
            return b"\x00"          # nothing new: what most blocks are
        text = b"StreamTitle='" + title.encode("utf-8") + b"';StreamUrl='';"
        text += b"\x00" * (-len(text) % 16)
        return bytes((len(text) // 16,)) + text

    def blocks(self, count, title=None):
        """This many blocks of sound, each with its block of titles."""
        out = bytearray()
        for _ in range(count):
            sound = TONE[self.at:self.at + self.every]
            if len(sound) < self.every:
                sound += TONE[:self.every - len(sound)]
            self.at = (self.at + self.every) % len(TONE)
            out += sound + self.block(title)
        return bytes(out)

    def seconds(self, seconds, title=None):
        """About this much of the tone, the title in its first block and
        none after."""
        count = int(len(TONE) / TONE_SECONDS * seconds) // self.every
        return self.blocks(1, title) + self.blocks(count - 1)


class TitleSet(Set):
    """A console that asks for the station with what it is playing, and a
    station that says."""

    rate = NEWS_RATE

    def __init__(self, stick, every=EVERY):
        super().__init__(stick)
        self.stream = Icy(every)

    def play(self):
        return self.ask(p.NESP_TUNER_PLAY, bytes((NEWS,)))[0]

    def on_air(self, title="Dark Chisme - Suffer Like Me", every=None):
        """Tuned in, the stream's metaint said, enough of it come, and the
        sound begun."""
        assert self.play() == TUNING
        self.stick.fetch_icy(self.stream.every if every is None else every)
        if every == 0:
            self.air()
        else:
            self.air(self.stream.seconds(TONE_SECONDS, title))
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
def titles(stick):
    return TitleSet(stick)


def page(*lines):
    """A page as the nesp32 lays it out: NOW PLAYING, a blank line, and
    these."""
    out = ["NOW PLAYING", ""] + list(lines)
    return out + [""] * (ROWS - len(out))


KEXP = page("DARK CHISME", "", "", "", "SUFFER LIKE ME")


def test_play_with_no_mode_or_the_first_is_the_station_alone(radio):
    for payload in (b"", bytes((HIGH,))):
        assert radio.ask(p.NESP_TUNER_PLAY, payload)[0] == TUNING
        assert radio.stick.fetch_url == STATION_URL
        radio.stop()
    assert radio.stick.fetches == 2
    for payload in (b"\x02", b"\x00\x00"):
        assert radio.stick.ask(TUNER, p.NESP_TUNER_PLAY, payload).status == p.NESP_ST_BAD_ARG


@pytest.mark.parametrize("mode", [HIGH, NEWS])
def test_the_station_is_fetched_at_once_and_asked_for_its_titles(radio, mode):
    assert radio.ask(p.NESP_TUNER_PLAY, bytes((mode,)))[0] == TUNING
    assert radio.stick.fetches == 1 and radio.stick.fetch_url == STATION_URL
    assert radio.stick.fetch_wants_icy and "nesp32" in radio.stick.fetch_agent


def test_the_station_with_its_titles_goes_at_its_own_rate(titles):
    titles.play()
    titles.stick.fetch_icy(EVERY)
    titles.air(titles.stream.seconds(TONE_SECONDS))
    assert titles.sound(p.NESP_TUNER_RATE) == GONE      # the other mode's
    assert titles.why() == (FAILED, b"THIS NES CANNOT PLAY IT")
    titles.on_air()
    titles.hear(p.NESP_RAW_START_MS)
    sent = titles.hear(1000)
    assert titles.stick.line.rates == [NEWS_PERIOD]
    assert 0.9 * NEWS_RATE < len(sent) < 1.15 * NEWS_RATE


def test_the_title_goes_as_the_run_begins_and_the_blocks_are_not_sound(titles):
    titles.on_air()
    sent = titles.hear(p.NESP_RAW_START_MS + 1500)
    got, rest = pages(characters(sent))
    assert got == [KEXP] and rest == []
    first = [pcm.raw_byte(byte) >> 7 for byte in sent].index(0)
    assert first == 8 * 8                               # after a few characters of nothing
    # The blocks of titles were taken out: what is left is the tone, which
    # an MP3 decoder fed them would have broken up.
    amplitude, noise = tone_in(heard(sent)[2000:], rate=NEWS_RATE)
    assert amplitude == pytest.approx(TONE_LEVEL, abs=0.02)


def test_a_new_title_goes_when_it_comes_and_the_same_one_does_not(titles):
    titles.on_air()
    got, _ = pages(characters(titles.hear(p.NESP_RAW_START_MS + 2500)))
    assert got == [KEXP]
    titles.air(titles.stream.seconds(2, "Dark Chisme - Suffer Like Me"))    # said again
    got, _ = pages(characters(titles.hear(3000)))
    assert got == []
    titles.air(titles.stream.seconds(2, "Badmarsh & Shri - Into the Sunset"))
    got, rest = pages(characters(titles.hear(3000)))
    assert got == [page("BADMARSH & SHRI", "", "", "", "INTO THE SUNSET")] and rest == []
    assert titles.stick.tuner_page == 2


@pytest.mark.parametrize("title, lines", [
    # No " - ": the whole of it, on the seven lines.
    ("You're Listening to KCLU Radio!", ["YOU'RE LISTENING TO KCLU", "RADIO!"]),
    ("This Old Heart Of Mine (is Weak For You)-Isley Bros",
     ["THIS OLD HEART OF MINE (IS", "WEAK FOR YOU)-ISLEY BROS"]),
    # A station's programme, with a dash at its end.
    ("Bullseye with Jesse Thorn-", ["BULLSEYE WITH JESSE THORN"]),
    # UTF-8, and entities, made capitals of ASCII.
    ("Beyonc\u00e9 &amp; Jay-Z - D\u00e9j\u00e0 Vu", ["BEYONCE & JAY-Z", "", "", "", "DEJA VU"]),
    # Too long for its three lines.
    ("Olivier Deriviere - " + "The Land " * 12, ["OLIVIER DERIVIERE", "", "", "",
     "THE LAND THE LAND THE LAND", "THE LAND THE LAND THE LAND", "THE LAND THE LAND THE..."]),
])
def test_a_title_is_laid_out_as_the_console_can_show_it(titles, title, lines):
    titles.on_air(title)
    got, _ = pages(characters(titles.hear(p.NESP_RAW_START_MS + 1500)))
    assert got == [page(*lines)]


@pytest.mark.parametrize("every, title", [(0, None), (EVERY, ""), (EVERY, None)])
def test_a_station_with_no_title_sends_no_page_and_plays(titles, every, title):
    titles.on_air(title, every)
    sent = titles.hear(p.NESP_RAW_START_MS + 2000)
    assert characters(sent) == [] and len(sent) > 1.5 * NEWS_RATE
    amplitude, noise = tone_in(heard(sent)[2000:], rate=NEWS_RATE)
    assert amplitude == pytest.approx(TONE_LEVEL, abs=0.02)


def test_the_stream_may_come_in_pieces_of_any_size(stick):
    for size in (1, 7, 100, 4096):
        titles = TitleSet(stick, every=500)
        titles.play()
        stick.fetch_icy(500)
        data = titles.stream.seconds(TONE_SECONDS, "Dark Chisme - Suffer Like Me")
        for start in range(0, len(data), size):
            stick.fetch_body(data[start:start + size])
        titles.wait()
        assert titles.sound(p.NESP_TUNER_NEWS_RATE) == GO
        sent = titles.hear(p.NESP_RAW_START_MS + 1500)
        assert pages(characters(sent))[0] == [KEXP]
        amplitude, noise = tone_in(heard(sent)[2000:], rate=NEWS_RATE)
        assert amplitude == pytest.approx(TONE_LEVEL, abs=0.02)
        stick.event(p.NESP_EVENT_BUTTON_A)      # off, for the next
        titles.wait(400)


def test_the_button_ends_the_sound_with_a_character_at_the_dacs_rest(titles):
    titles.on_air()
    titles.wait(p.NESP_RAW_START_MS + 100)      # in the middle of the first page
    titles.stick.event(p.NESP_EVENT_BUTTON_A)
    sent = titles.hear(400)
    assert titles.stick.line.rates == [NEWS_PERIOD, p.NESP_PERIOD]
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
    assert titles.state() == OFF and not titles.stick.fetching


def test_a_stream_that_is_lost_ends_with_the_character_too(titles):
    titles.on_air()
    titles.stick.fetch_done(False, b"THE CONNECTION DROPPED")
    sent = titles.hear(p.NESP_RAW_START_MS + 5000)
    assert characters(sent)[-1] == bytes((END,))
    assert titles.why() == (FAILED, b"THE CONNECTION DROPPED")


def test_played_again_after_a_pause_the_latest_title_goes_again(titles):
    titles.on_air()
    titles.hear(p.NESP_RAW_START_MS + 1500)
    titles.air(titles.stream.seconds(2, "Badmarsh & Shri - Into the Sunset"))
    titles.hear(3000)
    assert titles.stick.feed(b"\xfc" * p.NESP_SOUND_SAY) == b""
    titles.wait(100)
    assert titles.state() == PAUSED
    assert titles.ask(p.NESP_TUNER_PLAY, bytes((NEWS,)))[0] == READY
    assert titles.stick.fetches == 1
    assert titles.sound(p.NESP_TUNER_NEWS_RATE) == GO
    titles.stick.line.sent.clear()
    got, rest = pages(characters(titles.hear(p.NESP_RAW_START_MS + 1500)))
    assert got == [page("BADMARSH & SHRI", "", "", "", "INTO THE SUNSET")] and rest == []


def test_tuned_in_again_the_last_station_s_title_is_not_sent(titles):
    titles.on_air()
    titles.hear(p.NESP_RAW_START_MS + 1500)
    titles.stick.event(p.NESP_EVENT_BUTTON_A)
    titles.wait(400)
    assert titles.state() == OFF
    titles.stick.line.sent.clear()
    titles.on_air(None)                         # a station that says nothing
    assert titles.stick.fetches == 2
    assert characters(titles.hear(p.NESP_RAW_START_MS + 2000)) == []
