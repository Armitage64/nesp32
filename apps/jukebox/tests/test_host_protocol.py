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


def test_host_keeps_the_counters_the_nes_reports():
    host = Host(looping_track())
    assert host.handle(Request(protocol.OP_STATS, 1, 176)) == b""
    assert host.handle(Request(protocol.OP_STATS, 3, 0)) == b""
    assert host.handle(Request(protocol.OP_STATS, 200, 9)) == b""   # no such counter
    # The NES was already running: what it counted before does not show.
    assert host.nes == {"timeouts": 0, "crc_errors": 0}
    assert host.stats["bursts"] == host.stats["resends"] == 0
    host.handle(Request(protocol.OP_STATS, 1, 250))
    host.handle(Request(protocol.OP_STATS, 1, 4))      # the low byte wrapped
    host.handle(Request(protocol.OP_STATS, 4, 3))      # request_delay is a level
    host.handle(Request(protocol.OP_STATS, 4, 0))
    assert host.nes == {"timeouts": 84, "crc_errors": 0, "request_delay": 0}


def test_counters_start_from_zero_when_the_nes_has_just_booted():
    host = Host(looping_track())
    host.handle(Request(protocol.OP_STATS, 0, 9))
    host.handle(Request(protocol.OP_HELLO, 0, 0))
    assert host.nes == {}
    host.handle(Request(protocol.OP_STATS, 0, 2))      # cut off twice since boot
    host.handle(Request(protocol.OP_STATS, 0, 5))
    assert host.nes == {"aborts": 5}


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


def test_host_sends_next_bytes_and_resends_identically_on_the_same_seq():
    host = Host(looping_track())
    assert host.handle(Request(0x48, 0, 0)) == b""
    first = host.handle(Request(0x4A, 0, 8))
    assert first == protocol.burst_bytes(0, bytes([0x80, 0x01]) + bytes(range(0x81, 0x87)))
    # Lost or late: the same seq gets the same burst, even with more credit,
    # because an earlier copy may still be the one the NES commits.
    assert host.handle(Request(0x4A, 0, 24)) == first
    nxt = host.handle(Request(0x4A, 1, 4))
    assert nxt == protocol.burst_bytes(1, bytes(range(0x87, 0x8B)))
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


def test_the_controller_read_byte_is_passed_over_without_counting_as_noise():
    # The NES's controller read puts $FE on the line once a frame, ahead of
    # the request. The same value inside a request is just data.
    decoder = RequestDecoder()
    line = (b"\xFE" + protocol.request_bytes(0x4A, 0, 24)
            + b"\xFE" + protocol.request_bytes(0x4A, 0xFE, 0xFE))
    assert decoder.feed(line) == [Request(0x4A, 0, 24), Request(0x4A, 0xFE, 0xFE)]
    assert decoder.discarded == 0
    assert decoder.feed(b"\x00\xFE" + protocol.request_bytes(0x53, 1, 2)) == [Request(0x53, 1, 2)]
    assert decoder.discarded == 1


def button(host, buttons):
    assert host.handle(Request(protocol.OP_BUTTON, 0, buttons)) == b""


def test_the_controller_changes_track_stops_and_plays():
    from playlist import PlaylistSource
    from test_playlist import A, B, titled

    source = PlaylistSource([("A", A), ("B", B)], loops=10 ** 6)
    host = Host(source, stopped=True)
    empty = protocol.burst_bytes(0, b"", flush=True)
    assert host.handle(Request(0x4A, 0, 24)) == empty

    button(host, protocol.BUTTON_PLAY)              # Start, from stopped
    assert not host.stopped
    assert host.handle(Request(0x4A, 1, 8)) == protocol.burst_bytes(1, titled("A", A)[:8], flush=True)

    button(host, protocol.BUTTON_NEXT)              # Right: the next track, at once
    assert source.index == 1
    assert host.handle(Request(0x4A, 2, 8)) == protocol.burst_bytes(2, titled("B", B)[:8], flush=True)
    button(host, protocol.BUTTON_PREVIOUS)
    assert source.index == 0

    assert host.handle(Request(0x4A, 3, 8)) == protocol.burst_bytes(3, titled("A", A)[:8], flush=True)
    button(host, protocol.BUTTON_PLAY)              # Start, while playing: pause
    assert host.paused and not host.stopped
    assert host.handle(Request(0x4A, 4, 24)) == protocol.burst_bytes(4, b"", pause=True)
    assert host.handle(Request(0x4A, 5, 0)) == protocol.burst_bytes(5, b"", pause=True)
    assert host.handle(Request(0x4A, 5, 0)) == protocol.burst_bytes(5, b"", pause=True)  # resent
    button(host, protocol.BUTTON_PLAY)              # and again: on from where it was
    assert not host.paused
    assert host.handle(Request(0x4A, 6, 4)) == protocol.burst_bytes(
        6, titled("A", A, 10 ** 6)[8:12])

    button(host, protocol.BUTTON_PLAY)
    button(host, protocol.BUTTON_NEXT)              # Right from paused plays the next
    assert not host.paused and source.index == 1
    assert host.handle(Request(0x4A, 7, 8)) == protocol.burst_bytes(7, titled("B", B)[:8], flush=True)

    host.stop()
    button(host, protocol.BUTTON_NEXT)              # and from stopped
    assert not host.stopped and source.index == 0
    assert host.stats["buttons"] == 8


