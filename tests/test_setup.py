"""The setup ROM on a simulated console, with the firmware's own link and
services at the other end of a cycle-exact line: every screen, worked with
the controller.
"""

import random
import string

import gen_screen as layout
import nesp
import nesp_proto as p
import pytest
from console import VBLANK_CYCLES
from drive import (PAD_A, PAD_B, PAD_DOWN, PAD_SELECT, PAD_START, PAD_UP, STATE_FAILED,
                   STATE_JOINING, STATE_KEYS, STATE_LIST, STATE_SCAN, STATE_STATUS, STATE_TEST,
                   STATE_USB, Setup)
from drive import MENU_TEST, MENU_USB
from nesp import Stick
from wire import link, ms

HOME = (b"Home Network", -48, p.NESP_AUTH_PASSWORD, 6)
CAFE = (b"Cafe", -70, p.NESP_AUTH_OPEN, 11)
FAR = (b"A very long name for a network!!", -90, p.NESP_AUTH_PASSWORD, 1)
WORK = (b"Work", -60, p.NESP_AUTH_OTHER, 3)
NETWORKS = [HOME, WORK, CAFE, FAR]
PRINTABLE = "".join(chr(code) for code in range(0x20, 0x7F))


@pytest.fixture
def setup(linked):
    def make(**port_options):
        return Setup(*linked(**port_options))
    return make


def joined(stick, name, rssi=-52, address=(192, 168, 1, 77)):
    stick.set_wifi(p.NESP_WIFI_JOINED, rssi=rssi, address=address)
    stick.set_saved(name)


# --- status ----------------------------------------------------------------------

def test_with_no_stick_it_says_so(console):
    c = console()
    c.run(60)
    s = Setup(c, None, None)
    assert s.heading == "STATUS"
    assert s.values() == dict.fromkeys(layout.STATUS_LABELS, "-") | {"NESP32": "NOT FOUND"}
    c.press(PAD_A)
    c.press(PAD_B)
    c.run(10)
    assert s.state == STATE_STATUS      # there is nothing to set up or test


def test_the_header_is_the_name_and_what_this_is(console):
    c = console()
    c.run(3)
    header = layout.build_screen()
    count = 32 * layout.HEADER_ROWS
    assert bytes(c.vram[0x2000:0x2000 + count]) == bytes(header.names[:count])
    # What this is, right under the name: a picture, set to the pixel, in
    # the credit line's blue and not the text's white.
    assert layout.TITLE_TEXT == "SETUP" and layout.TITLE_ROW == layout.LOGO_ROW + 2
    title = [header.tiles[tile] for row in range(layout.TITLE_ROW, layout.CREDIT_ROW)
             for tile in header.names[32 * row:32 * row + 32]]
    assert any(any(tile) for tile in title) and not any(any(tile[:8]) for tile in title)
    assert layout.CREDIT_ROW == layout.TITLE_ROW + layout.TITLE_ROWS
    # The credit line is a picture, in a font smaller than a tile.
    credit = c.text(layout.CREDIT_ROW, layout.CREDIT_COLUMN, layout.CREDIT_TILES)
    assert credit.count("^") >= 8 and c.line(layout.CREDIT_ROW) == credit.strip()
    # The name is 2 x 2 tiles a letter, of tiles that are not characters.
    column = (32 - 2 * len(layout.LOGO_TEXT)) // 2
    for row in (layout.LOGO_ROW, layout.LOGO_ROW + 1):
        assert c.text(row, column, 2 * len(layout.LOGO_TEXT)).count("^") >= len(layout.LOGO_TEXT)


def test_a_stick_is_greeted_and_shown(setup):
    s = setup()
    joined(s.stick, b"Home Network", rssi=-61)
    s.stick.set_battery(83)
    s.settle(80)
    assert s.values() == {
        "NESP32": "CONNECTED", "FIRMWARE": "0.1.0", "BOARD": "Computer", "WI-FI": "JOINED",
        "NETWORK": "Home Network", "ADDRESS": "192.168.1.77", "SIGNAL": "-61 DBM",
        "BATTERY": "83%"}
    assert s.stick.app == (b"SETP", 1)
    assert s.stick.active(p.NESP_SVC_NET) and s.stick.active(p.NESP_SVC_DIAG)
    assert s.stick.hellos == 1          # once, not every round


