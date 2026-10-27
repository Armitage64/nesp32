"""The Weather ROM against nesp32's firmware, on a simulated console."""

import gen_screen as layout
import nesp
import nesp_proto as p
import pytest
from forecast import (KEPT, NOT_FOUND, PAD_A, PAD_B, PAD_DOWN, PAD_LEFT, PAD_RIGHT, PAD_SELECT,
                      PAD_START, PAD_UP, VIEW_REPORT)

WEATHER = p.NESP_SVC_WEATHER
COLUMNS = p.NESP_WEATHER_COLUMNS
DEGREE = chr(p.NESP_WEATHER_DEGREE)
SUN, CLOUD = (layout.picture_rows(which) for which in (p.NESP_PICTURE_SUN,
                                                       p.NESP_PICTURE_CLOUD))
# What the nesp32 makes of the two sites' answers for 90210 (nesp32's
# tests/test_weather.py holds its service to the same rows).
REPORT = [line.ljust(COLUMNS) for line in (
    "BEVERLY HILLS, CA      90210",
    "",
    SUN[0] + "  72" + DEGREE + "F  CLEAR",
    SUN[1] + "  HIGH 74" + DEGREE + "  LOW 55" + DEGREE,
    "    HUMIDITY 43%",
    "    WIND 9 MPH",
    "",
    "",
    " TUE   WED   THU   FRI   SAT",
    " " + "    ".join((CLOUD[0], SUN[0], SUN[0], SUN[0], SUN[0])),
    " " + "    ".join((CLOUD[1], SUN[1], SUN[1], SUN[1], SUN[1])),
    " 74    81    86    91    90",
    " 55    61    66    74    76",
)]
# And as the ROM draws them: the days' names in its own tiles.
SHOWN = layout.on_screen(REPORT)


def test_the_layout_is_the_nesp32s():
    assert (layout.ROWS, layout.COLUMNS) == (p.NESP_WEATHER_ROWS, p.NESP_WEATHER_COLUMNS)
    assert (layout.PICTURE, layout.DEGREE) == (p.NESP_WEATHER_PICTURE, p.NESP_WEATHER_DEGREE)
    assert layout.ZIP_LEN == p.NESP_WEATHER_ZIP_LEN
    names = [name for name, _ in layout.PICTURES]
    assert names == [name[len("NESP_PICTURE_"):] for name in sorted(
        (name for name in dir(p) if name.startswith("NESP_PICTURE_")),
        key=lambda name: getattr(p, name))]
    assert len(layout.sample_report()) == layout.ROWS


def test_every_picture_has_tiles_of_its_own_and_the_font_keeps_its_capitals():
    screen = layout.build_screen()
    data = screen.chr()
    tiles = [data[16 * number:16 * number + 16] for number in range(256)]
    pictures = tiles[layout.PICTURE:layout.PICTURE + 4 * len(layout.PICTURES)]
    assert len(layout.PICTURES) == 8 and layout.PICTURE + len(pictures) == 0x80
    for which in range(len(layout.PICTURES)):
        assert any(any(tile) for tile in pictures[4 * which:4 * which + 4])
    assert len({bytes(pictures[4 * which:4 * which + 4][0] + pictures[4 * which + 1]
                      + pictures[4 * which + 2] + pictures[4 * which + 3])
                for which in range(len(layout.PICTURES))}) == len(layout.PICTURES)
    plain = layout.gen_ui.Screen().chr()
    assert data[16 * 0x20:16 * 0x60] == plain[16 * 0x20:16 * 0x60]
    assert any(tiles[layout.DEGREE])


def test_with_no_nesp32_it_says_so(sky):
    s = sky(attached=False)
    s.c.run(40)
    assert s.status == "WAITING FOR LINK"
    credit = layout.build_screen().nametable()[32 * layout.CREDIT_ROW:][:32]
    assert s.c.tiles(layout.CREDIT_ROW, 0, 32) == credit and len(set(credit)) > 10
    assert all(row.strip() == "" for row in s.rows()) and s.foot == ""
    s.c.press(PAD_A)                # and no button does anything
    s.c.press(PAD_UP)
    s.c.run(20)
    assert all(row.strip() == "" for row in s.rows())
    s.writes_were_in_time()


