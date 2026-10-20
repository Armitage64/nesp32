"""STUN (stun.c): the Binding Request a nesp32 sends from PEER's socket,
and the address and port read from the answer."""

import struct

from nesp import Arq, stun_mapped, stun_request

COOKIE = bytes.fromhex("2112a442")
# RFC 5769, 2.2: a Binding answer whose XOR-MAPPED-ADDRESS is 192.0.2.1,
# port 32853, among a SOFTWARE attribute, MESSAGE-INTEGRITY and FINGERPRINT.
IDENT = bytes.fromhex("b7e7a701bc34d686fa87dfae")
VECTOR = bytes.fromhex(
    "0101003c" "2112a442" "b7e7a701bc34d686fa87dfae"
    "8022000b" "74657374" "20766563" "746f7220"
    "00200008" "0001a147" "e112a643"
    "00080014" "2b91f599" "fd9e90c3" "8c7489f9" "2af9ba53" "f06be7d7"
    "80280004" "c07d4c96")


def answer(*attributes, ident=IDENT, kind=0x0101):
    body = b"".join(attributes)
    return struct.pack(">HH", kind, len(body)) + COOKIE + ident + body


def attribute(kind, value):
    padding = b"\0" * (-len(value) % 4)
    return struct.pack(">HH", kind, len(value)) + value + padding


def xor_mapped(address, port):
    mixed = bytes(a ^ c for a, c in zip(address, COOKIE))
    return attribute(0x0020, struct.pack(">BBH", 0, 1, port ^ 0x2112) + mixed)


def mapped(address, port):
    return attribute(0x0001, struct.pack(">BBH", 0, 1, port) + bytes(address))


def test_the_request_is_a_bare_binding_request():
    assert stun_request(IDENT) == bytes.fromhex("00010000") + COOKIE + IDENT


def test_the_rfc_5769_answer():
    assert stun_mapped(VECTOR, IDENT) == (bytes([192, 0, 2, 1]), 32853)


def test_another_requests_answer_is_not_this_ones():
    assert stun_mapped(VECTOR, bytes(12)) is None


def test_only_an_answer_is_taken():
    assert stun_mapped(stun_request(IDENT), IDENT) is None
    assert stun_mapped(answer(xor_mapped(b"\x01\x02\x03\x04", 1), kind=0x0111), IDENT) is None


def test_an_ipv6_address_is_not_one():
    value = struct.pack(">BBH", 0, 2, 0xA147) + bytes(16)
    assert stun_mapped(answer(attribute(0x0020, value)), IDENT) is None


def test_an_older_servers_mapped_address():
    assert stun_mapped(answer(mapped(b"\x0a\x00\x00\x01", 6502)), IDENT) == (b"\x0a\x00\x00\x01",
                                                                             6502)


def test_the_mixed_address_is_believed_over_the_plain_one():
    got = stun_mapped(answer(mapped(b"\x0a\x00\x00\x01", 1), xor_mapped(b"\xcb\x00\x71\x05", 6502)),
                      IDENT)
    assert got == (b"\xcb\x00\x71\x05", 6502)


def test_an_answer_cut_short_after_the_address_still_gives_it():
    whole = answer(xor_mapped(b"\xc6\x33\x64\x09", 40000), attribute(0x8022, b"x" * 200))
    assert stun_mapped(whole[:60], IDENT) == (b"\xc6\x33\x64\x09", 40000)


def test_an_answer_cut_short_inside_the_address_gives_nothing():
    whole = answer(xor_mapped(b"\xc6\x33\x64\x09", 40000))
    assert stun_mapped(whole[:-2], IDENT) is None
    assert stun_mapped(whole[:10], IDENT) is None


def test_a_peer_datagram_is_not_one():
    assert stun_mapped(Arq().packet(0), IDENT) is None
