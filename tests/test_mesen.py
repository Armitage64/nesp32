"""host/mesen/nesp32_bridge.py, the NESP32 for Mesen's Lua script, with no
Mesen: the computer's keyboard as the nesp32's Bluetooth keyboard, a
ROM's files kept, and fetches as the firmware makes them."""

import http.server
import os
import socket
import sys
import threading
import time

import nesp_proto as p
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "host", "mesen"))

import nesp32_bridge as bridge  # noqa: E402

bridge.load_nesp32()

KBD = p.NESP_SVC_KBD
SHIFT, CTRL, ALT, GUI = 0x02, 0x01, 0x04, 0x08
A, ENTER, ESCAPE, BACKSPACE = 0x04, 0x28, 0x29, 0x2A
ONE, SLASH, CAPS, F1, F12, HOME, DELETE, RIGHT, UP = (0x1E, 0x38, 0x39, 0x3A, 0x45, 0x4A,
                                                    0x4C, 0x4F, 0x52)
KEYPAD_1 = 0x59


def letter(c):
    return A + ord(c) - ord("a")


class Typist:
    """A Keyboard, and what it has typed."""

    def __init__(self):
        self.typed = bytearray()
        self.keyboard = bridge.Keyboard(self.typed.append)
        self.now = 0

    def tap(self, usage, modifiers=0):
        self.keyboard.report(modifiers, [usage], self.now)
        self.keyboard.report(modifiers, [], self.now)


# --- the keyboard ---------------------------------------------------------------

def test_letters_digits_and_signs_are_a_us_layout_with_shift():
    t = Typist()
    for c in "hi":
        t.tap(letter(c))
    t.tap(letter("h"), SHIFT)
    t.tap(ONE)
    t.tap(ONE, SHIFT)
    t.tap(SLASH, SHIFT)
    t.tap(0x2C)                                 # space
    t.tap(0x34, 0x20)                           # ' with the right Shift
    assert bytes(t.typed) == b'hiH1!? "'


def test_caps_lock_is_for_the_letters_alone():
    t = Typist()
    t.tap(CAPS)
    t.tap(letter("a"))
    t.tap(letter("a"), SHIFT)
    t.tap(ONE)
    t.tap(CAPS)
    t.tap(letter("a"))
    assert bytes(t.typed) == b"Aa1a"


def test_the_keys_that_are_not_characters_are_kbds():
    t = Typist()
    for usage in (ENTER, ESCAPE, BACKSPACE, RIGHT, RIGHT + 1, RIGHT + 2, UP, 0x4B, 0x4E,
                  F1, F1 + 7, F12, HOME, 0x49, DELETE):
        t.tap(usage)
    t.tap(HOME, SHIFT)
    assert list(t.typed) == [
        p.NESP_KEY_ENTER, p.NESP_KEY_ESCAPE, p.NESP_KEY_BACKSPACE, p.NESP_KEY_RIGHT,
        p.NESP_KEY_LEFT, p.NESP_KEY_DOWN, p.NESP_KEY_UP, p.NESP_KEY_PAGE_UP,
        p.NESP_KEY_PAGE_DOWN, p.NESP_KEY_F1, p.NESP_KEY_F8, p.NESP_KEY_F12, p.NESP_KEY_HOME,
        p.NESP_KEY_INSERT, p.NESP_KEY_DELETE, p.NESP_KEY_SHIFT_HOME]


def test_keys_the_firmware_has_nothing_for_type_nothing():
    t = Typist()
    t.tap(KEYPAD_1)
    t.tap(0x4D)                                 # End
    t.tap(F1 + 8)                               # F9
    t.tap(letter("a"), GUI)                     # with the Windows key
    assert bytes(t.typed) == b""


def test_ctrl_and_enter_or_escape_are_start_and_select():
    t = Typist()
    t.tap(ENTER, CTRL)
    t.tap(ESCAPE, 0x10)                         # the right Ctrl
    assert list(t.typed) == [p.NESP_KEY_START, p.NESP_KEY_SELECT]


