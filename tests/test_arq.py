"""The stream over datagrams that carries PEER's connection (arq.c), with
the test as the network: it loses packets, brings them twice and brings
them the wrong way round, and every byte still arrives once, in order."""

import random

import nesp
from nesp import ARQ_ANSWER, ARQ_BYE, ARQ_CALL, ARQ_DATA, Arq

MS = 1000


def network(one, other, sent, seconds=2.0, delay=lambda: 5 * MS, lose=0.0, twice=0.0,
            seed=1, each=16667):
    """Each end writes one byte every `each` microseconds for a while, as a
    game does, and sends a datagram whenever one is due. Returns what each
    end read."""
    rng = random.Random(seed)
    ends = (one, other)
    flying = []                 # (when it lands, which end it lands at, the datagram)
    read = [bytearray(), bytearray()]
    written = [0, 0]
    for now in range(0, int(seconds * 1e6) + 400 * MS, 500):
        for side, end in enumerate(ends):
            if now < seconds * 1e6 and now % each < 500 and written[side] < len(sent[side]):
                written[side] += end.write(sent[side][written[side]:written[side] + 1])
            if end.due(now):
                packet = end.packet(now)
                for _ in range(2 if rng.random() < twice else 1):
                    if rng.random() >= lose:
                        flying.append((now + delay(), 1 - side, packet))
        landed = [item for item in flying if item[0] <= now]
        flying = [item for item in flying if item[0] > now]
        for _, side, packet in landed:
            assert ends[side].take(now, packet) == ARQ_DATA
            read[side] += ends[side].read()
    return bytes(read[0]), bytes(read[1])


def stream(seed, count=120):
    rng = random.Random(seed)
    return bytes(rng.randrange(256) for _ in range(count))


def test_bytes_cross_both_ways():
    sent = (stream(1), stream(2))
    assert network(Arq(), Arq(), sent) == (sent[1], sent[0])


def test_a_quarter_of_the_packets_lost_and_nothing_is():
    sent = (stream(3), stream(4))
    one, other = Arq(), Arq()
    assert network(one, other, sent, lose=0.25) == (sent[1], sent[0])
    assert one.unsaid == 0 and other.unsaid == 0


def test_packets_twice_and_out_of_order():
    rng = random.Random(9)
    sent = (stream(5), stream(6))
    got = network(Arq(), Arq(), sent, twice=0.3, lose=0.1,
                  delay=lambda: rng.choice((2, 5, 9, 30, 70)) * MS)
    assert got == (sent[1], sent[0])


def test_a_lost_packet_holds_nothing_up():
    """The byte a lost datagram carried comes with the next one, a few
    milliseconds later: not after a wait to send the first again."""
    one, other = Arq(), Arq()
    one.write(b"\x11")
    one.packet(0)                               # lost
    assert not one.due(1 * MS)
    one.write(b"\x22")
    assert one.due(1 * MS)                      # a new byte goes at once
    assert other.take(6 * MS, one.packet(1 * MS)) == ARQ_DATA
    assert other.read() == b"\x11\x22"


def test_with_nothing_new_a_packet_goes_again_soon_and_then_now_and_again():
    one, other = Arq(), Arq()
    one.write(b"\x01")
    packet = one.packet(0)
    assert not one.due(7 * MS) and one.due(8 * MS)      # not said to have come
    other.take(1 * MS, packet)
    one.take(2 * MS, other.packet(1 * MS))
    assert one.unsaid == 0
    one.packet(8 * MS)
    assert not one.due(50 * MS) and one.due(58 * MS)    # only to say it is there


def test_how_long_the_network_takes():
    """Each datagram gives back the other's clock with the time it was
    held, so the wait before an answer is not counted. The two clocks need
    not agree."""
    one, other = Arq(), Arq()
    skew = 123456789
    other.take(skew + 20 * MS, one.packet(0))                   # 20 ms to cross
    packet = other.packet(skew + 35 * MS)                       # held 15 ms
    assert one.take(47 * MS, packet) == ARQ_DATA                # 12 ms back
    assert one.rtt_last == 32 * MS and one.rtt == 32 * MS
    assert other.rtt == 0                                       # nothing has come back to it yet
    other.take(skew + 60 * MS, one.packet(50 * MS))
    assert other.rtt_last == (12 + 10) * MS


def test_one_slow_packet_does_not_set_the_quickest_time():
    """A session's first delay is taken from the quickest the network has
    been, a few packets into a connection. The first of them is the call's
    answer, and slow as a rule: it is most of the smoothed time for a
    while, and none of the quickest once another has come."""
    one, other = Arq(), Arq()
    other.take(40 * MS, one.packet(0))
    one.take(83 * MS, other.packet(40 * MS))                    # 83 ms there and back
    assert one.rtt_least == one.rtt == 83 * MS
    now = 100 * MS
    for _ in range(3):
        other.take(now + 2 * MS, one.packet(now))
        one.take(now + 4 * MS, other.packet(now + 2 * MS))      # and then 4
        now += 50 * MS
    assert one.rtt_last == 4 * MS
    assert one.rtt_least == 4 * MS
    assert one.rtt > 50 * MS                                    # the smoothed is still the first's


def test_a_note_rides_with_every_packet_and_the_latest_is_kept():
    one, other = Arq(), Arq()
    assert other.noted == bytes(4)
    one.note(b"\x01\x02\x03\x04")
    first = one.packet(0)
    one.note(b"\x05\x06\x07\x08")
    second = one.packet(10 * MS)
    other.take(12 * MS, second)
    other.take(13 * MS, first)                  # late: it does not put the old note back
    assert other.noted == b"\x05\x06\x07\x08"


def test_another_connections_packets_are_not_taken():
    one, stranger = Arq(session=1), Arq(session=2)
    stranger.write(b"\x77")
    assert one.take(0, stranger.packet(0)) == -1
    assert one.take(0, b"hello") == -1
    assert one.read() == b""


def test_the_kinds_are_passed_on():
    one, other = Arq(session=7), Arq(session=7)
    assert other.take(0, one.packet(0, ARQ_CALL)) == ARQ_CALL
    assert one.take(1, other.packet(1, ARQ_ANSWER)) == ARQ_ANSWER
    assert other.take(2, one.packet(2, ARQ_BYE)) == ARQ_BYE


def test_more_than_a_packet_carries_still_arrives():
    """A long silence from the other end: what was written meanwhile is
    kept, and crosses a packetful at a time once it is heard again."""
    one, other = Arq(), Arq()
    sent = stream(8, 90)
    assert one.write(sent) == 90
    assert one.write(bytes(20)) == 6            # and no more than it can keep
    got = bytearray()
    for now in range(0, 400 * MS, MS):
        if one.due(now):
            other.take(now, one.packet(now))
            got += other.read()
        if other.due(now):
            one.take(now, other.packet(now))
    assert bytes(got[:90]) == sent


def test_the_python_and_the_c_agree_on_sizes():
    assert len(Arq().packet(0)) == 24
    one = Arq()
    one.write(bytes(96))
    assert len(one.packet(0)) == nesp.ARQ_PACKET