def test_the_header_is_nesp32s_with_what_this_is(sky):
    s = sky(attached=False)
    s.c.run(5)
    from gen_ui import LOGO_LAST_ROW, Screen, header
    screen = Screen()
    screen.names[:] = b" " * len(screen.names)
    header(screen, "WEATHER")
    width = 32 * (LOGO_LAST_ROW + 1)
    theirs, ours = screen.nametable(), layout.build_screen().nametable()
    assert bytes(s.c.vram[0x2000:0x2000 + width]) == ours[:width]
    # The same tiles in the same places as any ROM with that header: only
    # the tiles' numbers are this ROM's to choose.
    assert [tile == 0x20 for tile in ours[:width]] == [tile == 0x20 for tile in theirs[:width]]
    assert bytes(s.c.vram[0x23C0:0x2400]) == ours[960:]


def test_with_nothing_kept_the_form_comes_up_and_a_zip_code_is_entered(sky):
    s = sky()
    assert s.form_is_up() == "00000" and s.lit == 0 and s.status == ""
    assert s.asked(p.NESP_WEATHER_LAST) == [b""]
    assert s.asked(p.NESP_WEATHER_ZIP) == []        # the form asks nothing
    s.enter("90210")
    s.press(PAD_A)
    assert s.report_is_up() == SHOWN
    assert s.stick.zip == KEPT and s.stick.zip_keeps == 1
    assert s.asked(p.NESP_WEATHER_ZIP)[0] == b"\x0190210"
    assert [url.split("?")[0] for url in s.served] == [
        "https://api.zippopotam.us/us/90210", "https://api.open-meteo.com/v1/forecast"]
    assert s.stick.shown(0) == "90210: 72F"
    s.writes_were_in_time()


def test_the_status_line_says_how_it_stands_on_the_way(sky):
    s = sky()
    s.form_is_up()
    s.enter("90210")
    s.c.press(PAD_START)            # Start asks too; and the sites take their time
    s.c.run_until(lambda: s.stick.fetching, 60)
    s.c.run(10)
    assert s.status == "FINDING THE ZIP CODE"
    assert s.view == VIEW_REPORT and s.lit is None and s.digits == "90210"
    s.serve()
    s.c.run_until(lambda: s.stick.fetching, 60)
    s.c.run(10)
    assert s.status == "FETCHING THE WEATHER"
    s.c.press(PAD_UP)               # the form is on the screen still, and cannot be changed
    assert s.digits == "90210"
    s.serve()
    assert s.report_is_up() == SHOWN


def test_a_zip_code_the_nesp32_keeps_is_in_the_form_and_a_is_all_it_takes(sky):
    s = sky(kept=KEPT)
    assert s.form_is_up() == "90210" and s.lit == 0 and s.status == ""
    assert s.asked(p.NESP_WEATHER_LAST) == [b""]
    s.run(120)                      # and there it waits: nothing is asked or fetched
    assert s.asked(p.NESP_WEATHER_ZIP) == [] and s.served == []
    assert s.view != VIEW_REPORT
    s.press(PAD_A)
    assert s.report_is_up() == SHOWN
    assert all("zippopotam" not in url for url in s.served) and len(s.served) == 1
    assert s.stick.zip_keeps == 0
    s.writes_were_in_time()


def test_b_in_the_form_does_nothing_on_no_cartridge(sky):
    s = sky(kept=KEPT)
    assert s.form_is_up() == "90210" and s.c.byte("on_cart") == 0
    assert s.foot == layout.FOOT_FORM   # and says nothing of it
    s.press(PAD_B)
    s.run(30)
    assert s.form_is_up() == "90210" and s.asked(p.NESP_WEATHER_ZIP) == []
    s.go()
    s.report_is_up()
    s.press(PAD_B)
    s.form_is_up()
    s.press(PAD_B)                  # nor once a report has been asked for
    s.run(30)
    assert s.form_is_up() == "90210" and s.view != VIEW_REPORT


