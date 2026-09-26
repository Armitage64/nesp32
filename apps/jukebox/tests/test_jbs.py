import random

import pytest

import apu_model
import jbs
from apu_model import ApuState


def writes_only(frame):
    return [item for item in frame if not isinstance(item, jbs.Control)]


def assert_stream_matches(frames, encoded, loop_frame=None):
    """The decoded stream has the same effect as the original writes, frame by
    frame, including a second pass through the loop."""
    decoded, tail = jbs.decode(encoded.data)
    assert tail == []
    assert len(decoded) == len(frames)
    assert decoded[0][:1] == [jbs.Control(jbs.CTRL_INIT)]
    reference, console = ApuState(), ApuState()
    for index, (want, got) in enumerate(zip(frames, decoded)):
        assert console.run(writes_only(got)) == reference.run(want), index
        assert console.snapshot() == reference.snapshot(), index
    if loop_frame is None:
        return
    again, _ = jbs.decode(encoded.data, encoded.loop_offset)
    assert len(again) == len(frames) - loop_frame
    for index, (want, got) in enumerate(zip(frames[loop_frame:], again), loop_frame):
        assert all(not isinstance(item, jbs.Control) for item in got)
        assert console.run(got) == reference.run(want), index
        assert console.snapshot() == reference.snapshot(), index


def test_record_layout_matches_the_specification():
    record = jbs.encode_record([(0x15, 0x0F), (0x00, 0xBF), (0x03, 0x08), (0x0B, 0x10), (0x17, 0x40)])
    #   header: status g5, pulse1 g0, triangle g2, frame counter g6
    assert record == bytes([
        0x80 | 0x20 | 0x01 | 0x04 | 0x40,
        0x0F,                   # $4015, no submask
        0b1001, 0xBF, 0x08,     # pulse1: $4000 and $4003
        0b100, 0x10,            # triangle: $400B is its third register
        0x40,                   # $4017, no submask
    ])


def test_record_rejects_unordered_or_repeated_writes():
    with pytest.raises(ValueError):
        jbs.encode_record([(0x03, 0x08), (0x00, 0x30)])
    with pytest.raises(ValueError):
        jbs.encode_record([(0x00, 0x30), (0x00, 0x31)])
    with pytest.raises(ValueError):
        jbs.encode_record([])


def test_long_silences_split_into_127_frame_waits():
    frames = [[(0x00, 0x30)]] + [[] for _ in range(300)]
    encoded = jbs.encode(frames)
    assert encoded.data == bytes([0x80, 0x01, 0x81, 0b0001, 0x30, 127, 127, 46])
    assert_stream_matches(frames, encoded)


def test_a_frame_merges_to_the_last_value_and_drops_known_values():
    frames = [
        [(0x00, 0x30), (0x02, 0x10)],
        [(0x00, 0x31), (0x00, 0x30), (0x02, 0x20)],
    ]
    encoded = jbs.encode(frames)
    decoded, _ = jbs.decode(encoded.data)
    assert writes_only(decoded[1]) == [(0x02, 0x20)]
    assert_stream_matches(frames, encoded)


def test_repeated_length_loads_are_kept():
    frames = [[(0x03, 0x08)], [(0x03, 0x08)], [(0x17, 0x40)], [(0x17, 0x40)]]
    decoded, _ = jbs.decode(jbs.encode(frames).data)
    assert [writes_only(frame) for frame in decoded] == frames


def test_order_sensitive_frames_become_chained_records():
    # Load the length, then enable: the load is ignored. Sorting $4015
    # first would make it take effect, so the encoder must keep the order.
    frames = [[(0x15, 0x00)], [(0x03, 0x08), (0x15, 0x01)]]
    encoded = jbs.encode(frames)
    assert jbs.OP_CHAIN in encoded.data[2:]
    decoded, _ = jbs.decode(encoded.data)
    assert writes_only(decoded[1]) == [(0x03, 0x08), (0x15, 0x01)]
    assert_stream_matches(frames, encoded)


def test_loop_offset_lands_on_the_loop_frame_and_forgets_known_values():
    frames = [[(0x00, 0x30)], [], [], [(0x00, 0x30), (0x02, 0x55)], [(0x02, 0x66)], []]
    encoded = jbs.encode(frames, loop_frame=2)
    assert_stream_matches(frames, encoded, loop_frame=2)
    again, _ = jbs.decode(encoded.data, encoded.loop_offset)
    # $4000 is written again after the loop even though the console held it
    # on the first pass, because a repeat pass arrives from the end.
    assert again[1] == [(0x00, 0x30), (0x02, 0x55)]


def test_loop_at_frame_zero_skips_the_init_control():
    frames = [[(0x00, 0x30)], [(0x00, 0x31)]]
    encoded = jbs.encode(frames, loop_frame=0)
    assert encoded.loop_offset == 2
    assert_stream_matches(frames, encoded, loop_frame=0)


@pytest.mark.parametrize("seed", range(200))
def test_random_streams_round_trip(seed):
    rng = random.Random(seed)
    registers = sorted(apu_model.STREAMED_REGISTERS)
    values = (0x00, 0x08, 0x30, 0x80, 0x8F)
    frames = []
    for _ in range(120):
        if rng.random() < 0.3:
            frames.append([])
            continue
        frame = []
        for _ in range(rng.randint(1, 7)):
            register = rng.choice(registers)
            value = rng.randint(0, 15) if register == 0x15 else rng.choice(values)
            frame.append((register, value))
        frames.append(frame)
    loop_frame = rng.choice([None, 0, rng.randrange(len(frames))])
    assert_stream_matches(frames, jbs.encode(frames, loop_frame), loop_frame)


@pytest.mark.parametrize(
    "data, message",
    [
        (bytes([0x81]), "truncated"),
        (bytes([0x81, 0x00, 0x30]), "submask"),
        (bytes([0x81, 0x10, 0x30]), "submask"),
        (bytes([0x80, 0x07]), "control code"),
        (bytes([0x00, 0x05]), "expected a write record"),
    ],
)
def test_malformed_streams_are_rejected(data, message):
    with pytest.raises(jbs.StreamError, match=message):
        jbs.decode(data)


def test_end_control_after_the_last_frame_is_returned_as_tail():
    frames, tail = jbs.decode(bytes([0x81, 0b0001, 0x30, 0x80, 0x00]))
    assert frames == [[(0x00, 0x30)]]
    assert tail == [jbs.Control(jbs.CTRL_END)]


def test_file_container_round_trips():
    original = jbs.JbsFile(
        stream=bytes([0x80, 0x01, 0x81, 0b0001, 0x30, 0x05]),
        total_frames=6,
        loop_frame=1,
        loop_offset=5,
        pal_source=True,
        title="Café Theme",
    )
    loaded = jbs.JbsFile.from_bytes(original.to_bytes())
    assert loaded.title == "Caf? Theme"
    loaded.title = original.title
    assert loaded == original


def test_file_without_loop_round_trips():
    original = jbs.JbsFile(stream=b"\x80\x01\x05", total_frames=5)
    assert jbs.JbsFile.from_bytes(original.to_bytes()) == original


def test_bad_files_are_rejected():
    with pytest.raises(jbs.StreamError):
        jbs.JbsFile.from_bytes(b"JBS")
    data = jbs.JbsFile(stream=b"\x80\x01\x05", total_frames=5).to_bytes()
    with pytest.raises(jbs.StreamError):
        jbs.JbsFile.from_bytes(b"XXXX" + data[4:])
    with pytest.raises(jbs.StreamError):
        jbs.JbsFile.from_bytes(data[:-1])