def test_a_stick_with_no_network_and_no_battery_gauge(setup):
    s = setup()
    s.settle(80)
    assert s.values() == {
        "NESP32": "CONNECTED", "FIRMWARE": "0.1.0", "BOARD": "Computer", "WI-FI": "NOT SET UP",
        "NETWORK": "-", "ADDRESS": "-", "SIGNAL": "-", "BATTERY": "-"}


def test_every_address_and_number_is_written_right(setup):
    s = setup()
    for address, rssi, battery in (((0, 0, 0, 0), -1, 0), ((255, 255, 255, 255), -128, 100),
                                   ((10, 0, 100, 9), -9, 7), ((1, 20, 3, 199), -100, 99)):
        joined(s.stick, b"n", rssi=rssi, address=address)
        s.stick.set_battery(battery)
        s.settle(80)
        assert s.value("ADDRESS") == ".".join(str(part) for part in address)
        assert s.value("SIGNAL") == "%d DBM" % rssi
        assert s.value("BATTERY") == "%d%%" % battery


def test_a_stick_that_is_unplugged_is_missed_and_one_plugged_in_is_found(setup):
    s = setup()
    joined(s.stick, b"Home Network")
    s.settle(80)
    s.port.deaf = True
    s.settle(200)
    assert s.values() == dict.fromkeys(layout.STATUS_LABELS, "-") | {"NESP32": "NOT FOUND"}
    s.port.deaf = False
    s.settle(200)
    assert s.value("NESP32") == "CONNECTED" and s.value("NETWORK") == "Home Network"
    assert s.stick.hellos == 2


def test_a_stick_from_another_protocol_is_not_used(console):
    c = console()

    def older(data):
        reply = nesp.parse(data)
        if reply.svc == p.NESP_SVC_SYS and len(reply.payload) == 7:    # a hello's
            return nesp.reply_frame(reply.svc, p.NESP_ST_VERSION, reply.seq, reply.payload)
        return data

    stick, port = link(c, Stick, to_console=older)
    s = Setup(c, stick, port)
    c.run(120)
    assert s.value("NESP32") == "NEEDS AN UPDATE" and s.value("FIRMWARE") == "-"
    c.press(PAD_A)
    c.run(10)
    assert s.state == STATE_STATUS


# --- choosing a network ----------------------------------------------------------

def test_the_networks_found_are_listed_with_their_locks_and_strengths(setup):
    s = setup()
    s.press(PAD_A)
    s.wait_for(STATE_SCAN)
    assert s.heading == "CHOOSE A NETWORK" and s.message == "LOOKING FOR NETWORKS..."
    s.c.run(60)
    assert s.state == STATE_SCAN and s.stick.scans == 1     # it waits, and asks once
    s.stick.scan_set(NETWORKS)
    s.stick.scan_finish()
    s.wait_for(STATE_LIST)
    s.settle()
    assert s.listed()[:6] == [
        ("Home Network", True, 4), ("Work", True, 3), ("Cafe", False, 2),
        ("A very long name for a", True, 1), ("OTHER NETWORK...", False, 0), ("", False, 0)]
    assert s.arrow_line == 0


def test_the_arrow_moves_and_stops_at_the_ends(setup):
    s = setup()
    s.scan(NETWORKS)
    s.press(PAD_UP)
    assert s.arrow_line == 0
    for line in (1, 2, 3, 4, 4, 4):         # OTHER NETWORK is the last
        s.press(PAD_DOWN)
        assert s.arrow_line == line


def test_a_long_list_scrolls(setup):
    s = setup()
    many = [(b"Network %02d" % index, -40 - index, p.NESP_AUTH_PASSWORD) for index in range(20)]
    s.scan(many)
    names = [name for name, _, _ in s.listed()]
    assert names == ["Network %02d" % index for index in range(layout.LIST_ROWS)]
    for _ in range(20):
        s.press(PAD_DOWN)
    s.settle()
    names = [name for name, _, _ in s.listed()]
    assert names[-1] == "OTHER NETWORK..." and names[-2] == "Network 19"
    assert s.arrow_line == layout.LIST_ROWS - 1
    for _ in range(25):
        s.press(PAD_UP)
    s.settle()
    assert s.listed()[0][0] == "Network 00" and s.arrow_line == 0