def test_a_key_with_ctrl_or_alt_comes_after_with_ctrl_or_with_alt():
    t = Typist()
    t.tap(letter("c"), CTRL)
    t.tap(letter("g"), ALT)
    t.tap(ENTER, CTRL | ALT)
    assert list(t.typed) == [p.NESP_KEY_WITH_CTRL, ord("c"), p.NESP_KEY_WITH_ALT, ord("g"),
                             p.NESP_KEY_WITH_CTRL, p.NESP_KEY_WITH_ALT, p.NESP_KEY_ENTER]


def test_a_key_is_typed_when_it_goes_down_and_not_again_while_it_is():
    t = Typist()
    k = t.keyboard
    k.report(0, [letter("a")], 0)
    k.report(0, [letter("a"), letter("b")], 10)
    k.report(0, [letter("b")], 20)
    k.report(0, [letter("b")], 30)
    k.report(0, [], 40)
    assert bytes(t.typed) == b"ab"


def test_too_many_keys_down_is_a_report_that_means_nothing():
    t = Typist()
    t.keyboard.report(0, [bridge.USAGE_ROLLOVER], 0)
    assert bytes(t.typed) == b""


def test_a_key_held_down_repeats_after_half_a_second_then_25_times_a_second():
    t = Typist()
    k = t.keyboard
    k.report(0, [letter("x")], 0)
    k.tick(499, lambda: False)
    assert bytes(t.typed) == b"x"
    k.tick(500, lambda: False)
    assert bytes(t.typed) == b"xx"
    for now in range(501, 1000):
        k.tick(now, lambda: False)
    assert bytes(t.typed) == b"x" * (2 + 12)    # 540, 580 ... 980
    k.report(0, [], 1000)
    k.tick(2000, lambda: False)
    assert bytes(t.typed) == b"x" * 14


def test_a_repeat_waits_until_what_was_typed_before_is_taken():
    t = Typist()
    k = t.keyboard
    k.report(0, [letter("x")], 0)
    for now in range(0, 1000, 10):
        k.tick(now, lambda: True)
    assert bytes(t.typed) == b"x"


def test_enter_escape_and_a_key_with_ctrl_do_not_repeat():
    for usage, modifiers in ((ENTER, 0), (ESCAPE, 0), (letter("c"), CTRL), (ENTER, CTRL)):
        t = Typist()
        t.keyboard.report(modifiers, [usage], 0)
        count = len(t.typed)
        t.keyboard.tick(5000, lambda: False)
        assert len(t.typed) == count


def test_shift_let_go_of_while_a_key_repeats_changes_what_it_types():
    t = Typist()
    k = t.keyboard
    k.report(SHIFT, [letter("a")], 0)
    k.report(0, [letter("a")], 100)
    k.tick(500, lambda: False)
    assert bytes(t.typed) == b"Aa"


# --- the Bluetooth keyboard, on the firmware's own KBD --------------------------

def state(stick):
    reply = stick.ask(KBD, p.NESP_KBD_STATE)
    assert reply.ok
    return reply.payload[0], reply.payload[1], bytes(reply.payload[3:])


def keys(stick):
    reply = stick.ask(KBD, p.NESP_KBD_KEYS)
    assert reply.ok
    return bytes(reply.payload[1:])


@pytest.fixture
def bt(stick):
    assert stick.hello(services=[KBD]).ok
    return bridge.BluetoothKeyboard(stick, bridge.Memory())


def pair(stick, bt, now=0):
    """The setup ROM's pairing: SCAN, until it is over; FOUND; PAIR."""
    assert stick.ask(KBD, p.NESP_KBD_SCAN).ok
    bt.update(now)
    assert state(stick)[0] == p.NESP_KEYBOARD_SCANNING
    now += bridge.SCAN_MS
    bt.update(now)
    assert state(stick)[:2] == (p.NESP_KEYBOARD_SCANNED, 1)
    found = stick.ask(KBD, p.NESP_KBD_FOUND, b"\x00")
    assert found.ok
    assert found.payload[3:] == bridge.KEYBOARD_NAME
    assert found.payload[1] == bridge.KEYBOARD_SIGNAL & 0xFF
    assert stick.ask(KBD, p.NESP_KBD_PAIR, b"\x00").ok
    bt.update(now)
    assert state(stick)[0] == p.NESP_KEYBOARD_PAIRING
    now += bridge.PAIR_MS
    bt.update(now)
    return now


