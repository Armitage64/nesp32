import jbs
from playlist import END_OF_TRACK, PlaylistSource


def song(frames, loop_frame=None, title=""):
    encoded = jbs.encode(frames, loop_frame)
    return jbs.JbsFile(stream=encoded.data, total_frames=len(frames), loop_frame=loop_frame,
                       loop_offset=encoded.loop_offset, title=title)


A = song([[(0x00, 0x30)], [(0x00, 0x31)], [], [], [(0x00, 0x32)]], loop_frame=1)
B = song([[(0x04, 0x40)], [(0x04, 0x41)]])


def drain(source, chunk=5):
    out = bytearray()
    while True:
        data = source.take(chunk)
        if not data:
            return bytes(out)
        out += data


def writes(stream):
    frames, tail = jbs.decode(stream)
    return [[item for item in frame if not isinstance(item, jbs.Control)] for frame in frames]


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
    stream = source.take(len(B.stream) * 3)
    assert stream == B.stream * 3


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


def test_skip_backwards_wraps_and_restart_replays():
    source = PlaylistSource([("A", A), ("B", B)], loops=1)
    source.skip(-1)
    assert source.take(len(B.stream)) == B.stream
    source.restart()
    assert source.take(len(B.stream)) == B.stream