def test_no_networks_still_leaves_the_other_one(setup):
    s = setup()
    s.scan([])
    assert s.listed()[:2] == [("OTHER NETWORK...", False, 0), ("", False, 0)]


def test_a_name_with_odd_bytes_is_shown_without_them(setup):
    s = setup()
    s.scan([(b"caf\xc3\xa9\x01", -50, p.NESP_AUTH_OPEN)])
    assert s.listed()[0][0] == "caf???"


def test_select_looks_again_and_b_goes_back(setup):
    s = setup()
    s.scan(NETWORKS)
    s.press(PAD_SELECT)
    s.wait_for(STATE_SCAN)
    s.c.run_until(lambda: s.stick.scans == 2, 60)
    s.stick.scan_set([CAFE])
    s.stick.scan_finish()
    s.wait_for(STATE_LIST)
    s.settle()
    assert s.listed()[:2] == [("Cafe", False, 2), ("OTHER NETWORK...", False, 0)]
    s.press(PAD_B)
    s.wait_for(STATE_STATUS)
    # and the arrow is the status screen's own, at the top of its menu
    assert s.heading == "STATUS" and s.c.sprite()[1] == 8 * (layout.BODY_ROW + 9)


def test_a_scan_the_stick_never_finishes_is_given_up(setup):
    s = setup()
    s.press(PAD_A)
    s.wait_for(STATE_SCAN)
    s.c.run(8 * 150 + 30)
    assert s.state == STATE_STATUS and s.message == "NO ANSWER FROM THE NESP32"


def test_a_scan_that_fails_is_started_again(setup):
    s = setup()
    s.press(PAD_A)
    s.c.run_until(lambda: s.stick.scans == 1, 120)
    s.stick.scan_finish(p.NESP_SCAN_FAILED)
    s.c.run_until(lambda: s.stick.scans == 2, 120)
    s.stick.scan_set([HOME])
    s.stick.scan_finish()
    s.wait_for(STATE_LIST)


def test_a_kind_of_network_the_stick_cannot_join_is_refused(setup):
    s = setup()
    s.scan(NETWORKS)
    s.choose(1)                         # Work: neither open nor a password
    s.wait_for_message("CANNOT JOIN THAT KIND")
    assert s.state == STATE_LIST and s.stick.joins == 0


# --- typing and joining ----------------------------------------------------------

def test_a_network_is_joined_with_a_password_typed_on_the_controller(setup):
    s = setup()
    s.scan(NETWORKS)
    s.choose(0)
    s.wait_for(STATE_KEYS)
    assert s.heading == "PASSWORD FOR"
    assert s.c.line(layout.BODY_ROW) == "Home Network"
    assert s.field == "_"
    s.type("Tr0ub4dor & 3")
    s.settle(4)
    assert s.field == "Tr0ub4dor & 3_"
    s.press(PAD_START)
    s.wait_for(STATE_JOINING)
    assert s.heading == "JOINING" and s.c.line(layout.BODY_ROW) == "Home Network"
    s.wait_for_message("JOINING...")
    assert (s.stick.joins, s.stick.joined_name, s.stick.joined_password) == (
        1, b"Home Network", b"Tr0ub4dor & 3")
    s.c.run(100)
    assert s.state == STATE_JOINING     # it waits to hear
    joined(s.stick, b"Home Network")
    s.wait_for(STATE_STATUS)
    s.settle(80)
    assert s.value("WI-FI") == "JOINED" and s.value("NETWORK") == "Home Network"
    assert s.value("ADDRESS") == "192.168.1.77"


def test_every_printable_character_can_be_typed(setup):
    # A hidden network with the longest name there is, and the longest
    # password: 95 characters between them, which is every one, once.
    characters = list(PRINTABLE)
    random.Random(95).shuffle(characters)
    if characters[0] == " ":            # a name does not begin with a space here
        characters[0], characters[1] = characters[1], characters[0]
    name = "".join(characters[:p.NESP_NAME_MAX])
    password = "".join(characters[p.NESP_NAME_MAX:])
    assert len(password) == p.NESP_PASSWORD_MAX and sorted(name + password) == sorted(PRINTABLE)
    s = setup()
    s.scan(NETWORKS)
    s.choose(len(NETWORKS))             # OTHER NETWORK...
    s.wait_for(STATE_KEYS)
    assert s.heading == "NAME OF THE NETWORK"
    s.type(name)
    s.press(PAD_A)                      # one more than fits is not taken
    assert s.c.byte("keys_len") == p.NESP_NAME_MAX
    s.press(PAD_START)
    s.wait_for(STATE_KEYS)
    assert s.heading == "PASSWORD FOR"
    s.type(password)
    s.settle(4)
    # The field shows the end of it, and no cursor: it is full.
    assert s.field == password[-(layout.FIELD_WIDTH - 1):].rstrip()
    s.press(PAD_START)
    s.wait_for(STATE_JOINING)
    assert (s.stick.joined_name, s.stick.joined_password) == (name.encode(), password.encode())