def test_a_scan_finds_the_computers_keyboard_and_it_pairs(stick, bt):
    assert state(stick) == (p.NESP_KEYBOARD_UNPAIRED, 0, b"")
    pair(stick, bt)
    assert state(stick) == (p.NESP_KEYBOARD_CONNECTED, 0, bridge.KEYBOARD_NAME)
    assert bt.memory.paired
    assert stick.ask(KBD, p.NESP_KBD_FOUND, b"\x01").status == p.NESP_ST_NOT_FOUND


def test_nothing_is_typed_before_the_keyboard_is_paired(stick, bt):
    bt.report(0, [letter("a")], 0)
    bt.report(0, [], 10)
    assert keys(stick) == b""
    now = pair(stick, bt)
    bt.report(SHIFT, [letter("o")], now)
    bt.report(0, [letter("k")], now)
    bt.report(0, [], now)
    assert keys(stick) == b"Ok"


def test_what_is_typed_while_no_rom_has_kbd_is_dropped(stick, bt):
    pair(stick, bt)
    assert stick.hello(services=[p.NESP_SVC_NET]).ok
    bt.report(0, [letter("a")], 0)
    assert stick.hello(services=[KBD]).ok
    bt.report(0, [], 0)
    assert keys(stick) == b""


def test_forget_unpairs_it_and_the_next_board_has_none(stick, bt):
    pair(stick, bt)
    assert stick.ask(KBD, p.NESP_KBD_FORGET).ok
    bt.update(0)
    assert state(stick) == (p.NESP_KEYBOARD_UNPAIRED, 0, b"")
    assert not bt.memory.paired
    bt.report(0, [letter("a")], 0)
    assert keys(stick) == b""


def test_a_board_after_a_reset_has_the_keyboard_paired_before(stick):
    memory = bridge.Memory()
    memory.paired = True
    bridge.BluetoothKeyboard(stick, memory)
    assert stick.hello(services=[KBD]).ok
    assert state(stick) == (p.NESP_KEYBOARD_CONNECTED, 0, bridge.KEYBOARD_NAME)


def test_repeats_come_at_the_roms_pace(stick, bt):
    now = pair(stick, bt)
    bt.report(0, [RIGHT], now)
    for t in range(now, now + 2000, 10):
        bt.update(t)
    # Nothing was taken, so the key held down came once only.
    assert keys(stick) == bytes((p.NESP_KEY_RIGHT,))
    bt.update(now + 2040)
    assert keys(stick) == bytes((p.NESP_KEY_RIGHT,))
    bt.report(0, [], now + 2050)
    bt.update(now + 3000)
    assert keys(stick) == b""


def test_no_more_is_held_than_the_firmware_holds(stick, bt):
    now = pair(stick, bt)
    for _ in range(bridge.HELD + 10):
        bt.report(0, [letter("a")], now)
        bt.report(0, [], now)
    assert stick.kbd_unread == bridge.HELD


# --- the board: what Mesen hears, and a ROM's files ---------------------------

def test_the_reply_line_ends_with_how_the_keyboard_stands():
    board = bridge.Board(bridge.Memory())
    assert board.sync(1000, []) == "R 0 0  K %d 0\n" % p.NESP_KEYBOARD_UNPAIRED


def test_a_roms_files_are_kept_in_the_directory_and_back_on_the_next_board(tmp_path):
    memory = bridge.Memory(str(tmp_path))
    board = bridge.Board(memory)
    stick = board.stick
    assert stick.hello(services=[p.NESP_SVC_TAPE]).ok
    program = b"10 PRINT 1\x00"
    header = bytearray(b"\x00" * p.NESP_TAPE_HEADER)
    header[p.NESP_TAPE_TYPE_AT] = 2
    header[p.NESP_TAPE_NAME_AT:p.NESP_TAPE_NAME_AT + 5] = b"HELLO"
    header[p.NESP_TAPE_LENGTH_AT:p.NESP_TAPE_LENGTH_AT + 2] = len(program).to_bytes(2, "little")
    pair_ = bytes(header) + program
    for at in range(0, len(pair_), 100):
        assert stick.ask(p.NESP_SVC_TAPE, p.NESP_TAPE_PUT,
                         at.to_bytes(2, "little") + pair_[at:at + 100]).ok
    assert stick.ask(p.NESP_SVC_TAPE, p.NESP_TAPE_SAVE,
                     bytes((1, 0)) + len(program).to_bytes(2, "little")).ok
    stick.tick(0)
    board.files()
    name = stick.file_names[0]
    assert (tmp_path / "files" / name).read_bytes() == pair_
    again = bridge.Board(bridge.Memory(str(tmp_path)))
    assert again.stick.file(name) == pair_


