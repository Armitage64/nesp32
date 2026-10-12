"""JUKE, the jukebox's service, with no console: requests in, replies out,
and the test as the console, the clock and the nesp32's files.

The service does not decode the music, so the tracks here are any bytes in
nes-jukebox's two containers. What it must get right is the stream: every
byte once and in order whatever is lost on the way, a new epoch for
everything that should be heard at once, and a sound handed to RAW.
"""

import struct

import nesp_proto as p
import pytest
from nesp import frame

JUKE, RAW = p.NESP_SVC_JUKE, p.NESP_SVC_RAW
STOPPED, PLAYING, PAUSED, NO_TRACKS = (p.NESP_PLAYER_STOPPED, p.NESP_PLAYER_PLAYING,
                                       p.NESP_PLAYER_PAUSED, p.NESP_PLAYER_NO_TRACKS)
DRAIN = p.NESP_PLAYER_DRAIN
NEXT, PREVIOUS, PLAY = p.NESP_PRESS_NEXT, p.NESP_PRESS_PREVIOUS, p.NESP_PRESS_PLAY
WAIT, GO, GONE = p.NESP_SOUND_WAIT, p.NESP_SOUND_GO, p.NESP_SOUND_GONE
LAST = bytes((p.NESP_JUKE_SOUND_LAST,))
END = b"\x80\x00"
PERIODS = (21, 16, 14, 12, 10, 8)
ROOM = 56                       # what nes-jukebox's ROM asks for at most


def jbs(title, stream, frames=600, loop=None):
    """A .jbs file (nes-jukebox's docs/PROTOCOL.md, part 2). loop is (the
    frame, the offset in the stream) it goes back to."""
    loop_frame, loop_offset = loop if loop else (0xFFFFFFFF, 0)
    return (b"JBS\x1a" + bytes((1, 1 if loop else 0, 0, 0))
            + struct.pack("<IIII", frames, loop_frame, loop_offset, len(stream))
            + bytes((len(title),)) + title + stream)


def pcm(title, samples, period=16):
    """A .pcm file (part 4)."""
    return b"NPCM" + bytes((1, period, len(title), 0)) + title + samples


