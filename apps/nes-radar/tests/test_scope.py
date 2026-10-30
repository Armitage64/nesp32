"""The link ROM against nesp32's own RADAR, over the simulated line: from
the editor to an airport's aircraft on the scope, and what becomes of it
when replies are lost, the nesp32 is switched off, or adsb.fi fails."""

import nesp_proto as p
import pytest
from scope import PAD_A, PAD_B, PAD_DOWN, PAD_SELECT, PAD_START, PAD_UP, PLACES, plane, reply_frame

RADAR = p.NESP_SVC_RADAR
POLL_FRAMES = p.NESP_RADAR_POLL_MS * 60 // 1000 + 30


def test_from_the_editor_to_an_airports_aircraft(scope):
    s = scope()
    s.open("KSBA")
    assert s.stick.app == (b"RADR", 1) and s.stick.active(RADAR)
    assert "/lat/34.426200/lon/-119.840400/dist/10" in s.stick.fetch_url
    assert s.count == 0 and s.targets() == []
    s.land([plane(0.05, 0.0, flight="FAR", t="A320"), plane(0.0, 0.02, flight="NEAR", t="C172")])
    assert s.live and s.count == 2 and s.airport == "KSBA"
    assert s.row(0) == ("NEAR", "C172") and s.row(1) == ("FAR", "A320")
    assert s.calls()[2:] == [""] * 6
    assert s.selected == 1
    near, far = s.targets()
    assert near[0] > far[0] and far[1] < near[1]       # one to the east, one to the north
    assert s.c.late_writes == [] and s.c.heard_in_nmi == 0


def test_the_scope_follows_each_fetch(scope):
    s = scope()
    s.open()
    s.land([plane(0.02, 0.0, flight="ONE")])
    first = s.targets()
    names = s.asked(p.NESP_RADAR_IDENTITY)
    assert names == 8 and s.count == 1
    # The same aircraft somewhere else: a new scene, and no names asked for.
    s.land([plane(0.06, 0.0, flight="ONE")], frames=POLL_FRAMES)
    assert s.targets() != first and s.targets()[0][1] < first[0][1]
    assert s.asked(p.NESP_RADAR_IDENTITY) == names
    # Another aircraft: its names first, and then the scene.
    s.land([plane(0.06, 0.0, flight="ONE"), plane(0.01, 0.0, flight="TWO")], frames=POLL_FRAMES)
    assert s.asked(p.NESP_RADAR_IDENTITY) == names + 8
    assert s.calls()[:2] == ["TWO", "ONE"] and s.count == 2 and s.live
    s.land([], frames=POLL_FRAMES)
    assert s.count == 0 and s.targets() == [] and s.calls() == [""] * 8
    assert s.c.late_writes == [] and s.c.heard_in_nmi == 0


def test_eight_aircraft_and_the_pad_chooses_among_them(scope):
    s = scope()
    s.open()
    s.land([plane(0.01 * (number + 1), 0.0, flight="N%d" % number, t="T%d" % number)
            for number in range(10)])
    assert s.count == 8 and len(s.targets()) == 8
    assert s.calls() == ["N%d" % number for number in range(8)]
    assert s.selected == 1
    s.c.press(PAD_DOWN, release=4)
    assert s.selected == 2
    s.c.press(PAD_UP, release=4)
    s.c.press(PAD_UP, release=4)
    assert s.selected == 8
    assert s.c.late_writes == []


def test_the_targets_take_turns_in_front(scope):
    s = scope()
    s.open()
    s.land([plane(0.01 * (number + 1), 0.0) for number in range(6)])
    seen = set()
    dmas = s.c.dmas
    for _ in range(16):
        s.c.run(1)
        seen.add(bytes(s.c.oam[:64]))
    assert len(seen) > 1                       # the order in OAM goes round
    assert s.c.dmas - dmas >= 14               # and a frame is seldom missed


def test_an_airport_nobody_has_heard_of(scope):
    s = scope()
    s.start("KZZZ")
    s.locate("KZZZ", found=False)
    s.c.run_until(lambda: s.message == "INVALID AIRPORT", 200)
    assert s.stick.fetches == 1
    # And then one there is.
    s.choose("KLAX")
    assert s.message == ""
    s.c.press(PAD_START)
    s.locate("KLAX")
    s.c.run_until(lambda: "adsb.fi" in s.stick.fetch_url, 200)
    s.c.run(30)
    assert s.airport == "KLAX" and "/lat/33.942501/" in s.stick.fetch_url