def test_the_three_sets_of_keys_are_drawn(setup):
    s = setup()
    s.scan(NETWORKS)
    s.choose(0)
    s.wait_for(STATE_KEYS)
    s.settle(10)

    def keys():
        return [s.c.text(layout.KEY_ROW + layout.KEY_STEP * row, layout.KEY_COLUMN,
                         layout.KEY_STEP * layout.KEY_COLUMNS)[::layout.KEY_STEP]
                for row in range(layout.KEY_ROWS)]

    for layer in (0, 1, 2, 0):
        assert keys() == list(layout.LAYERS[layer])
        s.press(PAD_SELECT)
        s.settle(10)
    assert s.c.line(layout.SPACE_ROW) == "SPACE"
    # The cursor is a bar under its key.
    x, y, tile = s.c.sprite()
    assert s.tile_names()[tile] == "UNDER"
    assert (x, y) == (8 * layout.KEY_COLUMN, 8 * (layout.KEY_ROW + layout.KEY_STEP) + 8)


def test_an_empty_key_types_nothing_and_b_deletes(setup):
    s = setup()
    s.scan(NETWORKS)
    s.choose(0)
    s.wait_for(STATE_KEYS)
    s.type("ab")
    s.press(PAD_SELECT)
    s.press(PAD_SELECT)                 # the signs: the b's row has none
    s.press(PAD_A)
    s.settle(4)
    assert s.field == "ab_"
    s.press(PAD_B)
    s.settle(4)
    assert s.field == "a_"
    s.press(PAD_B)
    s.press(PAD_B)                      # nothing left: back to the list
    s.wait_for(STATE_LIST)
    s.settle()
    assert s.listed()[0][0] == "Home Network" and s.stick.joins == 0


def test_an_open_network_is_joined_without_a_keyboard(setup):
    s = setup()
    s.scan(NETWORKS)
    s.choose(2)
    s.wait_for(STATE_JOINING)
    assert (s.stick.joined_name, s.stick.joined_password) == (b"Cafe", b"")


def test_a_long_name_is_joined_whole_though_the_list_cut_it(setup):
    s = setup()
    s.scan(NETWORKS)
    s.choose(3)
    s.wait_for(STATE_KEYS)
    assert s.c.line(layout.BODY_ROW) == FAR[0].decode()[:layout.WIDTH]
    s.type("pw")
    s.press(PAD_START)
    s.wait_for(STATE_JOINING)
    assert (s.stick.joined_name, s.stick.joined_password) == (FAR[0], b"pw")


@pytest.mark.parametrize("why, text", [
    (p.NESP_WHY_PASSWORD, "WRONG PASSWORD"),
    (p.NESP_WHY_NO_NETWORK, "NETWORK NOT FOUND"),
    (p.NESP_WHY_OTHER, "COULD NOT JOIN"),
])
def test_a_join_that_fails_says_why_and_the_password_can_be_put_right(setup, why, text):
    s = setup()
    s.scan(NETWORKS)
    s.choose(0)
    s.wait_for(STATE_KEYS)
    s.type("wrnog")
    s.press(PAD_START)
    s.wait_for(STATE_JOINING)
    s.stick.set_wifi(p.NESP_WIFI_FAILED, why=why)
    s.wait_for(STATE_FAILED)
    s.settle(10)
    assert s.message == text and s.c.line(layout.HELP_ROW) == "A:TRY AGAIN  B:BACK"
    s.press(PAD_A)
    s.wait_for(STATE_KEYS)
    assert s.field == "wrnog_"          # what was typed is still there
    for _ in range(3):
        s.press(PAD_B)
    s.type("ong")
    s.press(PAD_START)
    s.wait_for(STATE_JOINING)
    assert (s.stick.joins, s.stick.joined_password) == (2, b"wrong")


