"""KBD, a Bluetooth keyboard's service, with no console: requests in,
replies out, and the test as the keyboard."""

import nesp_proto as p
import pytest

KBD = p.NESP_SVC_KBD
KEYS_MAX = p.NESP_KBD_KEYS_MAX


@pytest.fixture
def kbd(stick):
    assert stick.hello(services=[KBD]).ok
    return stick


def state(stick):
    """The state, how many a scan found, and the name of the one paired."""
    reply = stick.ask(KBD, p.NESP_KBD_STATE)
    assert reply.ok
    data = reply.payload
    assert len(data) == 3 + data[2]
    return data[0], data[1], data[3:]


def keys(stick, seq=None):
    reply = stick.ask(KBD, p.NESP_KBD_KEYS, seq=seq)
    assert reply.ok
    assert len(reply.payload) == 1 + reply.payload[0]
    return reply.payload[1:]


def test_bluetooth_is_on_while_a_rom_asks_for_the_keyboard(stick):
    assert not stick.kbd_on
    assert stick.ask(KBD, p.NESP_KBD_STATE).status == p.NESP_ST_INACTIVE
    assert stick.hello(services=[KBD]).ok
    assert stick.kbd_on and stick.kbd_enables == 1
    # A hello that keeps it starts it afresh, as it does every service: the
    # firmware is what makes nothing of an off and an on together.
    assert stick.hello(services=[p.NESP_SVC_NET, KBD]).ok
    assert stick.kbd_on and (stick.kbd_enables, stick.kbd_disables) == (2, 1)
    assert stick.hello(services=[p.NESP_SVC_NET]).ok
    assert not stick.kbd_on and stick.kbd_disables == 2


def test_the_state_says_how_the_keyboard_stands_and_which_it_is(kbd):
    assert state(kbd) == (p.NESP_KEYBOARD_UNPAIRED, 0, b"")
    kbd.kbd_paired(b"MX KEYS S")
    kbd.kbd_state = p.NESP_KEYBOARD_WAITING
    assert state(kbd) == (p.NESP_KEYBOARD_WAITING, 0, b"MX KEYS S")
    kbd.kbd_state = p.NESP_KEYBOARD_CONNECTED
    assert state(kbd) == (p.NESP_KEYBOARD_CONNECTED, 0, b"MX KEYS S")


def test_what_is_typed_comes_in_order_and_once(kbd):
    assert keys(kbd) == b""
    kbd.kbd_type(b"Hi" + bytes((p.NESP_KEY_BACKSPACE, p.NESP_KEY_ENTER)))
    assert keys(kbd) == b"Hi\x08\x0a"
    assert keys(kbd) == b"" and kbd.kbd_unread == 0


def test_more_than_a_reply_holds_comes_in_the_next(kbd):
    typed = bytes(range(0x20, 0x20 + KEYS_MAX + 5))
    kbd.kbd_type(typed)
    assert keys(kbd) == typed[:KEYS_MAX]
    assert keys(kbd) == typed[KEYS_MAX:]


def test_keys_asked_for_again_are_the_same_keys_and_none_is_lost(kbd):
    kbd.kbd_type(b"abc")
    assert keys(kbd, seq=7) == b"abc"
    kbd.kbd_type(b"d")
    assert keys(kbd, seq=7) == b"abc"           # its reply was lost: the same again
    assert keys(kbd, seq=8) == b"d"


def test_what_was_typed_before_a_rom_asked_is_dropped(stick):
    stick.kbd_type(b"stale")
    assert stick.hello(services=[KBD]).ok
    assert keys(stick) == b""