def test_a_pause_burst_is_told_apart_by_its_marker_and_crc():
    burst = protocol.burst_bytes(9, b"", pause=True)
    assert burst[:3] == bytes([protocol.PAUSE_MARKER, 9, 0])
    assert burst[3:] != protocol.burst_bytes(9, b"")[3:]
    assert burst[3:] != protocol.burst_bytes(9, b"", flush=True)[3:]


def test_start_plays_again_after_the_playlist_has_ended():
    from playlist import PlaylistSource
    from test_playlist import B, titled

    source = PlaylistSource([("B", B)], loops=1)
    host = Host(source)
    seq = 0
    while host.handle(Request(0x4A, seq, 24)) != protocol.burst_bytes(seq, b""):
        seq += 1
    assert source.finished and not host.stopped
    button(host, protocol.BUTTON_PLAY)
    assert host.handle(Request(0x4A, seq + 1, 8)) == protocol.burst_bytes(
        seq + 1, titled("B", B)[:8], flush=True)


def test_a_single_track_host_takes_the_buttons_too():
    host = Host(looping_track())
    host.handle(Request(0x4A, 0, 10))
    button(host, protocol.BUTTON_NEXT)              # no other track: start it again
    assert host.handle(Request(0x4A, 1, 4)) == protocol.burst_bytes(
        1, looping_track().stream[:4], flush=True)
    button(host, protocol.BUTTON_PLAY)
    assert host.paused


# -- sound ---------------------------------------------------------------------

def sound_playlist():
    import pcm
    from playlist import PlaylistSource
    from test_playlist import B

    voice = pcm.Sound("Voices - Hello", 12, pcm.encode(range(100)))
    return PlaylistSource([("Voices - Hello", voice), ("B", B)], loops=1), voice


def drained(host, seq=0):
    """Answer data requests until the source gives nothing. Returns the
    next sequence number."""
    while host.handle(Request(protocol.OP_DATA, seq, 24))[2]:
        seq += 1
    return seq + 1


def test_a_go_burst_carries_the_rate_and_its_crc_covers_the_marker():
    burst = protocol.burst_bytes(9, bytes([3]), go=True)
    crc = protocol.crc16(bytes([0xC3, 9, 1, 3]))
    assert burst == bytes([0xC3, 9, 1, 3, crc >> 8, crc & 0xFF])
    assert protocol.OP_SOUND in protocol.OPS
    decoder = RequestDecoder()
    assert decoder.feed(protocol.request_bytes(protocol.OP_SOUND, 9, 3)) == [
        Request(protocol.OP_SOUND, 9, 3)]


def test_a_sound_request_gets_a_go_burst_and_the_sound_is_due():
    source, voice = sound_playlist()
    host = Host(source)
    seq = drained(host)
    assert source.sound is voice and not host.sound_due
    go = protocol.burst_bytes(seq, bytes([voice.rate]), go=True)
    assert host.handle(Request(protocol.OP_SOUND, seq, voice.rate)) == go
    assert host.sound_due and host.sound_begin() is voice
    # The console missed it and asks again: the same burst, still due.
    assert host.handle(Request(protocol.OP_SOUND, seq, voice.rate)) == go
    assert host.sound_due and host.stats["resends"] == 1
    host.sound_end()
    assert not host.sound_due and source.sound is None
    # The music after it starts from an emptied buffer.
    from test_playlist import B, titled
    assert host.handle(Request(protocol.OP_DATA, seq + 1, 16)) == protocol.burst_bytes(
        seq + 1, titled("B", B)[:16], flush=True)


def test_a_request_that_is_not_for_sound_calls_the_sound_off():
    for other in (Request(protocol.OP_HELLO, 0, 0), Request(protocol.OP_BUTTON, 0, 1)):
        source, voice = sound_playlist()
        host = Host(source)
        seq = drained(host)
        host.handle(Request(protocol.OP_SOUND, seq, voice.rate))
        assert host.sound_due
        host.handle(other)
        assert not host.sound_due
    # After the button the console asks once more for the sound it was
    # about to play. It gets a new answer under the old number, never the
    # go burst again: nobody would send the samples.
    answer = host.handle(Request(protocol.OP_SOUND, seq, voice.rate))
    assert answer[0] == protocol.FLUSH_MARKER and not host.sound_due
    assert source.index == 1


def test_a_console_that_cannot_play_a_sound_is_sent_past_it():
    source, voice = sound_playlist()
    host = Host(source)
    seq = drained(host)
    answer = host.handle(Request(protocol.OP_SOUND, seq, protocol.SOUND_REFUSED))
    assert answer[0] == protocol.FLUSH_MARKER and len(answer) == 24 + 5
    assert not host.sound_due and source.sound is None and source.index == 1


def test_stopped_and_paused_hosts_do_not_start_a_sound():
    source, voice = sound_playlist()
    host = Host(source)
    seq = drained(host)
    host.paused = True
    assert host.handle(Request(protocol.OP_SOUND, seq, voice.rate)) == protocol.burst_bytes(
        seq, b"", pause=True)
    assert not host.sound_due and source.sound is voice
    host.stop()
    assert host.handle(Request(protocol.OP_SOUND, seq + 1, voice.rate)) == protocol.burst_bytes(
        seq + 1, b"", flush=True)
    assert not host.sound_due
    host.play()                     # the track starts again, and will ask again
    assert source.sound is None
    assert drained(host, seq + 2) and source.sound is voice