def test_after_a_failed_join_b_looks_for_networks_again(setup):
    s = setup()
    s.scan(NETWORKS)
    s.choose(2)
    s.wait_for(STATE_JOINING)
    s.stick.set_wifi(p.NESP_WIFI_FAILED, why=p.NESP_WHY_OTHER)
    s.wait_for(STATE_FAILED)
    s.press(PAD_B)
    s.wait_for(STATE_SCAN)


def test_a_join_the_stick_never_ends_is_given_up(setup):
    s = setup()
    s.scan(NETWORKS)
    s.choose(2)
    s.wait_for(STATE_JOINING)
    s.c.run(16 * 170 + 40)
    assert s.state == STATE_FAILED and s.message == "NO ANSWER FROM THE NESP32"


def test_a_password_gets_through_a_line_that_loses_and_damages_replies(setup):
    generator = random.Random(7)

    def rough(data):
        roll = generator.random()
        if roll < 0.25:
            return None                             # lost
        if roll < 0.5:
            damaged = bytearray(data)
            damaged[generator.randrange(len(damaged))] ^= 1 << generator.randrange(8)
            return bytes(damaged)
        return data

    s = setup()
    s.scan(NETWORKS)
    s.choose(0)
    s.wait_for(STATE_KEYS)
    password = "".join(random.Random(8).choice(string.ascii_letters + string.punctuation)
                       for _ in range(p.NESP_PASSWORD_MAX))
    s.type(password)
    s.port.to_console = rough
    s.press(PAD_START)
    s.wait_for(STATE_JOINING, 900)
    s.port.to_console = None
    assert (s.stick.joins, s.stick.joined_name, s.stick.joined_password) == (
        1, b"Home Network", password.encode())
    assert s.stick.repeats > 0          # and it was the repeats that got it there


def test_requests_that_are_lost_do_not_garble_a_password(setup):
    s = setup()
    s.scan(NETWORKS)
    s.choose(0)
    s.wait_for(STATE_KEYS)
    s.type("x" * 40 + "tail")
    generator = random.Random(3)
    s.press(PAD_START)
    for _ in range(600):
        s.port.deaf = generator.random() < 0.4      # the Stick hears some frames, not others
        s.c.run(1)
        if s.state == STATE_JOINING:
            break
    s.port.deaf = False
    assert s.state == STATE_JOINING
    assert s.stick.joined_password == b"x" * 40 + b"tail"


def test_a_console_reset_in_the_middle_starts_clean(setup, console):
    s = setup()
    s.scan(NETWORKS)
    s.choose(0)
    s.wait_for(STATE_KEYS)
    s.type("half a passw")
    s.press(PAD_START)
    s.c.run(2)                          # the name has gone, and a piece of the password
    assert s.state != STATE_JOINING and s.stick.joins == 0
    # Reset: the same Stick, a console that knows nothing.
    c = console()
    stick, port = s.stick, s.port
    port.console = c
    port.search_from = port.heard_at = 0.0
    port.tap.__init__()
    port.wire.__init__()
    c.joy2_level, c.joy2_quiet_until = port.wire.level, port.wire.quiet_until
    c.on_joy1, c.host, c.host_every = port.tap.write, stick.poll, 150
    again = Setup(c, stick, port)
    c.run_until(lambda: c.byte("linked"), 200)
    assert stick.hellos == 2
    again.scan(NETWORKS)
    again.choose(0)
    again.wait_for(STATE_KEYS)
    assert again.field == "_"
    again.type("whole")
    again.press(PAD_START)
    again.wait_for(STATE_JOINING)
    assert (stick.joins, stick.joined_password) == (1, b"whole")


def test_a_stick_switched_off_and_on_takes_the_console_back_to_its_hello(setup):
    s = setup()
    s.scan(NETWORKS)
    # A new Stick on the same line: it has heard no hello, and says so.
    fresh = Stick(s.port)
    s.c.host = fresh.poll
    s.press(PAD_SELECT)                 # look again: the first request it refuses
    s.wait_for(STATE_STATUS, 200)
    s.c.run_until(lambda: fresh.hellos == 1, 200)
    s.settle(80)
    assert s.value("NESP32") == "CONNECTED" and fresh.active(p.NESP_SVC_NET)