def intro(title, frames):
    """What goes ahead of a track, as nes-jukebox's tools/jbs.py has it."""
    game, dash, track = title.partition(b" - ")
    if not dash:
        game, track = b"", title
    game, track = game[:28].strip(), track[:28].strip()
    seconds = min(frames // 60, 99 * 60 + 59)
    length = ("%d:%02d " % (seconds // 60, seconds % 60))[:5].encode()
    return (b"\x80\x03" + bytes((len(game),)) + game + b"\x80\x02" + bytes((len(track),)) + track
            + b"\x80\x04" + length)


def body(seed, length):
    """Bytes that say where in which track they are."""
    return bytes((seed + 7 * index) & 0xFF for index in range(length))


# Each longer than the nesp32 reads ahead, so that the track it is on is the
# one whose bytes are coming.
ONE = jbs(b"Game - First", body(1, 300), frames=600)
TWO = jbs(b"Game - Second", body(2, 200), frames=3600, loop=(1200, 60))
THREE = jbs(b"Lonely", body(3, 250), frames=59)
ONE_STREAM = intro(b"Game - First", 600) + body(1, 300)
# Twice through its loop: all of it, then from the loop's start again.
TWO_STREAM = intro(b"Game - Second", 3600 + 2400) + body(2, 200) + body(2, 200)[60:]
THREE_STREAM = intro(b"Lonely", 59) + body(3, 250)


class Deck:
    """The console's side: where it has got to, and what it holds.

    `music` is every byte it has taken since the last flush, and `flushes`
    counts those. A real console's ring holds a kilobyte; what matters here
    is the order.
    """

    def __init__(self, stick, tracks=(), services=(JUKE, RAW), reply_max=63, **settings):
        self.stick = stick
        for track in tracks:
            stick.add_track(track)
        if settings:
            stick.set_juke(**settings)
        self.now = 0
        self.hello(services, reply_max)

    def hello(self, services=(JUKE, RAW), reply_max=63):
        assert self.stick.hello(app=b"JUKE", reply_max=reply_max, services=services).ok
        self.epoch = 0
        self.pos = 0
        self.fresh = True       # as the ROM does: the next reply's music is all it holds
        self.music = b""
        self.flushes = 0
        self.state = None
        self.drained = False
        self.underruns = 0
        self.wait()

    def wait(self, ms=5):
        """Time passes: the nesp32 does what it does between requests."""
        for _ in range(ms):
            self.now += 1
            self.stick.tick(self.now)

    def ask(self, room=ROOM, lose_reply=False):
        """One STREAM exchange. Returns the bytes it brought."""
        request = bytes((self.epoch, self.pos, room, self.underruns & 0xFF))
        reply = self.stick.ask(JUKE, p.NESP_JUKE_STREAM, request)
        self.wait()
        assert reply.ok
        if lose_reply:
            return None
        state, epoch, data = reply.payload[0], reply.payload[1], reply.payload[2:]
        assert len(data) <= room
        if epoch != self.epoch or self.fresh:
            self.fresh = False
            self.epoch, self.pos, self.music = epoch, 0, b""
            self.flushes += 1
        self.pos = (self.pos + len(data)) & 0xFF
        self.music += data
        self.state = state & p.NESP_PLAYER_STATE
        self.drained = bool(state & DRAIN)
        return data

    def pull(self, count, room=ROOM):
        """Ask until this much music has come since the last flush."""
        self.ask(0)             # whatever was pressed since, the nesp32 says so first
        for _ in range(4000):
            if len(self.music) >= count:
                return self.music
            self.ask(room)
        raise AssertionError("only %d of %d bytes came" % (len(self.music), count))

    def press(self, buttons):
        reply = self.stick.ask(JUKE, p.NESP_JUKE_BUTTON, bytes((buttons,)))
        self.wait()
        assert reply.ok and len(reply.payload) == 1
        return reply.payload[0]

    def sound(self, rate, epoch=None):
        epoch = self.epoch if epoch is None else epoch
        reply = self.stick.ask(JUKE, p.NESP_JUKE_SOUND, bytes((epoch, rate)))
        assert reply.ok and len(reply.payload) == 2
        return reply.payload[1]

    def hear(self, ms=p.NESP_RAW_START_MS + 50):
        """Sit through a run, as a console that took GO does: deaf and
        dumb. Returns what the nesp32 put on the line."""
        self.stick.line.sent.clear()
        self.wait(ms)
        return bytes(self.stick.line.sent)


@pytest.fixture
def deck(stick):
    return Deck(stick, (ONE, TWO, THREE))


# --- the stream ---------------------------------------------------------------------


def test_it_answers_only_after_a_hello_asks_for_it(stick):
    stick.add_track(ONE)
    request = bytes((0, 0, ROOM, 0))
    assert stick.ask(JUKE, p.NESP_JUKE_STREAM, request).status == p.NESP_ST_INACTIVE
    assert stick.hello(services=[JUKE]).ok
    assert stick.ask(JUKE, p.NESP_JUKE_STREAM, request).ok


def test_nothing_plays_until_a_button_says_so(deck):
    assert deck.ask() == b"" and deck.state == STOPPED and not deck.drained
    deck.wait(100)
    assert deck.ask() == b""
    assert deck.stick.shown(0) == "1/3 Game - First"
    assert deck.stick.shown(1) == ""            # the track has both lines to itself


def test_a_stick_with_no_music_says_so(stick):
    deck = Deck(stick)
    assert deck.ask() == b"" and deck.state == NO_TRACKS
    assert deck.press(PLAY) == NO_TRACKS
    assert deck.ask() == b"" and deck.state == NO_TRACKS
    assert (stick.shown(0), stick.shown(1)) == ("", "")


def test_play_sends_the_track_with_its_names_ahead_of_it(deck):
    assert deck.press(PLAY) == PLAYING
    assert deck.pull(len(ONE_STREAM))[:len(ONE_STREAM)] == ONE_STREAM
    assert deck.state == PLAYING and deck.flushes == 1


@pytest.mark.parametrize("room", [1, 5, 24, 56, 61])
def test_the_playlist_is_one_stream_whatever_the_console_has_room_for(deck, room):
    """Each track's names, its bytes, round its loop, then the next; and
    after the last, the first again."""
    deck.press(PLAY)
    whole = ONE_STREAM + TWO_STREAM + THREE_STREAM + ONE_STREAM
    assert deck.pull(len(whole), room)[:len(whole)] == whole
    assert deck.flushes == 1 and not deck.drained


def test_no_file_is_read_on_the_way_to_a_reply(deck):
    """The stand-in's files abort if they are read while a request is being
    answered (host/nesp_host.c). That this test ends at all is the check;
    here it also sees that the reading was done, between requests."""
    deck.press(PLAY)
    deck.pull(len(ONE_STREAM + TWO_STREAM))
    assert deck.stick.track_reads > 6


def test_a_reply_that_was_lost_is_sent_again(deck):
    deck.press(PLAY)
    first = deck.ask(24)
    assert deck.ask(24, lose_reply=True) is None
    assert deck.ask(24, lose_reply=True) is None
    deck.pull(len(ONE_STREAM), 24)
    assert deck.music[:len(ONE_STREAM)] == ONE_STREAM and first == ONE_STREAM[:24]
    assert deck.stick.juke_resent == 2


def test_a_lost_reply_is_made_up_in_full_when_the_console_has_more_room(deck):
    deck.press(PLAY)
    deck.ask(10)
    deck.ask(10, lose_reply=True)
    assert deck.ask(40) == ONE_STREAM[10:50]


def test_a_request_that_was_lost_changes_nothing(deck):
    deck.press(PLAY)
    deck.ask(24)
    # The nesp32 never hears this one: a console's request, one bit wrong.
    damaged = bytearray(frame(JUKE, p.NESP_JUKE_STREAM, 200, bytes((deck.epoch, deck.pos, 24, 0))))
    damaged[6] ^= 0x04
    assert deck.stick.feed(bytes(damaged)) == b""
    deck.pull(len(ONE_STREAM), 24)
    assert deck.music[:len(ONE_STREAM)] == ONE_STREAM and deck.stick.juke_resent == 0


def test_a_reply_is_no_longer_than_the_console_said_it_takes(stick):
    deck = Deck(stick, (ONE,), reply_max=31)
    deck.press(PLAY)
    assert len(deck.ask(56)) == 29              # the state and the epoch are two of the 31
    assert deck.pull(len(ONE_STREAM))[:len(ONE_STREAM)] == ONE_STREAM


def test_the_last_track_ends_the_playlist_when_it_is_not_to_repeat(stick):
    deck = Deck(stick, (ONE, THREE), repeat=False)
    deck.press(PLAY)
    whole = ONE_STREAM + THREE_STREAM + END
    assert deck.pull(len(whole)) == whole
    assert deck.drained                         # play what you have: no more is coming
    assert deck.ask() == b"" and deck.drained and deck.state == PLAYING
    # Play then starts the track it ended on, from its beginning.
    assert deck.press(PLAY) == PLAYING
    assert deck.pull(len(THREE_STREAM + END)) == THREE_STREAM + END and deck.flushes == 2


def test_a_track_plays_once_through_when_loops_is_one(stick):
    deck = Deck(stick, (TWO,), loops=1, repeat=False)
    deck.press(PLAY)
    whole = intro(b"Game - Second", 3600) + body(2, 200) + END
    assert deck.pull(len(whole)) == whole


def test_a_long_title_is_cut_to_the_screen_and_a_title_with_no_game_has_none(stick):
    long = b"A Game With A Very Long Name Indeed - And A Track Whose Name Is Longer"
    deck = Deck(stick, (jbs(long, body(1, 5), frames=60 * (12 * 60 + 34)),), repeat=False)
    deck.press(PLAY)
    expected = (b"\x80\x03\x1c" + b"A Game With A Very Long Name"
                + b"\x80\x02\x1c" + b"And A Track Whose Name Is Lo" + b"\x80\x0412:34")
    assert deck.pull(len(expected) + 7) == expected + body(1, 5) + END
    assert intro(long, 60 * (12 * 60 + 34)) == expected
    assert THREE_STREAM.startswith(b"\x80\x03\x00\x80\x02\x06Lonely\x80\x040:00 ")


# --- buttons --------------------------------------------------------------------------


def test_next_and_previous_change_the_track_at_once(deck):
    deck.press(PLAY)
    deck.pull(100)
    assert deck.press(NEXT) == PLAYING
    assert deck.pull(100) == TWO_STREAM[:len(deck.music)]
    assert deck.flushes == 2                    # the console dropped the first track's music
    assert deck.stick.shown(0) == "2/3 Game - Second"
    # The track the buttons count from is the one being sent, which near a
    # track's end is the next: the console is a few seconds behind.
    assert deck.pull(len(TWO_STREAM))[:len(TWO_STREAM)] == TWO_STREAM
    assert deck.stick.juke_index == 2
    deck.press(PREVIOUS)
    deck.press(PREVIOUS)
    assert deck.pull(100) == ONE_STREAM[:len(deck.music)]
    assert deck.flushes == 3 and deck.stick.juke_index == 0
    deck.press(PREVIOUS)                        # round the start, to the last
    assert deck.pull(100) == THREE_STREAM[:len(deck.music)]
    deck.press(NEXT)                            # and round the end
    assert deck.pull(100) == ONE_STREAM[:len(deck.music)]


def test_next_plays_from_stopped(deck):
    assert deck.press(NEXT) == PLAYING
    assert deck.pull(len(TWO_STREAM))[:len(TWO_STREAM)] == TWO_STREAM


def test_play_pauses_and_goes_on_from_where_it_was(deck):
    deck.press(PLAY)
    deck.pull(60)
    held = len(deck.music)
    assert deck.press(PLAY) == PAUSED
    for _ in range(20):
        assert deck.ask() == b"" and deck.state == PAUSED and not deck.drained
    assert deck.press(PLAY) == PLAYING
    deck.pull(len(ONE_STREAM))
    assert deck.music[:len(ONE_STREAM)] == ONE_STREAM and len(deck.music) > held
    assert deck.flushes == 1                    # nothing was dropped


def test_a_button_request_sent_twice_is_done_once(deck):
    """The console that hears no reply sends its request again, unchanged,
    and the nesp32 answers as it did then and does nothing more."""
    deck.press(PLAY)
    stick = deck.stick
    request = frame(JUKE, p.NESP_JUKE_BUTTON, 77, bytes((NEXT,)))
    first = stick.feed(request)
    assert stick.feed(request) == first and stick.repeats == 1
    assert stick.juke_index == 1


def test_the_sticks_own_buttons_do_what_the_consoles_do(deck):
    stick = deck.stick
    stick.event(p.NESP_EVENT_BUTTON_A)
    assert deck.pull(50) == ONE_STREAM[:len(deck.music)]
    stick.event(p.NESP_EVENT_BUTTON_POWER)      # next
    assert deck.pull(100) == TWO_STREAM[:len(deck.music)]
    stick.event(p.NESP_EVENT_BUTTON_B)          # previous
    assert deck.pull(20) == ONE_STREAM[:len(deck.music)]
    stick.event(p.NESP_EVENT_BUTTON_A)
    assert deck.ask() == b"" and deck.state == PAUSED
    # The service took them: nothing is waiting for the console to ask about.
    reply = stick.ask(p.NESP_SVC_SYS, p.NESP_SYS_EVENT)
    assert reply.payload == bytes((p.NESP_EVENT_NONE, 0)) and not reply.attention


def test_another_roms_stick_buttons_still_go_to_the_console(stick):
    stick.add_track(ONE)
    assert stick.hello(services=[]).ok
    stick.event(p.NESP_EVENT_BUTTON_A)
    reply = stick.ask(p.NESP_SVC_SYS, p.NESP_SYS_EVENT)
    assert reply.payload == bytes((p.NESP_EVENT_BUTTON_A, 0))


# --- what can go wrong ------------------------------------------------------------------


def test_a_console_that_is_reset_finds_the_music_stopped_at_the_same_track(deck):
    deck.press(NEXT)
    deck.pull(40)
    deck.hello()
    assert deck.ask() == b"" and deck.state == STOPPED
    assert deck.stick.juke_index == 1 and deck.stick.shown(0) == "2/3 Game - Second"
    deck.press(PLAY)
    assert deck.pull(len(TWO_STREAM))[:len(TWO_STREAM)] == TWO_STREAM


def test_a_console_that_holds_what_was_never_sent_starts_the_track_again(deck):
    """One of the two was switched off and on, and by chance their epochs
    agree. The nesp32 starts where both know where they are."""
    deck.press(PLAY)
    deck.pull(60)
    deck.pos = (deck.pos + 100) & 0xFF
    deck.ask()
    assert deck.flushes == 2
    assert deck.pull(len(ONE_STREAM))[:len(ONE_STREAM)] == ONE_STREAM


def test_a_file_that_is_not_a_track_is_passed_over(stick):
    deck = Deck(stick, (b"not music at all" * 4, ONE, b"JBS\x1a\x01", THREE), repeat=False)
    assert deck.ask() == b"" and deck.state == STOPPED
    deck.press(PLAY)
    whole = ONE_STREAM + THREE_STREAM + END
    assert deck.pull(len(whole)) == whole
    assert stick.shown(0) == "4/4 Lonely"


def test_a_stick_with_no_file_it_can_read_has_no_music(stick):
    deck = Deck(stick, (b"junk", jbs(b"Cut", body(1, 50))[:40]))
    deck.press(PLAY)
    deck.wait(20)
    assert deck.ask() == b"" and deck.state == NO_TRACKS
    assert deck.press(PLAY) == NO_TRACKS


def test_a_file_that_ends_early_gives_what_it_has_and_the_next_follows(stick):
    deck = Deck(stick, (TWO, THREE), repeat=False)
    deck.press(PLAY)
    deck.pull(20)
    stick.cut_track(0, len(TWO) - 50)           # after it was looked at, and begun
    whole = intro(b"Game - Second", 6000) + body(2, 200)[:150] + THREE_STREAM + END
    assert deck.pull(len(whole)) == whole


def test_the_consoles_underruns_are_kept_as_a_total(deck):
    deck.press(PLAY)
    deck.underruns = 250                        # where its count stood when the nesp32 first heard
    deck.ask()
    deck.underruns = 253
    deck.ask()
    deck.underruns = 260                        # the byte has wrapped
    deck.ask()
    assert deck.stick.juke_underruns == 10


@pytest.mark.parametrize("request_", [b"", bytes(3), bytes(5)])
def test_a_request_of_the_wrong_length_is_refused(deck, request_):
    for op in (p.NESP_JUKE_STREAM, p.NESP_JUKE_SOUND, p.NESP_JUKE_BUTTON):
        assert deck.stick.ask(JUKE, op, request_).status == p.NESP_ST_BAD_ARG
    assert deck.stick.ask(JUKE, 0x7F).status == p.NESP_ST_NO_OP


# --- sampled sound ------------------------------------------------------------------------

SAMPLES = bytes(0x80 | (index * 5) & 0x7F for index in range(700))
NOISE = pcm(b"Tape - Speech", SAMPLES, period=16)
NOISE_FRAMES = 700 * 60 * 11 // ((1789773 + 8) // 16)
NOISE_STREAM = intro(b"Tape - Speech", NOISE_FRAMES) + b"\x80\x05\x01"


@pytest.fixture
def tape(stick):
    """A deck whose second track is sound, playing, with the music before
    it all taken and the sound's record with it."""
    deck = Deck(stick, (THREE, NOISE, ONE))
    deck.press(PLAY)
    whole = THREE_STREAM + NOISE_STREAM
    assert deck.pull(len(whole)) == whole
    return deck


def test_a_sounds_place_in_the_stream_is_its_names_and_a_record(tape):
    assert tape.drained                         # and then nothing: play what you have
    for _ in range(5):
        assert tape.ask() == b"" and tape.drained and tape.state == PLAYING
    assert tape.stick.line.rates == []


def test_the_sound_goes_as_a_run_at_its_own_rate_and_the_music_follows(tape):
    line = tape.stick.line
    assert tape.sound(1) == GO
    assert tape.hear() == SAMPLES + LAST
    assert line.rates == [16, p.NESP_PERIOD]
    # The music after it starts from an empty ring, as a change of track does.
    assert tape.pull(100) == ONE_STREAM[:len(tape.music)]
    assert tape.flushes == 2 and tape.stick.shown(0) == "3/3 Game - First"


@pytest.mark.parametrize("period", PERIODS)
def test_every_rate_a_sound_may_have(stick, period):
    deck = Deck(stick, (pcm(b"Tone", SAMPLES[:50], period),), repeat=False)
    deck.press(PLAY)
    rate = PERIODS.index(period)
    record = intro(b"Tone", 0) + bytes((0x80, 0x05, rate))
    assert deck.pull(len(record)) == record
    assert deck.sound(rate) == GO
    assert deck.hear() == SAMPLES[:50] + LAST
    assert stick.line.rates == [period, p.NESP_PERIOD]
    assert deck.pull(2) == END and deck.drained


def test_a_console_that_did_not_hear_go_asks_again_and_the_wait_starts_again(tape):
    assert tape.sound(1) == GO
    tape.wait(p.NESP_RAW_LISTEN_MS - 20)
    assert tape.sound(1) == GO                  # a frame later, the same request
    tape.wait(p.NESP_RAW_LISTEN_MS - 20)
    assert tape.stick.line.rates == [] and not tape.stick.line.sent
    assert tape.hear() == SAMPLES + LAST


def test_a_console_that_cannot_play_it_gets_the_next_track(tape):
    assert tape.sound(p.NESP_JUKE_SOUND_REFUSED) == GONE
    tape.wait(300)
    assert tape.stick.line.rates == []
    assert tape.pull(len(ONE_STREAM))[:len(ONE_STREAM)] == ONE_STREAM and tape.flushes == 2


def test_a_rate_that_is_not_the_sounds_is_refused(tape):
    assert tape.sound(4) == GONE
    assert tape.pull(len(ONE_STREAM))[:len(ONE_STREAM)] == ONE_STREAM


def test_a_rom_that_did_not_ask_for_raw_gets_no_sound(stick):
    deck = Deck(stick, (NOISE, ONE), services=(JUKE,))
    deck.press(PLAY)
    deck.pull(len(NOISE_STREAM))
    assert deck.sound(1) == GONE
    assert deck.pull(len(ONE_STREAM))[:len(ONE_STREAM)] == ONE_STREAM


def test_a_sound_asked_for_from_before_a_jump_is_gone(tape):
    """The console came to a sound's record, and a button on the nesp32 has
    since moved to another sound. It must not get that one under this
    one's name."""
    stale = tape.epoch
    tape.stick.event(p.NESP_EVENT_BUTTON_B)     # back to the track before
    tape.stick.event(p.NESP_EVENT_BUTTON_POWER)  # and on to the sound again
    tape.wait(20)
    assert tape.sound(1, epoch=stale) == GONE
    tape.wait(300)
    assert tape.stick.line.rates == []
    assert tape.pull(len(NOISE_STREAM)) == NOISE_STREAM and tape.flushes == 2
    assert tape.sound(1) == GO                  # under its own epoch, it plays
    assert tape.hear() == SAMPLES + LAST


def test_a_paused_stick_holds_a_sound_until_it_is_resumed(tape):
    tape.press(PLAY)
    for _ in range(10):
        assert tape.sound(1) == WAIT
        tape.wait(17)
    assert tape.stick.line.rates == []
    tape.press(PLAY)
    assert tape.sound(1) == GO
    assert tape.hear() == SAMPLES + LAST


def test_the_consoles_button_in_the_wait_calls_the_sound_off(tape):
    """It did not hear GO, or it would not be reading its controller."""
    assert tape.sound(1) == GO
    tape.wait(30)
    assert tape.press(PREVIOUS) == PLAYING
    tape.wait(400)
    assert tape.stick.line.rates == [] and not tape.stick.line.sent
    assert tape.pull(len(THREE_STREAM))[:len(THREE_STREAM)] == THREE_STREAM


def test_a_request_for_the_stream_in_the_wait_leaves_the_sound_due(tape):
    assert tape.sound(1) == GO
    tape.wait(30)
    assert tape.ask() == b"" and tape.drained
    tape.wait(400)
    assert tape.stick.line.rates == []
    assert tape.sound(1) == GO
    assert tape.hear() == SAMPLES + LAST


@pytest.mark.parametrize("button, state, track", [
    (p.NESP_EVENT_BUTTON_A, STOPPED, 1),        # the nesp32's button does not pause one
    (p.NESP_EVENT_BUTTON_B, PLAYING, 0),
    (p.NESP_EVENT_BUTTON_POWER, PLAYING, 2),
])
def test_a_button_on_the_stick_ends_a_sound_early(tape, button, state, track):
    line = tape.stick.line
    line.room = 16                              # a UART that takes a little at a time
    assert tape.sound(1) == GO
    line.sent.clear()
    tape.wait(p.NESP_RAW_START_MS + 5)
    assert 0 < len(line.sent) < len(SAMPLES) and line.rates == [16]
    tape.stick.event(button)
    tape.wait(40)
    # It stops at a sample, with the byte that leaves the DAC at 0.
    sent = bytes(line.sent)
    assert sent[-1:] == LAST and SAMPLES.startswith(sent[:-1]) and len(sent) < len(SAMPLES)
    assert line.rates == [16, p.NESP_PERIOD]
    tape.ask()
    assert tape.state == state and tape.stick.juke_index == track and tape.flushes == 2
    if state == STOPPED:
        # Play then plays the sound from its start.
        tape.press(PLAY)
        assert tape.pull(len(NOISE_STREAM)) == NOISE_STREAM
        line.room = None
        assert tape.sound(1) == GO
        assert tape.hear() == SAMPLES + LAST


def sample_levels(sent):
    """What the console's DAC makes of bytes on the wire."""
    return [(int("{:08b}".format(byte)[::-1], 2) ^ 0x3F) & 0x7F for byte in sent]


def hush(tape, after=30):
    """A console takes GO, plays this many ms of the sound, and says that
    it has left it. Returns what the nesp32 sent."""
    line = tape.stick.line
    line.room = 10                              # about what leaves in a millisecond
    assert tape.sound(1) == GO
    line.sent.clear()
    tape.wait(p.NESP_RAW_START_MS + after)
    assert tape.stick.feed(b"\xfc" * p.NESP_SOUND_SAY) == b""
    tape.wait(40)
    line.room = None
    return bytes(line.sent)


def test_a_console_heard_during_a_sound_pauses_it_where_it_was(tape):
    """A console that left the sound for a press of its button A says so,
    at the link's rate, into a line that is the run's."""
    flushes = tape.flushes
    sent = hush(tape)
    # It stops at a sample, with the byte that leaves the DAC at 0.
    assert sent[-1:] == LAST and SAMPLES.startswith(sent[:-1]) and len(sent) < len(SAMPLES)
    assert tape.stick.line.rates == [16, p.NESP_PERIOD]
    # Paused, in the same epoch, with the sound still due.
    assert tape.ask() == b"" and tape.state == PAUSED and tape.flushes == flushes
    assert tape.sound(1) == p.NESP_SOUND_WAIT and tape.stick.juke_index == 1
    assert tape.press(PLAY) == PLAYING
    assert tape.ask() == b"" and tape.drained and tape.flushes == flushes
    assert tape.sound(1) == GO
    rest = tape.hear()
    # From where it was when the console was heard, 30 ms in at ten samples
    # a millisecond, and not from where the UART had got to; and from the
    # DAC's rest, over 20 ms.
    at = len(SAMPLES) + 1 - len(rest)
    assert abs(at - 305) <= 20 and at < len(sent) - 1
    ramp = 10169 // 50
    assert rest[ramp:] == SAMPLES[at + ramp:] + LAST
    rise, whole = sample_levels(rest[:ramp]), sample_levels(SAMPLES[at:at + ramp])
    assert rise[0] == 0 and all(got <= level for got, level in zip(rise, whole))
    assert rise[-1] >= whole[-1] - 1
    # And then the music after it, in a new epoch.
    tape.ask()
    assert tape.state == PLAYING and tape.stick.juke_index == 2 and tape.flushes == flushes + 1


def test_a_sound_paused_twice_goes_on_from_the_second_place(tape):
    hush(tape, after=10)
    tape.press(PLAY)
    again = hush(tape, after=10)
    assert again[-1:] == LAST
    tape.press(PLAY)
    assert tape.sound(1) == GO
    rest = tape.hear()
    at = len(SAMPLES) + 1 - len(rest)
    assert abs(at - 2 * 102) <= 30 and rest[-100:] == SAMPLES[-99:] + LAST


@pytest.mark.parametrize("button, track", [(NEXT, 2), (PREVIOUS, 0)])
def test_the_track_can_be_changed_while_a_sound_is_paused(tape, button, track):
    flushes = tape.flushes
    hush(tape)
    assert tape.press(button) == PLAYING and tape.stick.juke_index == track
    assert tape.sound(1) == GONE                # asked for from before the jump
    tape.ask()
    assert tape.flushes == flushes + 1 and tape.stick.line.rates == [16, p.NESP_PERIOD]


def test_a_sound_changed_away_from_and_back_to_plays_from_its_start(tape):
    hush(tape)
    tape.press(NEXT)
    tape.press(PREVIOUS)
    assert tape.pull(len(NOISE_STREAM)) == NOISE_STREAM
    assert tape.sound(1) == GO
    assert tape.hear() == SAMPLES + LAST


def test_a_stray_byte_during_a_sound_does_not_pause_it(tape):
    assert tape.sound(1) == GO
    tape.stick.line.sent.clear()
    tape.wait(p.NESP_RAW_START_MS)
    tape.stick.feed(b"\x00\x00\x00")
    tape.wait(100)
    assert bytes(tape.stick.line.sent) == SAMPLES + LAST
    tape.ask()
    assert tape.state == PLAYING and tape.stick.juke_index == 2


def test_a_button_on_the_stick_in_the_wait_is_kept_for_the_sound(tape):
    """The console may have heard GO and gone deaf, so the nesp32 cannot
    change its mind: the sound starts, and the button ends it at once."""
    assert tape.sound(1) == GO
    tape.wait(30)
    tape.stick.event(p.NESP_EVENT_BUTTON_POWER)
    assert tape.hear() == LAST
    tape.ask()
    assert tape.state == PLAYING and tape.stick.juke_index == 2


def test_a_button_on_the_stick_in_the_wait_is_done_at_once_if_the_console_asks_again(tape):
    assert tape.sound(1) == GO
    tape.wait(30)
    tape.stick.event(p.NESP_EVENT_BUTTON_POWER)
    assert tape.sound(1) == GONE                # it is not deaf: no sound, the next track
    tape.wait(400)
    assert tape.stick.line.rates == []
    assert tape.pull(len(ONE_STREAM))[:len(ONE_STREAM)] == ONE_STREAM


def test_a_sound_can_be_the_whole_playlist_and_repeat(stick):
    deck = Deck(stick, (NOISE,))
    deck.press(PLAY)
    for turn in range(3):
        assert deck.pull(len(NOISE_STREAM)) == NOISE_STREAM
        assert deck.sound(1) == GO
        assert deck.hear() == SAMPLES + LAST
        assert deck.flushes == turn + 1


def test_the_screen_keeps_the_track_while_the_line_is_the_sounds(tape):
    tape.stick.line.busy = True
    assert tape.sound(1) == GO
    tape.wait(p.NESP_RAW_START_MS + 600)
    assert (tape.stick.shown(0), tape.stick.shown(1)) == ("2/3 Tape - Speech", "")