def test_select_does_nothing_on_no_cartridge(sky):
    s = sky(kept=KEPT)
    assert s.form_is_up() == "90210" and s.c.byte("on_cart") == 0
    s.press(PAD_SELECT)
    s.run(30)
    assert s.form_is_up() == "90210" and s.asked(p.NESP_WEATHER_ZIP) == []
    s.go()
    s.report_is_up()
    s.press(PAD_SELECT)
    s.run(30)
    assert s.view == VIEW_REPORT


def test_the_days_names_are_centered_over_their_pictures(sky):
    screen = layout.build_screen()
    data = screen.chr()
    days = REPORT[layout.DAY_ROW]
    assert SHOWN[:layout.DAY_ROW] + SHOWN[layout.DAY_ROW + 1:] == \
        REPORT[:layout.DAY_ROW] + REPORT[layout.DAY_ROW + 1:]
    for column in layout.DAY_COLUMNS:
        name = days[column:column + 3]
        assert days[column - 1] == " " and SHOWN[layout.DAY_ROW][column + 3:column + 4] in " "
        tiles = SHOWN[layout.DAY_ROW][column - 1:column - 1 + layout.DAY_TILES]
        # The font's tiles of the name, put side by side and moved half a
        # tile to the left: the same pixels.
        shown = [[0] * 32 for _ in range(8)]
        for index, char in enumerate(name):
            for y, row in enumerate(layout.gen_ui.font_tile(char)):
                for x, color in enumerate(row):
                    shown[y][8 + 8 * index + x - 4] = color
        assert b"".join(data[16 * ord(tile):][:16] for tile in tiles) == b"".join(
            layout.gen_ui.tile_bytes(tile) for tile in layout.gen_ui.cut_tiles(shown)[0])
        assert all(ord(tile) > 0x7F for tile in tiles)  # none of the font's or the pictures'
    assert len(screen.days) == 7 and screen.next_tile <= 0x100
    s = sky(kept=KEPT)
    s.go()
    assert s.report_is_up()[layout.DAY_ROW] == SHOWN[layout.DAY_ROW]


def test_the_lit_digit_pulses_and_nothing_does_on_the_report(sky):
    s = sky(kept=KEPT)
    s.form_is_up()
    seen = []
    for _ in range(8 * len(layout.PULSE) + 8):
        s.run(1)
        if not seen or seen[-1] != s.pulse:
            seen.append(s.pulse)
    assert set(seen) == set(layout.PULSE) and len(seen) >= len(layout.PULSE)
    start = seen.index(layout.PULSE[0])
    assert seen[start:start + 3] == list(layout.PULSE[:3]) or len(seen) - start < 3
    s.press(PAD_RIGHT)
    assert s.form_is_up() == "90210" and s.lit == 1    # the next one's square, and only it
    s.press(PAD_A)
    s.report_is_up()                # where no square has that palette
    still = s.pulse
    s.run(40)
    assert s.pulse == still
    s.writes_were_in_time()


def test_a_zip_code_entered_is_there_the_next_time_the_program_is_started(sky):
    s = sky()
    s.form_is_up()
    s.enter("90210")
    s.press(PAD_A)
    s.report_is_up()
    s.c.reset()                     # the console's reset button
    s.run(3)
    assert s.c.byte("serial_have") == 0
    assert s.form_is_up() == "90210"    # the form, with the digits in it
    s.press(PAD_A)
    assert s.report_is_up() == SHOWN
    assert len(s.served) == 3 and "open-meteo" in s.served[2]
    kept = s.stick.zip
    again = sky(kept=kept)          # and its power, and the nesp32's
    assert again.form_is_up() == "90210"
    again.press(PAD_START)
    assert again.report_is_up() == SHOWN


