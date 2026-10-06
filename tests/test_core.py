"""The firmware's link and services with no console: bytes in, bytes out."""

import random

import nesp
import nesp_proto as p
import pytest
from nesp import frame, parse

SYS, NET, DIAG = p.NESP_SVC_SYS, p.NESP_SVC_NET, p.NESP_SVC_DIAG
CONTROLLER_READ = b"\xfe"       # what the console's controller read looks like


def test_the_rate_is_the_one_the_other_projects_ran_at():
    assert (p.NESP_PERIOD, p.NESP_BAUD) == (21, 85227)
    assert p.NESP_OVERHEAD == p.NESP_HEADER + 2


# --- frames ----------------------------------------------------------------------

def test_the_firmware_and_the_tests_agree_on_the_crc():
    generator = random.Random(1)
    for length in (0, 1, 2, 17, 131):
        data = bytes(generator.randrange(256) for _ in range(length))
        assert nesp.c_checks(data) == nesp.checks(data)
    # CRC-16/CCITT-FALSE's check value.
    assert nesp.c_checks(b"123456789") == nesp.checks(b"123456789") == b"\x29\xb1"
    assert nesp.checks(b"") == b"\xff\xff"


def test_no_two_wrong_bits_get_a_request_past_the_crc(stick):
    # Every pair of bits of a short request, which is what the running sums
    # this link first had let through one time in 150.
    request = frame(SYS, p.NESP_SYS_ECHO, 5, b"ab")
    bits = 8 * len(request)
    for first in range(bits):
        for second in range(first + 1, bits):
            damaged = bytearray(request)
            damaged[first // 8] ^= 1 << (first % 8)
            damaged[second // 8] ^= 1 << (second % 8)
            assert stick.feed(bytes(damaged)) == b"", (first, second)


def test_a_request_gets_one_reply_that_echoes_its_service_and_sequence(stick):
    reply = stick.ask(SYS, p.NESP_SYS_ECHO, b"hello", seq=0x42)
    assert (reply.svc, reply.seq, reply.status, reply.payload) == (SYS, 0x42, 0, b"hello")


def test_a_request_may_arrive_a_byte_at_a_time(stick):
    request = frame(SYS, p.NESP_SYS_ECHO, 7, b"piecemeal")
    for byte in request[:-1]:
        assert stick.feed(bytes((byte,))) == b""
    assert parse(stick.feed(request[-1:])).payload == b"piecemeal"
    assert stick.noise == 0


def test_noise_round_a_request_is_passed_over(stick):
    request = frame(SYS, p.NESP_SYS_ECHO, 1, b"x")
    reply = stick.feed(CONTROLLER_READ + b"\x00\x00" + request + CONTROLLER_READ)
    assert parse(reply).payload == b"x"
    assert stick.noise == 4


def test_a_marker_in_the_noise_does_not_hide_the_request_behind_it(stick):
    # 'N' and a plausible length: the decoder must not sit waiting for the
    # rest of a frame that is not one.
    junk = bytes((p.NESP_REQUEST_MARKER, 0, 0, 0, 100))
    assert stick.feed(junk) == b""
    reply = stick.feed(frame(SYS, p.NESP_SYS_ECHO, 2, b"real"))
    assert parse(reply).payload == b"real"
    # And nothing of the junk is left to trip the next one.
    assert parse(stick.feed(frame(SYS, p.NESP_SYS_ECHO, 3, b"next"))).payload == b"next"


@pytest.mark.parametrize("flip", range(8 * 12))
def test_a_request_with_any_one_bit_wrong_is_not_answered(stick, flip):
    request = bytearray(frame(SYS, p.NESP_SYS_ECHO, 5, b"abcde"))
    request[flip // 8] ^= 1 << (flip % 8)
    assert stick.feed(bytes(request)) == b""


def test_a_length_with_bit_7_set_is_never_a_frame(stick):
    body = bytes((SYS, p.NESP_SYS_ECHO, 1, 0x80)) + bytes(0x80)
    assert stick.feed(bytes((p.NESP_REQUEST_MARKER,)) + body + nesp.checks(body)) == b""


def test_of_several_requests_only_the_last_is_answered(stick):
    data = b"".join(frame(SYS, p.NESP_SYS_ECHO, seq, bytes((seq,))) for seq in (1, 2, 3))
    reply = parse(stick.feed(data))
    assert (reply.seq, reply.payload) == (3, b"\x03")
    assert (stick.requests, stick.dropped, stick.noise) == (3, 2, 0)


def test_a_flood_of_noise_does_not_stop_the_link(stick):
    generator = random.Random(4)
    for _ in range(50):
        stick.feed(bytes(generator.randrange(256) for _ in range(generator.randrange(1, 600))))
    # One request may be lost to a marker left at the end of the noise.
    stick.feed(frame(SYS, p.NESP_SYS_ECHO, 8, b"flush"))
    assert parse(stick.feed(frame(SYS, p.NESP_SYS_ECHO, 9, b"after"))).payload == b"after"


# --- repeats ---------------------------------------------------------------------

def test_the_same_request_again_gets_the_same_bytes_again(stick):
    stick.hello(services=[DIAG])
    request = frame(DIAG, p.NESP_DIAG_STATS, 9)
    first = stick.feed(request)
    stick.feed(frame(SYS, p.NESP_SYS_ECHO, 1, b"other service"))
    assert stick.feed(request) == first     # though the counters have moved on
    assert stick.repeats == 1
    assert stick.feed(frame(DIAG, p.NESP_DIAG_STATS, 10)) != first


def test_a_new_request_under_an_old_sequence_number_is_not_taken_for_a_repeat(stick):
    assert stick.ask(SYS, p.NESP_SYS_ECHO, b"one", seq=1).payload == b"one"
    assert stick.ask(SYS, p.NESP_SYS_ECHO, b"two", seq=1).payload == b"two"
    assert stick.repeats == 0


def test_busy_is_never_repeated(stick):
    # Nothing here answers busy yet, so this holds the rule in the core by
    # way of a service that is not there: its reply is not held either.
    request = frame(0x7F, 0, 1)
    assert parse(stick.feed(request)).status == p.NESP_ST_NO_SERVICE
    stick.feed(request)
    assert stick.repeats == 0


# --- hello -----------------------------------------------------------------------

def test_hello_says_what_the_stick_is(stick):
    reply = stick.hello(app=b"SETP", version=3, services=[NET, DIAG])
    assert reply.ok
    assert reply.payload == bytes((p.NESP_PROTOCOL, 0, 1, 0, p.NESP_BOARD_HOST,
                                   p.NESP_PAYLOAD_MAX, 0))
    assert stick.app == (b"SETP", 3)


def test_a_service_answers_only_after_a_hello_asks_for_it(stick):
    assert stick.ask(NET, p.NESP_NET_WIFI_STATUS).status == p.NESP_ST_INACTIVE
    assert stick.ask(SYS, p.NESP_SYS_STATUS).ok          # SYS always does
    stick.hello(services=[NET])
    assert stick.ask(NET, p.NESP_NET_WIFI_STATUS).ok
    assert stick.ask(DIAG, p.NESP_DIAG_STATS).status == p.NESP_ST_INACTIVE
    stick.hello(services=[DIAG])                        # another ROM
    assert stick.ask(NET, p.NESP_NET_WIFI_STATUS).status == p.NESP_ST_INACTIVE
    assert stick.ask(DIAG, p.NESP_DIAG_STATS).ok


def test_hello_names_the_services_this_firmware_lacks(stick):
    reply = stick.hello(services=[NET, 0x7E, DIAG, 0x7F])
    assert reply.status == p.NESP_ST_NO_SERVICE
    assert reply.payload[6:] == bytes((2, 0x7E, 0x7F))
    assert stick.active(NET) and stick.active(DIAG)     # the rest are there


def test_a_service_not_built_yet_is_reported_missing(stick):
    assert stick.hello(services=[p.NESP_SVC_RADAR]).payload[6:] == bytes((1, p.NESP_SVC_RADAR))
    assert stick.ask(p.NESP_SVC_RADAR, 0).status == p.NESP_ST_NO_SERVICE


def test_hello_from_another_protocol_is_told_so(stick):
    payload = bytes((p.NESP_PROTOCOL + 1,)) + b"TEST" + bytes((1, 64))
    reply = stick.ask(SYS, p.NESP_SYS_HELLO, payload)
    assert reply.status == p.NESP_ST_VERSION and reply.payload[0] == p.NESP_PROTOCOL


def test_hello_forgets_the_replies_held_for_the_console_that_was_reset(stick):
    stick.hello(services=[DIAG])
    request = frame(DIAG, p.NESP_DIAG_STATS, 1)
    first = stick.feed(request)
    stick.hello(services=[DIAG])
    assert stick.feed(request) != first and stick.repeats == 0
    # Nor is a hello itself ever answered from memory.
    assert stick.hellos == 2
    hello = frame(SYS, p.NESP_SYS_HELLO, 1, bytes((p.NESP_PROTOCOL,)) + b"SAME" + bytes((1, 64)))
    stick.feed(hello)
    stick.feed(hello)
    assert stick.hellos == 4


def test_hello_sets_the_longest_reply(stick):
    long = bytes(range(100))
    assert len(stick.ask(SYS, p.NESP_SYS_ECHO, long).payload) == p.NESP_REPLY_BEFORE_HELLO
    stick.hello(reply_max=100)
    assert stick.ask(SYS, p.NESP_SYS_ECHO, long).payload == long
    stick.hello(reply_max=1)                    # less than any ROM can work with
    assert len(stick.ask(SYS, p.NESP_SYS_ECHO, long).payload) == p.NESP_REPLY_MIN
    stick.hello(reply_max=255)
    assert len(stick.ask(SYS, p.NESP_SYS_ECHO, bytes(127)).payload) == p.NESP_PAYLOAD_MAX


# --- SYS -------------------------------------------------------------------------

def test_status_and_info(stick):
    stick.set_wifi(p.NESP_WIFI_JOINED, rssi=-61, address=(192, 168, 1, 77))
    stick.set_saved(b"Home Network")
    stick.set_battery(83)
    reply = stick.ask(SYS, p.NESP_SYS_STATUS)
    assert reply.payload == bytes((p.NESP_WIFI_JOINED, 256 - 61, 192, 168, 1, 77, 83, 0))
    assert stick.ask(SYS, p.NESP_SYS_INFO, bytes((p.NESP_INFO_FIRMWARE,))).payload == b"0.1.0"
    assert stick.ask(SYS, p.NESP_SYS_INFO, bytes((p.NESP_INFO_BOARD,))).payload == b"Computer"
    assert stick.ask(SYS, p.NESP_SYS_INFO,
                     bytes((p.NESP_INFO_NETWORK,))).payload == b"Home Network"
    stick.hello(app=b"JUKE")
    assert stick.ask(SYS, p.NESP_SYS_INFO, bytes((p.NESP_INFO_APP,))).payload == b"JUKE"
    assert stick.ask(SYS, p.NESP_SYS_INFO, b"\x63").status == p.NESP_ST_NOT_FOUND
    assert stick.ask(SYS, 0x7F).status == p.NESP_ST_NO_OP


def test_time(stick):
    assert stick.ask(SYS, p.NESP_SYS_TIME).payload == bytes(5)
    stick.set_time(0x65432100)
    assert stick.ask(SYS, p.NESP_SYS_TIME).payload == bytes((1, 0x00, 0x21, 0x43, 0x65))


def test_events_raise_attention_on_every_reply_until_they_are_taken(stick):
    assert not stick.ask(SYS, p.NESP_SYS_STATUS).attention
    stick.event(p.NESP_EVENT_BUTTON_A)
    stick.event(p.NESP_EVENT_BUTTON_B, 2)
    reply = stick.ask(SYS, p.NESP_SYS_STATUS)
    assert reply.attention and reply.ok and reply.payload[7] == 2
    assert stick.ask(SYS, p.NESP_SYS_EVENT).payload == bytes((p.NESP_EVENT_BUTTON_A, 0))
    last = stick.ask(SYS, p.NESP_SYS_EVENT)
    assert last.payload == bytes((p.NESP_EVENT_BUTTON_B, 2)) and not last.attention
    assert stick.ask(SYS, p.NESP_SYS_EVENT).payload == bytes((p.NESP_EVENT_NONE, 0))


def test_more_events_than_the_queue_holds_are_dropped_not_muddled(stick):
    for arg in range(p.NESP_EVENT_QUEUE + 3):
        stick.event(p.NESP_EVENT_BUTTON_A, arg)
    taken = [stick.ask(SYS, p.NESP_SYS_EVENT).payload[1] for _ in range(p.NESP_EVENT_QUEUE)]
    assert taken == list(range(p.NESP_EVENT_QUEUE))
    assert stick.ask(SYS, p.NESP_SYS_EVENT).payload[0] == p.NESP_EVENT_NONE


# --- NET: Wi-Fi ------------------------------------------------------------------

NETWORKS = [(b"Home Network", -48, p.NESP_AUTH_PASSWORD, 6),
            (b"Cafe", -70, p.NESP_AUTH_OPEN, 11),
            (b"x" * 32, -88, p.NESP_AUTH_PASSWORD, 1)]


def pieces(stick, op, text, size):
    for offset in range(0, max(len(text), 1), size):
        reply = stick.ask(NET, op, bytes((offset,)) + text[offset:offset + size])
        assert reply.ok and reply.payload == bytes((min(offset + size, len(text)),))


def test_a_scan_is_started_asked_after_and_read(stick):
    stick.hello(services=[NET])
    assert stick.ask(NET, p.NESP_NET_SCAN_STATUS).payload == bytes((p.NESP_SCAN_IDLE, 0))
    assert stick.ask(NET, p.NESP_NET_SCAN_START).ok
    assert stick.ask(NET, p.NESP_NET_SCAN_STATUS).payload == bytes((p.NESP_SCAN_RUNNING, 0))
    assert stick.ask(NET, p.NESP_NET_SCAN_RESULT, b"\x00").status == p.NESP_ST_NOT_FOUND
    stick.scan_set(NETWORKS)
    stick.scan_finish()
    assert stick.ask(NET, p.NESP_NET_SCAN_STATUS).payload == bytes((p.NESP_SCAN_DONE, 3))
    for index, (name, rssi, auth, channel) in enumerate(NETWORKS):
        reply = stick.ask(NET, p.NESP_NET_SCAN_RESULT, bytes((index,)))
        assert reply.payload == bytes((index, rssi & 0xFF, auth, channel, len(name))) + name
    assert stick.ask(NET, p.NESP_NET_SCAN_RESULT, b"\x03").status == p.NESP_ST_NOT_FOUND
    assert stick.scans == 1


def test_a_name_too_long_for_the_reply_is_cut_not_dropped(stick):
    stick.hello(services=[NET], reply_max=p.NESP_REPLY_MIN)
    stick.scan_set(NETWORKS)
    stick.scan_finish()
    reply = stick.ask(NET, p.NESP_NET_SCAN_RESULT, b"\x02")
    assert reply.payload[4] == p.NESP_REPLY_MIN - 5 and len(reply.payload) == p.NESP_REPLY_MIN


def test_a_network_is_joined_from_pieces(stick):
    stick.hello(services=[NET])
    password = bytes(range(0x20, 0x20 + 63))        # the longest, and every kind of character
    name = b"Home Network"
    pieces(stick, p.NESP_NET_SET_NAME, name, 16)
    pieces(stick, p.NESP_NET_SET_PASSWORD, password, 16)
    assert stick.ask(NET, p.NESP_NET_JOIN, bytes((len(name), len(password)))).ok
    assert (stick.joins, stick.joined_name, stick.joined_password) == (1, name, password)
    reply = stick.ask(NET, p.NESP_NET_WIFI_STATUS)
    assert reply.payload == bytes((p.NESP_WIFI_JOINING, 0, 0, 0, 0, 0, 0, len(name))) + name
    stick.set_wifi(p.NESP_WIFI_JOINED, rssi=-50, address=(10, 0, 0, 9))
    reply = stick.ask(NET, p.NESP_NET_WIFI_STATUS)
    assert reply.payload[:7] == bytes((p.NESP_WIFI_JOINED, 0, 256 - 50, 10, 0, 0, 9))


def test_an_open_network_has_an_empty_password(stick):
    stick.hello(services=[NET])
    pieces(stick, p.NESP_NET_SET_NAME, b"Cafe", 16)
    pieces(stick, p.NESP_NET_SET_PASSWORD, b"", 16)
    assert stick.ask(NET, p.NESP_NET_JOIN, bytes((4, 0))).ok
    assert (stick.joined_name, stick.joined_password) == (b"Cafe", b"")


def test_a_piece_that_never_came_is_found_out_before_a_join(stick):
    stick.hello(services=[NET])
    pieces(stick, p.NESP_NET_SET_NAME, b"Home Network", 16)
    assert stick.ask(NET, p.NESP_NET_SET_PASSWORD, b"\x00" + b"a" * 16).ok
    # The second piece is lost; the third does not carry on from the first.
    reply = stick.ask(NET, p.NESP_NET_SET_PASSWORD, b"\x20" + b"c" * 16)
    assert reply.status == p.NESP_ST_BAD_ARG and reply.payload == b"\x10"
    # And a console that went on regardless is refused.
    assert stick.ask(NET, p.NESP_NET_JOIN, bytes((12, 48))).status == p.NESP_ST_BAD_ARG
    assert stick.joins == 0


def test_a_piece_sent_again_is_not_added_twice(stick):
    stick.hello(services=[NET])
    request = frame(NET, p.NESP_NET_SET_PASSWORD, 5, b"\x00secret")
    assert stick.feed(request) == stick.feed(request)
    again = frame(NET, p.NESP_NET_SET_PASSWORD, 6, b"\x06 more")
    assert stick.feed(again) == stick.feed(again)
    pieces(stick, p.NESP_NET_SET_NAME, b"n", 16)
    assert stick.ask(NET, p.NESP_NET_JOIN, bytes((1, 11))).ok
    assert stick.joined_password == b"secret more"


def test_text_past_its_longest_is_refused(stick):
    stick.hello(services=[NET])
    assert stick.ask(NET, p.NESP_NET_SET_NAME, b"\x00" + b"n" * 33).status == p.NESP_ST_BAD_ARG
    pieces(stick, p.NESP_NET_SET_PASSWORD, b"p" * 63, 21)
    assert stick.ask(NET, p.NESP_NET_SET_PASSWORD, b"\x3f!").status == p.NESP_ST_BAD_ARG
    assert stick.ask(NET, p.NESP_NET_JOIN, bytes((0, 63))).status == p.NESP_ST_BAD_ARG


def test_no_op_gives_the_password_back(stick):
    stick.hello(services=[NET, DIAG], reply_max=p.NESP_PAYLOAD_MAX)
    secret = b"correct horse battery staple"
    pieces(stick, p.NESP_NET_SET_NAME, b"Home Network", 16)
    pieces(stick, p.NESP_NET_SET_PASSWORD, secret, 16)
    stick.ask(NET, p.NESP_NET_JOIN, bytes((12, len(secret))))
    for svc in (SYS, NET, DIAG):
        for op in range(16):
            for payload in (b"", b"\x00", b"\x01", b"\x02", b"\x03"):
                if (svc, op) in ((SYS, p.NESP_SYS_HELLO), (NET, p.NESP_NET_SET_PASSWORD),
                                 (SYS, p.NESP_SYS_ECHO), (DIAG, p.NESP_DIAG_SINK)):
                    continue
                assert secret[:4] not in stick.ask(svc, op, payload).payload


def test_a_hello_drops_what_a_reset_console_had_typed(stick):
    stick.hello(services=[NET])
    pieces(stick, p.NESP_NET_SET_NAME, b"Home Network", 16)
    pieces(stick, p.NESP_NET_SET_PASSWORD, b"half a pass", 16)
    stick.hello(services=[NET])
    assert stick.ask(NET, p.NESP_NET_JOIN, bytes((12, 11))).status == p.NESP_ST_BAD_ARG


def test_forget(stick):
    stick.hello(services=[NET])
    stick.set_wifi(p.NESP_WIFI_JOINED)
    stick.set_saved(b"Home Network")
    assert stick.ask(NET, p.NESP_NET_FORGET).ok
    assert stick.ask(NET, p.NESP_NET_WIFI_STATUS).payload == bytes((p.NESP_WIFI_NONE,)) + bytes(7)
    assert stick.forgets == 1


# --- DIAG ------------------------------------------------------------------------

def reference_pattern(seed, count):
    """nes-jukebox's (throughput/stick/linktest/proto.py), which the console's
    6502 code was written from."""
    hi, lo = seed >> 8, seed & 0xFF
    out = bytearray(count)
    for index in range(count):
        a = (lo >> 1) | ((hi & 1) << 7)
        carry = lo & 1
        hi ^= a
        a = (hi >> 1) | (carry << 7)
        lo ^= a
        hi ^= lo
        out[index] = hi
    return bytes(out)


def test_the_pattern_is_the_throughput_tests(stick):
    assert nesp.pattern(0xACE1, 64) == reference_pattern(0xACE1, 64)
    assert len(set(nesp.pattern(1, 127))) > 64      # and is not something trivial
    stick.hello(services=[DIAG])
    reply = stick.ask(DIAG, p.NESP_DIAG_PATTERN, bytes((0xE1, 0xAC, 100)))
    assert reply.payload == reference_pattern(0xACE1, 100)
    assert stick.ask(DIAG, p.NESP_DIAG_PATTERN, bytes((0, 0, 4))).status == p.NESP_ST_BAD_ARG
    assert stick.ask(DIAG, p.NESP_DIAG_PATTERN, bytes((1, 0, 128))).status == p.NESP_ST_BAD_ARG


def test_the_sink_counts_bytes_that_differ(stick):
    stick.hello(services=[DIAG])
    data = bytearray(reference_pattern(0x1234, 60))
    assert stick.ask(DIAG, p.NESP_DIAG_SINK, b"\x34\x12" + data).payload == bytes((0, 60))
    data[3] ^= 0x10
    data[59] ^= 0x01
    assert stick.ask(DIAG, p.NESP_DIAG_SINK, b"\x34\x12" + data).payload == bytes((2, 60))


def test_stats_count_the_link(stick):
    stick.hello(services=[DIAG])
    stick.feed(CONTROLLER_READ * 5)
    stick.note_turnaround(180)
    stick.note_turnaround(90)
    payload = stick.ask(DIAG, p.NESP_DIAG_STATS).payload
    values = [payload[at] | payload[at + 1] << 8 for at in range(0, 12, 2)]
    assert values == [2, 0, 0, 5, 90, 180]