def test_the_password_is_not_asked_for_and_never_comes_back(setup):
    s = setup()
    s.scan(NETWORKS)
    s.choose(0)
    s.wait_for(STATE_KEYS)
    secret = "s3cret-Passw0rd"
    s.type(secret)
    s.press(PAD_START)
    s.wait_for(STATE_JOINING)
    joined(s.stick, b"Home Network")
    s.wait_for(STATE_STATUS)
    s.settle(100)
    for _, data in s.port.sent:
        assert secret[:5].encode() not in data
    assert secret[:5] not in s.c.screen()


# --- the link test ---------------------------------------------------------------

def test_the_link_test_counts_good_exchanges(setup):
    s = setup()
    s.stick.note_turnaround(140)
    s.stick.note_turnaround(95)
    s.menu(MENU_TEST)
    s.wait_for(STATE_TEST)
    assert s.heading == "LINK TEST"
    s.c.run(200)
    # A round of drawing takes six frames, a number a frame, from counts
    # copied as it begins: at its end the screen adds up, and partway
    # through no number is ahead of the one it is a part of.
    seen = []
    for _ in range(12):
        s.c.run(1)
        requests, good = int(s.test_value("REQUESTS")), int(s.test_value("GOOD"))
        assert requests > 180 and good <= requests
        seen.append(requests - good)
    assert seen.count(0) >= 2
    assert (s.test_value("NO REPLY"), s.test_value("WRONG")) == ("0", "0")
    assert (s.test_value("LAST"), s.test_value("SLOWEST")) == ("95 US", "140 US")
    s.press(PAD_B)
    s.wait_for(STATE_STATUS)


def test_the_link_test_tells_wrong_from_missing(setup):
    s = setup()
    s.menu(MENU_TEST)
    s.wait_for(STATE_TEST)
    generator = random.Random(11)
    seen = {"wrong": 0, "lost": 0}

    def spoil(data):
        reply = nesp.parse(data)
        roll = generator.random()
        if roll < 0.1:
            seen["lost"] += 1
            return None
        if roll < 0.2 and reply.svc == p.NESP_SVC_DIAG and len(reply.payload) > 12:
            # A Stick that sends the wrong pattern, in a good frame.
            payload = bytearray(reply.payload)
            payload[5] ^= 0x40
            seen["wrong"] += 1
            return nesp.reply_frame(reply.svc, reply.status, reply.seq, payload)
        return data

    s.port.to_console = spoil
    s.c.run(300)
    s.port.to_console = None
    s.c.run(12)
    assert seen["wrong"] > 5 and seen["lost"] > 5
    assert int(s.test_value("WRONG")) == seen["wrong"]
    # A lost reply to a request for the counters is not a trial.
    assert 0 <= seen["lost"] - int(s.test_value("NO REPLY")) <= 5
    # The numbers are drawn one a frame, so the screen is a few frames
    # behind itself; the counts it draws from add up exactly.
    sent, good, silent, wrong = (s.c.word("test_counts") if index == 0 else
                                 s.c.byte("test_counts", 2 * index)
                                 | s.c.byte("test_counts", 2 * index + 1) << 8
                                 for index in range(4))
    assert sent == good + silent + wrong and wrong == seen["wrong"]
    assert abs(int(s.test_value("REQUESTS")) - sent) <= 6


# --- the picture -----------------------------------------------------------------

# --- the menu --------------------------------------------------------------------

def test_the_status_screens_menu_is_worked_with_an_arrow(setup):
    s = setup()
    row = layout.BODY_ROW + 9
    assert [s.c.text(row + item, layout.LEFT + 2, 16).rstrip() for item in range(3)] \
        == ["WI-FI SETUP", "TEST INTERFACE", "ENABLE USB DRIVE"]

    def arrow():
        x, y, tile = s.c.sprite()
        assert x == 8 * layout.LEFT and s.tile_names()[tile] == "ARROW"
        return (y - 8 * row) // 8

    assert arrow() == 0
    s.press(PAD_UP)
    assert arrow() == 0                         # it stops at the ends
    for expected in (1, 2, 2):
        s.press(PAD_DOWN)
        assert arrow() == expected
    s.press(PAD_UP)
    assert arrow() == 1
    s.press(PAD_B)
    s.press(PAD_SELECT)
    s.c.run(10)
    assert s.state == STATE_STATUS              # only A chooses
    s.press(PAD_A)
    s.wait_for(STATE_TEST)
    s.press(PAD_B)
    s.wait_for(STATE_STATUS)
    assert arrow() == 0                         # and it is at the top again


