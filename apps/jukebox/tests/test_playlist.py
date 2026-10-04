import jbs
from playlist import END_OF_TRACK, PlaylistSource


def song(frames, loop_frame=None, title=""):
    encoded = jbs.encode(frames, loop_frame)
    return jbs.JbsFile(stream=encoded.data, total_frames=len(frames), loop_frame=loop_frame,
                       loop_offset=encoded.loop_offset, title=title)


A = song([[(0x00, 0x30)], [(0x00, 0x31)], [], [], [(0x00, 0x32)]], loop_frame=1)
B = song([[(0x04, 0x40)], [(0x04, 0x41)]])


def titled(title, track, loops=1):
    """A track's stream as a playlist sends it: its names and length first.
    loops is the playlist's, for a looping track's length."""
    frames = jbs.play_frames(track.total_frames, track.loop_frame, loops)
    return jbs.intro(title, frames) + track.stream


INFO = (jbs.Control, jbs.Title, jbs.Game, jbs.Length)


def drain(source, chunk=5):
    out = bytearray()
    while True:
        data = source.take(chunk)
        if not data:
            return bytes(out)
        out += data


def writes(stream):
    frames, tail = jbs.decode(stream)
    return [[item for item in frame if not isinstance(item, INFO)] for frame in frames]


def announced(stream):
    """The (game, track, length) of each track's records in a stream."""
    frames, tail = jbs.decode(stream)
    items = [item for frame in frames + [tail] for item in frame
             if isinstance(item, (jbs.Title, jbs.Game, jbs.Length))]
    assert [type(item) for item in items] == [jbs.Game, jbs.Title, jbs.Length] * (len(items) // 3)
    return [tuple(item.text for item in items[index:index + 3])
            for index in range(0, len(items), 3)]


def test_frame_units_cover_the_stream_at_safe_cuts():
    data = A.stream
    units = jbs.frame_units(data)
    assert units[0] == (0, 2)  # the init control is its own unit
    assert [start for start, _ in units[1:]] == [end for _, end in units[:-1]]
    assert units[-1][1] == len(data)
    assert A.loop_offset in [start for start, _ in units]


def test_frame_units_keep_a_chain_with_its_record():
    data = bytes([0x00, 0x81, 0x01, 0x30, 0xA0, 0x0F])
    assert jbs.frame_units(data) == [(0, 6)]


def test_looping_track_plays_its_loop_n_times_then_the_next_track():
    source = PlaylistSource([("A", A), ("B", B)], loops=2)
    stream = drain(source)
    a_frames = writes(A.stream)
    loop = a_frames[1:]
    assert writes(stream) == a_frames + loop + writes(B.stream) + [[]]  # [] is the end
    assert stream.endswith(END_OF_TRACK)


def test_repeat_starts_the_playlist_over():
    source = PlaylistSource([("B", B)], loops=1, repeat=True)
    stream = source.take(len(titled("B", B)) * 3)
    assert stream == titled("B", B) * 3


def test_skip_lands_on_a_frame_boundary():
    started = []
    source = PlaylistSource([("A", A), ("B", B)], loops=5, on_track=lambda i, t: started.append(t))
    first = source.take(3)          # partway into A's first frame record
    source.skip(1)
    rest = drain(source)
    stream = first + rest
    frames = writes(stream)
    # A's frames up to the unit that was already started, then all of B,
    # then the end-of-track frame.
    assert frames[-len(writes(B.stream)) - 1:] == writes(B.stream) + [[]]
    assert started == ["A", "B"]
    jbs.decode(stream)  # never a torn frame


def test_jump_switches_at_once_and_drops_what_was_pending():
    started = []
    source = PlaylistSource([("A", A), ("B", B)], loops=5, on_track=lambda i, t: started.append(t))
    source.take(3)                  # generates a whole frame; 3 bytes of it are taken
    source.jump(1)
    assert source.take(len(titled("B", B))) == titled("B", B)   # none of A's leftover first
    source.jump(1)                  # wraps to A
    assert source.take(len(titled("A", A, 5))) == titled("A", A, 5)
    assert started == ["A", "B", "A"]


def test_skip_backwards_wraps_and_restart_replays():
    source = PlaylistSource([("A", A), ("B", B)], loops=1)
    source.skip(-1)
    assert source.take(len(titled("B", B))) == titled("B", B)
    source.restart()
    assert source.take(len(titled("B", B))) == titled("B", B)


def test_each_track_is_announced_once_by_game_name_and_length():
    long_name = "A track name that is far too long to fit"
    source = PlaylistSource([("A", A), ("Some Game - " + long_name, B)], loops=3)
    stream = drain(source)
    # A is 5 frames and loops from its second, three times through: 13
    # frames, under a second. Its loop repeats without the records. A name
    # too long for the screen's line loses its end.
    assert announced(stream) == [("", "A", "0:00 "), ("Some Game", long_name[:28], "0:00 ")]
    assert stream.startswith(b"\x80\x03\x00\x80\x02\x01A\x80\x040:00 " + A.stream[:2])
    assert jbs.frame_units(stream)[:4] == [(0, 3), (3, 7), (7, 14), (14, 16)]


def test_lengths_count_the_loops_a_playlist_plays():
    assert jbs.play_frames(600, None, 4) == 600
    assert jbs.play_frames(600, 120, 1) == 600
    assert jbs.play_frames(600, 120, 3) == 600 + 2 * 480
    assert jbs.length_text(59) == b"0:00 "
    assert jbs.length_text(60 * 83) == b"1:23 "
    assert jbs.length_text(60 * 60 * 12 + 60 * 5) == b"12:05"
    assert jbs.length_text(10 ** 9) == b"99:59"
    assert jbs.length_text(None) == b"-:-- "
    assert jbs.split_title("Mega Man 2 - Dr. Wily - Stage 1") == ("Mega Man 2", "Dr. Wily - Stage 1")
    assert jbs.split_title("Just a name") == ("", "Just a name")


def test_a_title_longer_than_the_line_is_malformed():
    import pytest

    with pytest.raises(jbs.StreamError, match="title"):
        jbs.decode(bytes([0x80, 0x02, 29]) + b"x" * 29)
    with pytest.raises(jbs.StreamError, match="truncated"):
        jbs.frame_units(bytes([0x80, 0x02, 5]) + b"abc")


# -- sound tracks --------------------------------------------------------------

def hello(count=1000, period=16):
    import pcm
    return pcm.Sound("Voices - Hello", period, pcm.encode([index & 0x7F for index in range(count)]))


def test_a_sound_tracks_place_in_the_stream_is_its_names_and_a_record():
    voice = hello(10169)        # a second of it
    source = PlaylistSource([("A", A), ("Voices - Hello", voice), ("B", B)], loops=1)
    first = titled("A", A)
    assert source.take(len(first)) == first and source.sound is None
    # Then the sound's names and length, its record, and nothing more.
    place = jbs.intro("Voices - Hello", voice.frames) + jbs.sound_record(voice.rate)
    assert announced(place) == [("Voices", "Hello", "0:00 ")] and voice.frames == 59
    assert source.take(len(place) - 1) == place[:-1]
    assert source.sound is voice and source.index == 1
    assert source.take(100) == place[-1:] and source.take(100) == b""
    assert not source.finished
    source.sound_done()
    assert source.sound is None
    assert source.take(1000) == titled("B", B) + END_OF_TRACK and source.finished


def test_a_jump_or_a_restart_leaves_a_sound_that_was_waiting():
    started = []
    source = PlaylistSource([("Voices - Hello", hello()), ("B", B)], loops=1,
                            on_track=lambda index, title: started.append(title))
    drain(source)
    assert source.sound is not None
    source.jump(1)
    assert source.sound is None and source.take(1000) == titled("B", B) + END_OF_TRACK
    source.jump(-1)
    drain(source)
    assert source.sound is not None
    source.restart()                # the NES was reset: the sound is due again
    assert source.sound is None
    drain(source)
    assert source.sound is not None
    assert started == ["Voices - Hello", "B", "Voices - Hello", "Voices - Hello"]


def test_a_playlist_of_one_sound_repeats_or_ends():
    source = PlaylistSource([("Voices - Hello", hello())], loops=3)
    place = drain(source)
    source.sound_done()
    assert drain(source) == END_OF_TRACK and source.finished
    again = PlaylistSource([("Voices - Hello", hello())], repeat=True)
    assert drain(again) == place
    again.sound_done()
    assert drain(again) == place and not again.finished