def test_the_digits_go_round_and_so_does_the_mark(sky):
    s = sky()
    s.form_is_up()
    s.press(PAD_DOWN)
    assert s.form_is_up() == "90000"
    s.press(PAD_UP)
    s.press(PAD_UP)
    assert s.form_is_up() == "10000"
    s.press(PAD_LEFT)
    assert s.form_is_up() == "10000" and s.lit == 4
    s.press(PAD_UP)
    s.press(PAD_RIGHT)
    assert s.form_is_up() == "10001" and s.lit == 0
    for place in (1, 2, 3, 4, 0):
        s.press(PAD_RIGHT)
        s.form_is_up()
        assert s.lit == place
    s.press(PAD_UP | PAD_RIGHT)     # both at once: the mark moves, and its digit changes
    assert s.form_is_up() == "11001" and s.lit == 1


def test_a_direction_held_down_counts_again_and_again(sky):
    s = sky()
    s.form_is_up()
    s.run(15, pad=PAD_UP)
    assert s.digits == "10000"      # not at once
    s.run(30, pad=PAD_UP)           # then after 20 frames, and every 5 from there
    held = int(s.form_is_up()[0])
    assert 5 <= held <= 7
    s.run(1, pad=0)
    s.run(40)
    assert int(s.form_is_up()[0]) == held


def test_a_zip_code_there_is_none_of_goes_back_to_the_form(sky):
    s = sky(where=NOT_FOUND)
    s.form_is_up()
    s.enter("00001")
    s.press(PAD_A)
    s.run_until(lambda: s.status == "NO SUCH ZIP CODE")
    assert s.form_is_up() == "00001"
    assert s.stick.zip is None
    asked = len(s.asked(p.NESP_WEATHER_ZIP))
    s.run(120)
    assert len(s.asked(p.NESP_WEATHER_ZIP)) == asked    # and waits there, asking nothing
    assert s.status == "NO SUCH ZIP CODE"


def test_a_zip_code_put_right_after_one_there_is_none_of(sky, where):
    s = sky(where=NOT_FOUND)
    s.form_is_up()
    s.enter("90211")
    s.press(PAD_A)
    s.run_until(lambda: s.status == "NO SUCH ZIP CODE")
    s.form_is_up()
    s.where = where
    s.enter("90210")
    s.press(PAD_A)
    assert s.report_is_up() == SHOWN
    ids = [payload[0] for payload in s.asked(p.NESP_WEATHER_ZIP)]
    assert sorted(set(ids)) == [1, 2]                   # each asking has an id of its own


@pytest.mark.parametrize("which", ["where", "weather"])
def test_a_site_that_fails_says_why_and_goes_back_to_the_form(sky, which, where, weather):
    s = sky(**{which: (False, b"THE SITE SAID 503")})
    s.form_is_up()
    s.enter("90210")
    s.press(PAD_A)
    s.run_until(lambda: s.status == "THE SITE SAID 503")
    assert s.form_is_up() == "90210"
    s.where, s.weather = where, weather
    s.press(PAD_A)                  # the same again, once the site is back
    assert s.report_is_up() == SHOWN
    s.writes_were_in_time()


def test_words_as_long_as_the_line_and_then_shorter_ones(sky):
    long = b"THE NESP32 HAS RUN OUT OF IT"
    assert len(long) == layout.STATUS_WIDTH
    s = sky(where=(False, long))
    s.form_is_up()
    s.press(PAD_A)
    s.run_until(lambda: s.status == long.decode())
    s.form_is_up()
    s.where = (False, b"NO")
    s.press(PAD_A)
    s.run_until(lambda: s.status == "NO")
    assert s.c.text(layout.STATUS_ROW, layout.STATUS_COLUMN, layout.STATUS_WIDTH) == \
        "NO".center(layout.STATUS_WIDTH)


def test_with_no_network_it_says_so_and_goes_on_when_there_is_one(sky):
    s = sky(wifi=p.NESP_WIFI_IDLE, kept=KEPT)
    s.go()
    s.run_until(lambda: s.status == "NO WI-FI")
    s.run(60)
    assert s.served == [] and s.view == VIEW_REPORT
    s.stick.set_wifi(p.NESP_WIFI_JOINED, address=(10, 0, 0, 2))
    assert s.report_is_up() == SHOWN