# --- the USB drive ---------------------------------------------------------------

def test_select_lends_the_files_to_a_computer_and_says_how_that_stands(setup):
    s = setup()
    assert s.stick.drive == p.NESP_DRIVE_OFF
    s.menu(MENU_USB)
    s.wait_for(STATE_USB)
    assert s.heading == "USB DRIVE"
    s.wait_for_message("WAITING FOR A COMPUTER")
    assert s.stick.drive == p.NESP_DRIVE_WAITING
    s.stick.set_drive(p.NESP_DRIVE_MOUNTED)
    s.wait_for_message("THE USB DRIVE IS MOUNTED")
    s.stick.set_drive(p.NESP_DRIVE_EJECTED)
    s.wait_for_message("EJECTED. RESTARTING...")
    assert s.stick.drive_stops == 0


def test_b_takes_the_files_back_and_goes_back(setup):
    s = setup()
    s.menu(MENU_USB)
    s.wait_for_message("WAITING FOR A COMPUTER")
    s.stick.set_drive(p.NESP_DRIVE_MOUNTED)
    s.wait_for_message("THE USB DRIVE IS MOUNTED")
    s.press(PAD_B)
    s.wait_for(STATE_STATUS)
    assert s.stick.drive_stops == 1 and s.stick.drive == p.NESP_DRIVE_OFF
    s.settle(80)
    assert s.value("NESP32") == "CONNECTED"


def test_a_nesp32_that_has_restarted_out_of_being_a_drive_is_seen_to_have(setup):
    s = setup()
    s.menu(MENU_USB)
    s.wait_for_message("WAITING FOR A COMPUTER")
    s.stick.set_drive(p.NESP_DRIVE_OFF)         # as one is that has started again
    s.wait_for(STATE_STATUS)
    assert s.stick.drive_stops == 0


def test_a_drive_too_busy_to_answer_is_waited_for(setup):
    # While a computer writes to it the nesp32 misses requests, many in a
    # row: that is not its going away.
    s = setup()
    s.menu(MENU_USB)
    s.wait_for_message("WAITING FOR A COMPUTER")
    s.port.deaf = True
    s.c.run(400)
    assert s.state == STATE_USB and s.message == "WAITING FOR A COMPUTER"
    s.port.deaf = False
    s.stick.set_drive(p.NESP_DRIVE_MOUNTED)
    s.wait_for_message("THE USB DRIVE IS MOUNTED")
    s.stick.set_drive(p.NESP_DRIVE_OFF)         # ejected, and it has started again
    s.wait_for(STATE_STATUS)
    s.settle(200)
    assert s.value("NESP32") == "CONNECTED"


def test_a_board_that_cannot_be_a_drive_says_so(setup):
    s = setup()
    s.stick.set_drive(p.NESP_DRIVE_NONE)
    s.menu(MENU_USB)
    s.wait_for_message("THIS BOARD CANNOT BE A DRIVE")
    s.c.run(100)
    assert s.state == STATE_USB
    s.press(PAD_B)
    s.wait_for(STATE_STATUS)
    assert s.stick.drive_stops == 0


def test_the_nmi_is_over_well_inside_the_vblank(setup):
    s = setup()
    s.scan(NETWORKS)
    s.choose(0)
    s.wait_for(STATE_KEYS)
    s.type("abc")
    s.menu(MENU_USB)
    s.settle(20)
    s.press(PAD_START)
    s.wait_for(STATE_JOINING)
    frames = s.c.frames
    assert max(frame.last_write for frame in frames) < VBLANK_CYCLES - 500
    assert max(frame.nmi_cycles for frame in frames) < VBLANK_CYCLES


def test_one_controller_read_a_frame_reaches_the_stick_as_one_byte_of_noise(setup):
    s = setup()
    s.settle(20)
    noise, frames = s.stick.noise, len(s.c.frames)
    s.settle(100)
    assert s.stick.noise - noise == len(s.c.frames) - frames
