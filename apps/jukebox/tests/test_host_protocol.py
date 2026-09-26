import jbs
import protocol
from protocol import Host, Request, RequestDecoder, StreamSource


def looping_track():
    stream = bytes([0x80, 0x01]) + bytes(range(0x81, 0x81 + 40))
    return jbs.JbsFile(stream=stream, total_frames=40, loop_frame=1, loop_offset=2)


def test_crc_matches_the_standard_check_value():
    assert protocol.crc16(b"123456789") == 0x29B1


def test_crc_table_matches_the_bitwise_crc():
    import gen_crc_table
    for index, entry in enumerate(gen_crc_table.table()):
        # One table step from a zero low byte is the bitwise CRC of one byte.
        assert entry == protocol.crc16(bytes([index]), crc=0x0000)


def test_request_and_burst_layout():
    assert protocol.request_bytes(0x4A, 7, 24) == bytes([0x4A, 7, 24, 0xA5 ^ 0x4A ^ 7 ^ 24])
    burst = protocol.burst_bytes(3, b"\x01\x02")
    crc = protocol.crc16(bytes([3, 2, 1, 2]))
    assert burst == bytes([0xA5, 3, 2, 1, 2, crc >> 8, crc & 0xFF])


def test_decoder_resyncs_through_noise_and_split_reads():
    decoder = RequestDecoder()
    data = b"\x00\xFF" + protocol.request_bytes(0x48, 0, 0) + b"\x4A\x00" + protocol.request_bytes(0x4A, 1, 24)
    got = []
    for index in range(0, len(data), 3):
        got += decoder.feed(data[index:index + 3])
    assert got == [Request(0x48, 0, 0), Request(0x4A, 1, 24)]
    assert decoder.discarded == 4


def test_decoder_rejects_a_bad_check_and_unknown_ops():
    decoder = RequestDecoder()
    bad = bytearray(protocol.request_bytes(0x4A, 1, 24))
    bad[3] ^= 1
    assert decoder.feed(bytes(bad) + bytes([0x11, 0, 0, 0xA5 ^ 0x11])) == []


def test_source_loops_and_non_looping_tracks_end():
    source = StreamSource(looping_track())
    first = source.take(42)
    assert first[:2] == b"\x80\x01" and len(first) == 42
    assert source.take(3) == bytes([0x81, 0x82, 0x83])  # back at the loop point
    track = jbs.JbsFile(stream=b"\x80\x01\x05", total_frames=5)
    source = StreamSource(track)
    assert source.take(10) == b"\x80\x01\x05\x80\x00"
    assert source.take(10) == b""


def test_host_sends_next_bytes_and_resends_on_the_same_seq():
    host = Host(looping_track())
    assert host.handle(Request(0x48, 0, 0)) == b""
    first = host.handle(Request(0x4A, 0, 8))
    assert first == protocol.burst_bytes(0, bytes([0x80, 0x01]) + bytes(range(0x81, 0x87)))
    again = host.handle(Request(0x4A, 0, 4))           # lost: same seq, less credit
    assert again == protocol.burst_bytes(0, bytes([0x80, 0x01, 0x81, 0x82]))
    nxt = host.handle(Request(0x4A, 1, 4))
    assert nxt == protocol.burst_bytes(1, bytes(range(0x83, 0x87)))
    assert host.stats["resends"] == 1


def test_hello_restarts_the_track():
    host = Host(looping_track())
    host.handle(Request(0x4A, 0, 10))
    host.handle(Request(0x48, 0, 0))
    assert host.handle(Request(0x4A, 0, 2)) == protocol.burst_bytes(0, b"\x80\x01")


def test_an_ended_track_answers_with_empty_bursts():
    host = Host(jbs.JbsFile(stream=b"\x80\x01\x05", total_frames=5))
    assert host.handle(Request(0x4A, 0, 24)) == protocol.burst_bytes(0, b"\x80\x01\x05\x80\x00")
    assert host.handle(Request(0x4A, 1, 24)) == protocol.burst_bytes(1, b"")