def test_a_scan_finds_keyboards_strongest_first(kbd):
    assert kbd.ask(KBD, p.NESP_KBD_SCAN).ok
    assert kbd.ask(KBD, p.NESP_KBD_SCAN).ok and kbd.kbd_scans == 1     # already at it
    assert state(kbd)[:2] == (p.NESP_KEYBOARD_SCANNING, 0)
    assert kbd.ask(KBD, p.NESP_KBD_FOUND, b"\x00").status == p.NESP_ST_NOT_FOUND
    kbd.kbd_found([(b"MX KEYS S", -66), (b"K380", -80)])
    kbd.kbd_state = p.NESP_KEYBOARD_SCANNED
    assert state(kbd)[:2] == (p.NESP_KEYBOARD_SCANNED, 2)
    assert kbd.ask(KBD, p.NESP_KBD_FOUND, b"\x00").payload == b"\x00" + bytes((256 - 66, 9)) \
        + b"MX KEYS S"
    assert kbd.ask(KBD, p.NESP_KBD_FOUND, b"\x01").payload == b"\x01" + bytes((256 - 80, 4)) \
        + b"K380"
    assert kbd.ask(KBD, p.NESP_KBD_FOUND, b"\x02").status == p.NESP_ST_NOT_FOUND
    assert kbd.ask(KBD, p.NESP_KBD_FOUND).status == p.NESP_ST_BAD_ARG


def test_one_that_was_found_is_paired_and_the_old_one_forgotten(kbd):
    kbd.kbd_paired(b"OLD ONE")
    assert kbd.ask(KBD, p.NESP_KBD_PAIR, b"\x00").status == p.NESP_ST_FAILED  # no scan yet
    assert kbd.ask(KBD, p.NESP_KBD_SCAN).ok
    kbd.kbd_found([(b"MX KEYS S", -66), (b"K380", -80)])
    kbd.kbd_state = p.NESP_KEYBOARD_SCANNED
    assert kbd.ask(KBD, p.NESP_KBD_PAIR, b"\x05").status == p.NESP_ST_FAILED
    assert kbd.ask(KBD, p.NESP_KBD_PAIR).status == p.NESP_ST_BAD_ARG
    assert kbd.ask(KBD, p.NESP_KBD_PAIR, b"\x01").ok
    assert (kbd.kbd_pairs, kbd.kbd_pair_index) == (1, 1)
    assert state(kbd)[0] == p.NESP_KEYBOARD_PAIRING
    assert kbd.ask(KBD, p.NESP_KBD_SCAN).status == p.NESP_ST_BUSY       # not while pairing
    kbd.kbd_paired(b"K380")
    kbd.kbd_state = p.NESP_KEYBOARD_CONNECTED
    assert state(kbd) == (p.NESP_KEYBOARD_CONNECTED, 0, b"K380")


def test_the_keyboard_paired_is_forgotten(kbd):
    kbd.kbd_paired(b"MX KEYS S")
    kbd.kbd_state = p.NESP_KEYBOARD_CONNECTED
    assert kbd.ask(KBD, p.NESP_KBD_FORGET).ok
    assert kbd.kbd_forgets == 1
    assert state(kbd) == (p.NESP_KEYBOARD_UNPAIRED, 0, b"")


def test_a_board_with_no_bluetooth_says_so(stick):
    stick.kbd_absent()
    assert stick.hello(services=[KBD]).ok       # the service is there; the keyboard is not
    assert not stick.kbd_on
    assert state(stick) == (p.NESP_KEYBOARD_NONE, 0, b"")
    assert keys(stick) == b""
    for op in (p.NESP_KBD_SCAN, p.NESP_KBD_FORGET):
        assert stick.ask(KBD, op).status == p.NESP_ST_FAILED
    assert stick.ask(KBD, p.NESP_KBD_PAIR, b"\x00").status == p.NESP_ST_FAILED
    assert stick.ask(KBD, p.NESP_KBD_FOUND, b"\x00").status == p.NESP_ST_NOT_FOUND
    assert stick.hello(services=[]).ok


def test_a_name_is_cut_to_the_reply_a_rom_takes(stick):
    assert stick.hello(services=[KBD], reply_max=p.NESP_REPLY_MIN).ok
    name = b"A KEYBOARD WITH A LONG NAME"[:p.NESP_KBD_NAME_MAX]
    stick.kbd_paired(name)
    reply = stick.ask(KBD, p.NESP_KBD_STATE)
    assert len(reply.payload) == p.NESP_REPLY_MIN
    assert reply.payload[3:] == name[:p.NESP_REPLY_MIN - 3]
    stick.kbd_type(b"x" * KEYS_MAX)
    reply = stick.ask(KBD, p.NESP_KBD_KEYS)
    assert reply.payload[0] == min(KEYS_MAX, p.NESP_REPLY_MIN - 1)
    assert len(reply.payload) == 1 + reply.payload[0]