def test_b_on_the_report_is_the_form(sky):
    s = sky(kept=KEPT)
    s.go()
    s.report_is_up()
    s.press(PAD_A)                  # which are no buttons of the report's
    s.press(PAD_START)
    s.run(20)
    assert s.view == VIEW_REPORT and s.rows() == SHOWN
    s.press(PAD_B)
    assert s.form_is_up() == "90210" and s.lit == 0


def test_another_zip_code_takes_the_place_of_the_report(sky, where, weather):
    s = sky(kept=KEPT)
    s.go()
    s.report_is_up()
    s.press(PAD_B)
    s.form_is_up()
    s.where = where.replace(b"Beverly Hills", b"New York").replace(b'"CA"', b'"NY"')
    s.weather = weather.replace(b'"temperature_2m":72.0', b'"temperature_2m":-3.6')
    assert s.where != where and s.weather != weather
    s.enter("10001")
    s.press(PAD_A)
    rows = s.report_is_up()
    assert rows[0] == "NEW YORK, NY           10001"
    assert rows[2] == (SUN[0] + "  -4" + DEGREE + "F  CLEAR").ljust(COLUMNS)
    assert rows[3:] == SHOWN[3:]
    assert s.stick.zip[0] == b"10001"


def test_a_newer_report_is_drawn_when_the_nesp32_has_one(sky, weather):
    s = sky(kept=KEPT)
    s.go()
    s.report_is_up()
    first = s.c.byte("serial_have")
    s.weather = weather.replace(b'"temperature_2m":72.0', b'"temperature_2m":64.4')
    s.later(p.NESP_WEATHER_POLL_MS)
    s.run_until(lambda: len(s.served) == 2, 300)
    s.run_until(lambda: s.c.byte("serial_have") != first, 300)
    rows = s.report_is_up()
    assert rows[2] == (SUN[0] + "  64" + DEGREE + "F  CLEAR").ljust(COLUMNS)
    assert rows[:2] + rows[3:] == SHOWN[:2] + SHOWN[3:]
    s.writes_were_in_time()


def test_a_report_on_the_screen_is_asked_after_about_once_a_second(sky):
    s = sky(kept=KEPT)
    s.go()
    s.report_is_up()
    before = len(s.asked(p.NESP_WEATHER_ZIP))
    s.run(640)
    assert 8 <= len(s.asked(p.NESP_WEATHER_ZIP)) - before <= 11
    assert not any(service == WEATHER and op != p.NESP_WEATHER_ZIP
                   for service, op, _ in s.requests()[-300:])      # and nothing else of it
    assert s.rows() == SHOWN


def test_a_nesp32_switched_off_and_on_is_greeted_and_asked_again(sky):
    s = sky(kept=KEPT)
    s.go()
    s.report_is_up()
    s.port.deaf = True              # off
    s.run_until(lambda: s.status == "WAITING FOR LINK", 1200)
    assert s.rows() == SHOWN       # what was on the screen stays
    s.plug_in(kept=KEPT)            # and on: a new one
    s.run_until(lambda: s.stick.hellos == 1, 1200)
    assert s.report_is_up(1200) == SHOWN
    assert s.stick.hellos == 1 and len(s.served) == 2


def test_a_nesp32_without_the_service_is_told_to_be_updated(sky):
    def older(data):
        reply = nesp.parse(data)
        if reply.svc == p.NESP_SVC_SYS and len(reply.payload) == 7:    # a hello's
            return nesp.reply_frame(reply.svc, p.NESP_ST_NO_SERVICE, reply.seq,
                                    reply.payload[:6] + bytes((1, WEATHER)))
        return data

    s = sky(to_console=older)
    s.run_until(lambda: s.status == "UPDATE NESP32")
    s.run(60)
    assert s.asked(p.NESP_WEATHER_LAST) == [] and all(row.strip() == "" for row in s.rows())


# --- a Bluetooth keyboard on the nesp32 ---------------------------------------------

ENTER, ESCAPE, BACKSPACE = (bytes((key,)) for key in (p.NESP_KEY_ENTER, p.NESP_KEY_ESCAPE,
                                                      p.NESP_KEY_BACKSPACE))