def test_the_editor_waits_while_the_nesp32_asks_where_the_airport_is(scope):
    s = scope()
    s.start()
    s.c.run_until(lambda: s.stick.fetching, 200)
    s.c.run(400)                                # longer than it waits for a nesp32
    assert s.message == "REQUESTING"
    s.locate("KSBA")
    s.land([plane(0.02, 0.0, flight="FOUND")])
    assert s.calls()[0] == "FOUND"


def test_an_asking_that_fails(scope):
    s = scope()
    s.start()
    s.c.run_until(lambda: s.stick.fetching, 200)
    s.stick.fetch_done(False, b"no route")
    s.c.run_until(lambda: s.message == "LOOKUP FAILED", 200)
    s.c.press(PAD_START)                        # the same letters once more
    s.locate("KSBA")
    s.land([plane(0.02, 0.0, flight="FOUND")])
    assert s.calls()[0] == "FOUND" and s.live


def test_with_no_nesp32_the_editor_says_so(scope):
    s = scope(stick=False)
    s.start()
    s.c.run(10)
    assert s.message == "REQUESTING"
    s.c.run_until(lambda: s.message == "NO NESP32 ANSWER", 300)
    s.c.press(PAD_UP)
    assert s.message == "" and s.code == "LSBA"


def test_a_nesp32_with_no_wifi(scope):
    s = scope(online=False)
    s.start()
    s.c.run_until(lambda: s.message == "NESP32 NO WI-FI", 200)
    # Start again, with the letters as they are and the message still up.
    s.stick.set_wifi(p.NESP_WIFI_JOINED, address=(10, 0, 0, 2))
    s.c.press(PAD_START)
    s.locate("KSBA")
    s.land([plane(0.02, 0.0, flight="ONLINE")])
    assert s.calls()[0] == "ONLINE" and s.live


def test_a_nesp32_whose_firmware_has_no_radar(scope):
    def older(data):
        if data[1] == p.NESP_SVC_SYS:           # the hello's reply: one service missing
            payload = bytes((p.NESP_PROTOCOL, 0, 1, 0, p.NESP_BOARD_S3, 127, 1, RADAR))
            return reply_frame(p.NESP_SVC_SYS, p.NESP_ST_NO_SERVICE, data[3], payload)
        return data
    s = scope(to_console=older)
    s.start()
    s.c.run_until(lambda: s.message == "UPDATE NESP32", 200)


def test_a_nesp32_whose_firmware_has_no_kbd_is_used_all_the_same(scope):
    def older(data):
        if data[1] == p.NESP_SVC_SYS:           # the hello's reply: KBD missing
            payload = bytes((p.NESP_PROTOCOL, 0, 1, 0, p.NESP_BOARD_S3, 127, 1, p.NESP_SVC_KBD))
            return reply_frame(p.NESP_SVC_SYS, p.NESP_ST_NO_SERVICE, data[3], payload)
        return data
    s = scope(to_console=older)
    s.open("KSBA")
    s.land([plane(0.02, 0.0, flight="SBA")])
    assert s.airport == "KSBA" and s.calls()[0] == "SBA"


def test_select_does_nothing_on_the_scope_of_a_rom_on_no_cartridge(scope):
    s = scope()
    s.open("KSBA")
    s.land([plane(0.02, 0.0, flight="SBA")])
    s.c.press(PAD_SELECT, release=10)
    s.c.run(30)
    assert s.airport == "KSBA" and s.calls()[0] == "SBA"


def test_b_is_the_editor_again_and_a_looks_up_another_airport(scope):
    s = scope()
    s.open("KSBA")
    s.land([plane(0.02, 0.0, flight="SBA")])
    s.c.press(PAD_B, release=10)
    assert s.message == ""
    s.c.press(PAD_B)                    # and again does nothing: there is no step back
    s.choose("KLAX")
    s.c.press(PAD_A)
    s.locate("KLAX")
    s.c.run(30)
    assert s.airport == "KLAX" and s.link == "WAITING" and s.count == 0 and s.calls() == [""] * 8
    s.land([plane(0.02, 0.0, PLACES["KLAX"], flight="LAX")])
    assert s.calls()[0] == "LAX" and s.live
    assert s.c.late_writes == [] and s.c.heard_in_nmi == 0