def test_the_pairing_is_kept_in_the_directory(tmp_path):
    bridge.Memory(str(tmp_path)).set_paired(True)
    assert bridge.Memory(str(tmp_path)).paired
    bridge.Memory(str(tmp_path)).set_paired(False)
    assert not bridge.Memory(str(tmp_path)).paired


def test_secrets_in_an_address_are_not_logged():
    assert bridge.redact("https://x/y?username=me&key=s3cret&q=1") == \
        "https://x/y?username=...&key=...&q=1"


# --- fetches --------------------------------------------------------------------

class Site(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/to-a-file":
            self.send_response(302)
            self.send_header("Location", "file:///etc/hosts")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/moved":
            self.send_response(302)
            self.send_header("Location", "/there")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/there":
            body, code = b"hello", 200
        else:
            body, code = b"not here", 404
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def site():
    server = http.server.HTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % server.server_address[1]
    server.shutdown()


def fetched(url, icy=False, head=False):
    fetcher = bridge.Fetcher(1, url, b"test", icy, head)
    items = []
    while not items or items[-1][0] != "done":
        items.append(fetcher.items.get(timeout=15))
    return items


def test_a_sink_with_a_head_hears_the_status_type_and_length_first(site):
    assert fetched(site + "/there", head=True) == [
        ("head", 200, b"text/plain", 5), ("body", b"hello"), ("done", True, b"")]


def test_a_sink_with_a_head_hears_a_404_and_its_body(site):
    assert fetched(site + "/gone", head=True) == [
        ("head", 404, b"text/plain", 8), ("body", b"not here"), ("done", True, b"")]


def test_for_any_other_sink_a_404_is_a_fetch_that_failed(site):
    assert fetched(site + "/gone") == [("done", False, b"THE SITE SAID 404")]


def test_a_site_that_is_not_there_did_not_answer():
    with __import__("socket").socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert fetched("http://127.0.0.1:%d/" % port) == [("done", False, b"THE SITE DID NOT ANSWER")]


@pytest.mark.parametrize("url", ["file:///etc/hosts", "FILE:///etc/hosts",
                                 "data:text/plain,secret", "ftp://127.0.0.1/x", "/etc/hosts"])
def test_only_http_and_https_are_fetched_as_the_firmware_does(url):
    for head in (False, True):
        assert fetched(url, head=head) == [("done", False, b"THE SITE DID NOT ANSWER")]


def test_a_redirect_is_followed_to_http(site):
    assert fetched(site + "/moved") == [("body", b"hello"), ("done", True, b"")]


def test_a_redirect_to_a_file_is_not_followed(site):
    assert fetched(site + "/to-a-file") == [("done", False, b"THE SITE SAID 302")]
    items = fetched(site + "/to-a-file", head=True)
    assert items[0][:2] == ("head", 302)
    assert b"localhost" not in b"".join(i[1] for i in items if i[0] == "body")


# --- the Bluetooth keyboard, with a helper (real Bluetooth, here a fake one) ----

class FakeHelper:
    """What bridge.HelperLink is to the bridge: lines sent, lines to poll."""

    def __init__(self, up=True):
        self.up = up
        self.sent = []
        self.incoming = []

    def send(self, line):
        if self.up:
            self.sent.append(line)
        return self.up

    def poll(self):
        got, self.incoming = self.incoming, []
        return got


@pytest.fixture
def helped(stick):
    assert stick.hello(services=[KBD]).ok
    helper = FakeHelper()
    return bridge.BluetoothKeyboard(stick, bridge.Memory(), helper), helper


def scan_with_helper(stick, bt, helper, devices):
    assert stick.ask(KBD, p.NESP_KBD_SCAN).ok
    bt.update(0)
    assert helper.sent[-1].startswith("SCAN ")
    assert state(stick)[0] == p.NESP_KEYBOARD_SCANNING
    helper.incoming = ["D %s %d %s" % d for d in devices] + ["SCANDONE"]
    bt.update(10)


def test_a_helper_scan_finds_what_it_heard_strongest_first(stick, helped):
    bt, helper = helped
    scan_with_helper(stick, bt, helper, [("AA:BB:CC:00:00:01", -80, "Far one"),
                                         ("AA:BB:CC:00:00:02", -40, "Near keyboard")])
    assert state(stick)[:2] == (p.NESP_KEYBOARD_SCANNED, 3)
    assert stick.ask(KBD, p.NESP_KBD_FOUND, b"\x00").payload[3:] == b"Mesen PC keyboard"
    near = stick.ask(KBD, p.NESP_KBD_FOUND, b"\x01")
    assert near.payload[3:] == b"Near keyboard"
    assert near.payload[1] == -40 & 0xFF
    assert stick.ask(KBD, p.NESP_KBD_FOUND, b"\x02").payload[3:] == b"Far one"


def test_a_long_name_is_cut_and_no_more_than_eight_are_kept(stick, helped):
    bt, helper = helped
    devices = [("AA:BB:CC:00:00:%02X" % i, -50 - i, "n" * 40 if i == 0 else "k%d" % i)
               for i in range(11)]
    scan_with_helper(stick, bt, helper, devices)
    assert state(stick)[:2] == (p.NESP_KEYBOARD_SCANNED, 8)
    assert stick.ask(KBD, p.NESP_KBD_FOUND, b"\x01").payload[3:] == b"n" * 24


def test_a_helper_that_is_not_there_is_a_scan_that_finds_nothing(stick):
    assert stick.hello(services=[KBD]).ok
    bt = bridge.BluetoothKeyboard(stick, bridge.Memory(), FakeHelper(up=False))
    assert stick.ask(KBD, p.NESP_KBD_SCAN).ok
    bt.update(0)
    assert state(stick)[:2] == (p.NESP_KEYBOARD_SCANNED, 1)
    assert stick.ask(KBD, p.NESP_KBD_FOUND, b"\x00").payload[3:] == b"Mesen PC keyboard"


def test_the_keyboard_chosen_is_the_one_paired(stick, helped):
    bt, helper = helped
    scan_with_helper(stick, bt, helper, [("AA:BB:CC:00:00:01", -80, "Far one"),
                                         ("AA:BB:CC:00:00:02", -40, "Near keyboard")])
    assert stick.ask(KBD, p.NESP_KBD_PAIR, b"\x02").ok
    bt.update(20)
    assert helper.sent[-1] == "PAIR AA:BB:CC:00:00:01"
    assert state(stick)[0] == p.NESP_KEYBOARD_PAIRING
    helper.incoming = ["PASSKEY 123456", "PAIRED AA:BB:CC:00:00:01 Far one"]
    bt.update(30)
    assert state(stick) == (p.NESP_KEYBOARD_CONNECTED, 0, b"Far one")
    assert bt.memory.paired and bt.memory.address == "AA:BB:CC:00:00:01"


def test_a_pairing_that_fails_is_failed(stick, helped):
    bt, helper = helped
    scan_with_helper(stick, bt, helper, [("AA:BB:CC:00:00:01", -80, "Far one")])
    assert stick.ask(KBD, p.NESP_KBD_PAIR, b"\x01").ok
    bt.update(20)
    helper.incoming = ["PAIRFAIL AuthenticationFailed"]
    bt.update(30)
    assert state(stick)[0] == p.NESP_KEYBOARD_FAILED
    assert not bt.memory.paired


def test_the_helpers_keys_are_typed_and_the_computers_are_not(stick, helped):
    bt, helper = helped
    scan_with_helper(stick, bt, helper, [("AA:BB:CC:00:00:01", -80, "Far one")])
    assert stick.ask(KBD, p.NESP_KBD_PAIR, b"\x01").ok
    bt.update(20)
    helper.incoming = ["PAIRED AA:BB:CC:00:00:01 Far one"]
    bt.update(30)
    bt.report(0, [letter("z")], 40)
    bt.report(0, [], 41)
    assert keys(stick) == b""
    helper.incoming = ["K 2 %d" % letter("o"), "K 0 %d" % letter("k"), "K 0"]
    bt.update(50)
    assert keys(stick) == b"Ok"


def test_with_a_helper_the_computers_keyboard_can_still_be_paired(stick, helped):
    bt, helper = helped
    scan_with_helper(stick, bt, helper, [("AA:BB:CC:00:00:01", -40, "Near keyboard")])
    sent = len(helper.sent)
    assert stick.ask(KBD, p.NESP_KBD_PAIR, b"\x00").ok
    bt.update(20)
    assert len(helper.sent) == sent
    assert state(stick) == (p.NESP_KEYBOARD_CONNECTED, 0, b"Mesen PC keyboard")
    helper.incoming = ["K 0 %d" % letter("z"), "K 0"]
    bt.update(30)
    bt.report(2, [letter("o")], 40)
    bt.report(0, [letter("k")], 41)
    bt.report(0, [], 42)
    assert keys(stick) == b"Ok"
    assert stick.ask(KBD, p.NESP_KBD_FORGET).ok
    bt.update(50)
    assert len(helper.sent) == sent
    assert not bt.memory.paired


def test_forget_tells_the_helper(stick, helped):
    bt, helper = helped
    bt.memory.set_paired(True, "AA:BB:CC:00:00:01", "Far one")
    assert stick.ask(KBD, p.NESP_KBD_FORGET).ok
    bt.update(0)
    assert helper.sent[-1] == "FORGET AA:BB:CC:00:00:01"
    assert state(stick)[0] == p.NESP_KEYBOARD_UNPAIRED
    assert not bt.memory.paired


def test_a_board_after_a_reset_has_the_real_keyboard_paired_before(stick, tmp_path):
    memory = bridge.Memory(str(tmp_path))
    memory.set_paired(True, "AA:BB:CC:00:00:01", "Far one")
    memory = bridge.Memory(str(tmp_path))
    bridge.BluetoothKeyboard(stick, memory, FakeHelper())
    assert stick.hello(services=[KBD]).ok
    assert state(stick) == (p.NESP_KEYBOARD_CONNECTED, 0, b"Far one")


def test_the_helpers_evdev_keys_make_hid_reports():
    sys.path.insert(0, os.path.join(HERE, "..", "host", "mesen"))
    helper = pytest.importorskip("nesp32_bt_helper")
    pytest.importorskip("evdev")
    usages, mods = helper.keycodes()
    k = helper.Keys(usages, mods)
    from evdev import ecodes as e
    assert k.event(e.KEY_LEFTSHIFT, 1) == "K 2"
    assert k.event(e.KEY_A, 1) == "K 2 4"
    assert k.event(e.KEY_A, 2) is None
    assert k.event(e.KEY_A, 0) == "K 2"
    assert k.event(e.KEY_LEFTSHIFT, 0) == "K 0"
    assert k.event(e.KEY_ENTER, 1) == "K 0 40"


# --- the helper's key -----------------------------------------------------------

def helper_module():
    sys.path.insert(0, os.path.join(HERE, "..", "host", "mesen"))
    import nesp32_bt_helper
    return nesp32_bt_helper


def test_the_helpers_key_is_made_once_and_kept_for_its_user_alone(tmp_path):
    h = helper_module()
    key = h.Helper(str(tmp_path)).key
    assert len(key) == 32
    assert h.Helper(str(tmp_path)).key == key
    assert os.stat(tmp_path / "key").st_mode & 0o077 == 0


def connected(helper, first_line):
    """A bridge's end of a connection to the helper that starts with first_line."""
    ours, theirs = socket.socketpair()
    threading.Thread(target=helper.serve, args=(theirs,), daemon=True).start()
    ours.sendall(first_line)
    ours.settimeout(5)
    return ours


def wait_for_clients(helper, count):
    for _ in range(500):
        if len(helper.clients) == count:
            return
        time.sleep(0.01)
    assert len(helper.clients) == count


@pytest.mark.parametrize("first_line", [b"HELLO wrong\n", b"SCAN 6\n", b"HELLO\n"])
def test_a_connection_without_the_key_is_closed_and_hears_no_keys(tmp_path, first_line):
    helper = helper_module().Helper(str(tmp_path))
    conn = connected(helper, first_line)
    assert conn.recv(100) == b""                    # closed, with nothing said
    helper.tell("K 0 4")
    assert helper.clients == []


def test_a_connection_with_the_key_hears_the_keys(tmp_path):
    helper = helper_module().Helper(str(tmp_path))
    conn = connected(helper, b"HELLO %s\n" % helper.key.encode())
    wait_for_clients(helper, 1)
    helper.tell("K 2 4")
    assert conn.recv(100) == b"K 2 4\n"
    conn.close()


def test_the_bridge_says_hello_with_the_key_before_anything_else():
    server = socket.create_server(("127.0.0.1", 0))
    link = bridge.HelperLink("127.0.0.1:%d" % server.getsockname()[1], "abc123")
    assert link.send("SCAN 6")
    conn, _ = server.accept()
    conn.settimeout(5)
    got = b""
    while got.count(b"\n") < 2:
        got += conn.recv(100)
    assert got == b"HELLO abc123\nSCAN 6\n"
    conn.close()
    server.close()


# --- lines that make no sense ---------------------------------------------------

def test_an_s_line_is_its_cycle_and_out0s_changes():
    assert bridge.parse_sync(b"S 100 2 10 0 20 1".split()) == (100, [(10, 0), (20, 1)])
    assert bridge.parse_sync(b"S 100 0".split()) == (100, [])


@pytest.mark.parametrize("line", [b"S", b"S 100", b"S x 0", b"S 100 2 10 0", b"S 100 1 10 0 7",
                                  b"S 100 -1", b"S 100 1 10 y"])
def test_an_s_line_that_is_not_one_is_a_value_error(line):
    with pytest.raises(ValueError):
        bridge.parse_sync(line.split())


def test_a_line_from_mesen_that_makes_no_sense_is_passed_over(tmp_path):
    server = socket.create_server(("127.0.0.1", 0))
    ours = socket.create_connection(server.getsockname())
    theirs, _ = server.accept()
    server.close()
    threading.Thread(target=bridge.serve, args=(theirs, "test", bridge.Memory()),
                     daemon=True).start()
    ours.settimeout(5)
    replies = ours.makefile("rb")
    # Each S is answered, the one that is not one too, as the script waits.
    ours.sendall(b"S 100 1 50\nB\nB x\nK\nK 2 x\nQ 1\nS 200 0\n")
    assert replies.readline().startswith(b"R ")
    assert replies.readline().startswith(b"R ")
    ours.sendall(b"S 300 0\n")
    assert replies.readline().startswith(b"R ")    # still up
    ours.close()


def test_a_line_from_the_helper_that_makes_no_sense_is_passed_over(stick, helped):
    bt, helper = helped
    assert stick.ask(KBD, p.NESP_KBD_SCAN).ok
    bt.update(0)
    helper.incoming = ["D AA:BB:CC:00:00:01 loud Bad one", "PASSKEY", "K", "K x 4",
                       "D AA:BB:CC:00:00:02 -40 Near keyboard", "SCANDONE"]
    bt.update(10)
    assert state(stick)[:2] == (p.NESP_KEYBOARD_SCANNED, 2)
    assert stick.ask(KBD, p.NESP_KBD_FOUND, b"\x01").payload[3:] == b"Near keyboard"


@pytest.mark.parametrize("line", ["SCAN x", "SCAN ²"])
def test_a_scan_of_no_number_is_an_error_at_the_helper(tmp_path, monkeypatch, line):
    h = helper_module()
    monkeypatch.setattr(h, "scan", lambda seconds: pytest.fail("scanned"))
    helper = h.Helper(str(tmp_path))
    ours, theirs = socket.socketpair()
    ours.settimeout(5)
    helper.handle(theirs, line)
    assert ours.recv(100).startswith(b"ERR ")


# --- the UART's buffer ----------------------------------------------------------

def test_the_bridges_uart_holds_what_the_boards_does_and_the_tests_model_is_untouched():
    import wire
    assert bridge.Board().port.tx_buffer == bridge.UART_BUFFER == 2048
    assert wire.TX_BUFFER == 256
    assert wire.Port(bridge.Console()).tx_buffer == 256