LEFT, RIGHT, UP, DOWN = (bytes((key,)) for key in (p.NESP_KEY_LEFT, p.NESP_KEY_RIGHT,
                                                   p.NESP_KEY_UP, p.NESP_KEY_DOWN))


def typed(s, keys):
    """Keys typed on the nesp32's keyboard, and the ROM has had them."""
    s.stick.kbd_type(keys)
    s.run_until(lambda: s.stick.kbd_unread == 0, 60)
    s.run(4)


def test_a_zip_code_typed_on_a_keyboard_is_asked_for_with_enter(sky):
    s = sky()
    s.form_is_up()
    assert s.stick.kbd_on                           # the hello asked for KBD
    typed(s, b"90a2-1")                             # what is no digit is no key of the form's
    assert s.form_is_up() == "90210" and s.lit == 4
    typed(s, BACKSPACE + BACKSPACE + b"21")         # Backspace goes back a digit
    assert s.form_is_up() == "90210" and s.lit == 4
    typed(s, b"0")
    assert s.form_is_up() == "90210" and s.lit == 0     # after the last, the first
    assert s.asked(p.NESP_WEATHER_ZIP) == []
    typed(s, ENTER)
    assert s.report_is_up() == SHOWN
    assert s.asked(p.NESP_WEATHER_ZIP)[0] == b"\x0190210"


def test_backspace_stops_at_the_first_digit_and_the_arrows_are_the_d_pad(sky):
    s = sky()
    s.form_is_up()
    typed(s, BACKSPACE)
    assert s.form_is_up() == "00000" and s.lit == 0
    typed(s, LEFT)                                  # the arrows go round, as the D-pad does
    assert s.form_is_up() == "00000" and s.lit == 4
    typed(s, UP + UP + RIGHT + DOWN)
    assert s.form_is_up() == "90002" and s.lit == 0


def test_a_digit_typed_over_a_report_begins_the_next_zip_code(sky, where, weather):
    s = sky(kept=KEPT)
    s.go()
    s.report_is_up()
    typed(s, ENTER + UP)                            # no keys of the report's
    assert s.view == VIEW_REPORT and s.rows() == SHOWN
    typed(s, b"1")
    assert s.form_is_up() == "10210" and s.lit == 1
    typed(s, b"0001" + ESCAPE)                      # Escape is B: on the form, nothing
    assert s.form_is_up() == "10001" and s.lit == 0
    s.press(PAD_A)
    s.report_is_up()
    typed(s, ESCAPE)                                # and on the report, the form
    assert s.form_is_up() == "10001"


def test_a_nesp32_without_kbd_is_used_all_the_same(sky):
    def older(data):
        reply = nesp.parse(data)
        if reply.svc == p.NESP_SVC_SYS and reply.ok and len(reply.payload) == 7:
            return nesp.reply_frame(reply.svc, p.NESP_ST_NO_SERVICE, reply.seq,
                                    reply.payload[:6] + bytes((1, p.NESP_SVC_KBD)))
        return data

    s = sky(kept=KEPT, to_console=older)
    assert s.form_is_up() == "90210" and s.status == ""
    assert s.c.byte("greeted") and not s.c.byte("typing")
    s.stick.kbd_type(b"1")
    s.run(60)
    assert s.stick.kbd_unread == 1
    assert not any(service == p.NESP_SVC_KBD for service, _, _ in s.requests())
    s.press(PAD_A)
    assert s.report_is_up() == SHOWN


def test_it_gets_through_a_line_that_loses_and_damages_replies(sky):
    count = [0]

    def rough(data):
        count[0] += 1
        if count[0] % 3 == 0:
            return None
        if count[0] % 5 == 0:
            return data[:6] + bytes((data[6] ^ 0x40,)) + data[7:]
        return data

    s = sky(to_console=rough)
    s.form_is_up()
    s.enter("90210")
    s.press(PAD_A)
    assert s.report_is_up(2000) == SHOWN
    assert s.c.word("link_failed") > 10
    s.writes_were_in_time()