def test_replies_lost_now_and_then_cost_nothing_but_time(scope):
    count = [0]

    def lossy(data):
        count[0] += 1
        return None if count[0] % 3 == 0 else data
    s = scope(to_console=lossy)
    s.open()
    s.land([plane(0.01 * (number + 1), 0.0, flight="N%d" % number) for number in range(8)],
           frames=240)
    assert s.calls() == ["N%d" % number for number in range(8)] and s.live
    s.land([plane(0.03, 0.0, flight="LAST")], frames=POLL_FRAMES + 120)
    assert s.calls() == ["LAST"] + [""] * 7 and s.count == 1 and s.live


def test_damaged_replies_are_not_shown(scope):
    count = [0]

    def damaged(data):
        count[0] += 1
        if count[0] % 2:
            return data
        worse = bytearray(data)
        worse[len(worse) // 2] ^= 0x10
        return bytes(worse)
    s = scope(to_console=damaged)
    s.open()
    s.land([plane(0.02, 0.0, flight="GOOD", t="B738")], frames=240)
    assert s.row(0) == ("GOOD", "B738") and s.count == 1 and s.live


def test_the_dots_after_live_are_data_coming_in(scope):
    s = scope()
    s.open()
    s.land([plane(0.02, 0.0, flight="ONE")], frames=0)
    s.c.run_until(lambda: s.link == "LIVE.", 60)
    seen = ["LIVE."]
    for _ in range(120):
        s.c.run(1)
        if seen[-1] != s.link:
            seen.append(s.link)
    assert seen == ["LIVE.", "LIVE..", "LIVE...", "LIVE"]
    # The next fetch's aircraft, and only then the dots again.
    s.land([plane(0.03, 0.0, flight="ONE")], frames=0)
    s.c.run_until(lambda: s.link == "LIVE.", POLL_FRAMES)
    s.c.run(60)
    assert s.link == "LIVE"
    assert s.c.late_writes == [] and s.c.heard_in_nmi == 0


def test_a_nesp32_that_stops_answering_and_starts_again(scope):
    quiet = [False]
    s = scope(to_console=lambda data: None if quiet[0] else data)
    s.open()
    s.land([plane(0.02, 0.0, flight="HERE")])
    quiet[0] = True
    s.c.run_until(lambda: s.link == "NO ANSWER", 400)
    assert s.calls()[0] == "HERE" and s.count == 1      # the last scene stays
    quiet[0] = False
    s.c.run_until(lambda: s.live, 120)
    assert s.calls()[0] == "HERE"


def test_a_nesp32_switched_off_and_on_is_told_the_airport_again(scope):
    s = scope()
    s.open()
    s.land([plane(0.02, 0.0, flight="BEFORE")])
    hellos, fetches = s.stick.hellos, s.stick.fetches
    assert s.stick.hello(app=b"NONE", services=[]).ok   # as one that has just started
    assert not s.stick.active(RADAR)
    s.c.run_until(lambda: s.stick.fetches > fetches, 200)
    assert s.stick.hellos == hellos + 2 and s.stick.app == (b"RADR", 1)
    assert "adsb.fi" in s.stick.fetch_url       # where the airport is, it had kept
    s.land([plane(0.02, 0.0, flight="AFTER")])
    assert s.calls()[0] == "AFTER" and s.live and s.airport == "KSBA"


def test_a_fetch_that_fails_and_a_scene_gone_stale(scope):
    s = scope()
    s.open()
    s.land([plane(0.02, 0.0, flight="KEPT")])
    s.fail(frames=POLL_FRAMES)
    assert s.link == "ADSB DOWN" and s.calls()[0] == "KEPT" and s.count == 1
    s.land([plane(0.02, 0.0, flight="KEPT")], frames=POLL_FRAMES)
    assert s.live
    for _ in range(5):
        s.fail(frames=POLL_FRAMES)
    assert s.link == "ADSB DOWN" and s.calls()[0] == "KEPT"
    assert s.c.late_writes == []


def test_with_no_aircraft_to_be_had_the_scope_waits(scope):
    s = scope()
    s.open()
    s.c.run(700)                                # the fetch never ends
    assert s.link == "WAITING" and s.count == 0
    s.fail()
    assert s.link == "ADSB DOWN"                    # nothing good ever came: stale, and down


@pytest.mark.parametrize("turnaround_ms", [0.05, 1.0, 4.0])
def test_however_long_the_nesp32_takes_to_answer(scope, turnaround_ms):
    from wire import ms
    s = scope(turnaround=ms(turnaround_ms))
    s.open()
    s.land([plane(0.01 * (number + 1), 0.0, flight="N%d" % number) for number in range(8)])
    assert s.calls() == ["N%d" % number for number in range(8)] and s.live
    assert s.c.late_writes == [] and s.c.heard_in_nmi == 0


@pytest.mark.parametrize("clock_error", [-0.02, 0.02])
def test_with_the_nesp32s_clock_out(scope, clock_error):
    s = scope(clock_error=clock_error)
    s.open()
    s.land([plane(0.01 * (number + 1), 0.0, flight="N%d" % number) for number in range(8)])
    assert s.calls() == ["N%d" % number for number in range(8)] and s.live


def test_the_editor_begins_at_the_airport_the_nesp32_kept(scope):
    s = scope(kept="EGLL")
    s.past_splash()
    assert s.code == "EGLL" and s.stick.app == (b"RADR", 1)
    s.c.press(PAD_START)                        # and where it is, the nesp32 kept too
    s.c.run_until(lambda: s.stick.fetching, 200)
    assert s.stick.fetches == 1 and "/lat/51.470600/lon/-0.461941/" in s.stick.fetch_url
    s.land([plane(0.02, 0.0, PLACES["EGLL"], flight="LHR")])
    assert s.airport == "EGLL" and s.calls()[0] == "LHR" and s.live


def test_an_airport_found_is_where_the_editor_begins_next_time(scope, build):
    s = scope()
    s.past_splash()
    assert s.code == "KSBA"                     # nothing kept: nes-radar's own
    s.choose("KLAX")
    s.c.press(PAD_START)
    s.locate("KLAX")
    s.land([plane(0.02, 0.0, PLACES["KLAX"])])
    assert s.stick.airport == (b"KLAX", 33942501, -118407997)
    s.c.reset()                                 # the console's reset button
    s.past_splash()
    assert s.code == "KLAX"
    assert s.c.late_writes == [] and s.c.heard_in_nmi == 0


def test_with_no_nesp32_the_editor_is_hardly_later(scope):
    s = scope(stick=False)
    s.c.run(150)
    assert s.code == "KSBA" and s.message == ""
    s.c.press(PAD_UP)
    assert s.code == "LSBA"


def test_the_airport_kept_comes_through_lost_replies(scope):
    count = [0]

    def lossy(data):
        count[0] += 1
        return None if count[0] % 2 else data
    s = scope(kept="KLAX", to_console=lossy)
    s.past_splash()
    assert s.code == "KLAX"



def test_the_bluetooth_keyboard_is_the_controller_in_the_editor_and_on_the_scope(scope):
    """The arrows are the D-pad and Enter is A, which looks the airport up.
    Escape on the scope is B: the editor again."""
    s = scope()
    s.past_splash()
    s.choose("KSBB")
    s.stick.kbd_type(bytes((p.NESP_KEY_LEFT, p.NESP_KEY_DOWN)))    # the last letter, one down
    s.c.run_until(lambda: s.code == "KSBA", 60)
    s.stick.kbd_type(bytes((p.NESP_KEY_ENTER,)))
    s.locate("KSBA")
    s.c.run_until(lambda: s.link == "WAITING" and s.airport == "KSBA", 200)
    s.land([plane(0.02, 0.0, flight="SBA")])
    s.stick.kbd_type(bytes((p.NESP_KEY_ESCAPE,)))
    s.c.run_until(lambda: s.stick.kbd_unread == 0, 60)
    s.c.run(20)
    s.choose("KLAX")                    # the editor's
    s.c.press(PAD_A)
    s.locate("KLAX")


def test_an_airport_typed_on_the_bluetooth_keyboard_goes_in_the_editor(scope):
    """Letters in either case go where the cursor is, which moves on, and
    Backspace is Left: Enter then looks it up."""
    s = scope()
    s.past_splash()
    s.stick.kbd_type(b"klxx" + bytes((p.NESP_KEY_BACKSPACE, p.NESP_KEY_BACKSPACE)) + b"A")
    s.c.run_until(lambda: s.code == "KLAX" and s.stick.kbd_unread == 0, 120)
    s.c.run(20)
    assert s.code == "KLAX"
    s.stick.kbd_type(bytes((p.NESP_KEY_ENTER,)))
    s.locate("KLAX")
