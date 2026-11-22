"""The Gallery ROM against nesp32's firmware, on a simulated console."""

import gen_screen as layout
import nesp_proto as p
from conftest import fixture
from viewer import (PAD_B, PAD_LEFT, PAD_RIGHT, PAD_SELECT, PAD_START, STATE_INFO,
                    STATE_SEARCH, STATE_SEARCHING, STATE_VIEW)

SPLIT_LINE = 8 * p.NESP_COMMONS_SPLIT_ROW - 1


def info_is_up(g, index, total):
    assert g.state == STATE_INFO and g.c.ctrl & 3 == 0
    assert g.line(0, layout.COUNT_ROW) == "PICTURE %02d OF %02d" % (index, total)
    assert g.line(0, 4) == "WIKIMEDIA COMMONS"


def test_the_search_screen_is_up_with_lighthouse_to_search_for(gallery):
    g = gallery()
    g.run_until(lambda: g.c.byte("query_len") > 0)
    g.run(8)
    assert g.state == STATE_SEARCH and g.c.ctrl & 3 == 1     # nametable 1
    assert g.text(1, layout.FIELD_ROW, layout.FIELD_COLUMN, len(layout.DEFAULT_QUERY)) \
        == layout.DEFAULT_QUERY
    assert g.stick.hellos == 1


def test_a_search_shows_the_first_pictures_info_page_with_its_words(gallery):
    g = gallery(pictures=3)
    g.hold = True
    g.run_until(lambda: g.c.byte("query_len") > 0)
    g.press(PAD_START)
    g.run(20)
    assert g.state == STATE_SEARCHING and g.served == []    # held: still searching
    assert g.line(1, layout.STATUS_ROW) == "SEARCHING..."
    g.hold = False
    g.run_until(lambda: g.state == STATE_INFO)
    g.hold = True                   # and the picture is held
    g.run(30)
    info_is_up(g, 1, 3)
    rows = [g.line(0, row) for row in layout.CAPTION_ROWS]
    assert rows == ["Picture number 1", "", "By Ann Example", "CC BY 4.0"]
    assert g.line(0, layout.INFO_STATUS_ROW) == "LOADING..."
    assert g.line(0, layout.INFO_HELP_ROW) == layout.INFO_HELP
    assert g.c.mask & 0x18 == 0x18


def test_the_picture_comes_in_and_is_shown_split_between_the_tables(gallery):
    g = gallery()
    g.search()
    g.shown()
    made = g.made()
    vram = g.c.vram
    assert bytes(vram[0:0x2000]) == made[p.NESP_COMMONS_CHR:p.NESP_COMMONS_CHR + 0x2000]
    assert bytes(vram[0x2000:0x2400]) == made[p.NESP_COMMONS_NAMES:p.NESP_COMMONS_NAMES + 0x400]
    assert bytes(vram[0x3F00:0x3F20]) == made[p.NESP_COMMONS_PALETTE:p.NESP_COMMONS_PALETTE + 32]
    assert bytes(g.c.oam[0:4]) == made[p.NESP_COMMONS_SPRITE:p.NESP_COMMONS_SPRITE + 4]
    assert all(g.c.oam[4 * n] >= 0xEF for n in range(1, 64))    # no other sprite
    assert g.c.byte("split_delay") == made[p.NESP_COMMONS_DELAY]
    assert g.c.mask == 0x1E
    # Every frame changes table once, in the hblank of the top half's last line.
    for frame in g.c.frames[-3:]:
        assert frame.hit
        splits = [(line, dot) for line, dot, value in frame.ctrl_writes if value == 0x90]
        assert len(splits) == 1
        line, dot = splits[0]
        assert line == SPLIT_LINE and 240 < dot < 321, (line, dot)
        assert [value for _, _, value in frame.ctrl_writes][0] == 0x80    # the NMI's


def test_right_and_left_go_from_picture_to_picture(gallery):
    g = gallery(pictures=3)
    g.search()
    g.shown()
    g.press(PAD_RIGHT)
    g.run_until(lambda: g.state == STATE_INFO)      # the font is put back first
    info_is_up(g, 2, 3)
    assert g.line(0, layout.CAPTION_ROWS[0]) in ("", "Picture number 2")
    g.shown()
    assert g.served[-1].endswith("/2.jpg")
    g.press(PAD_RIGHT)
    g.run_until(lambda: g.state == STATE_INFO)
    g.shown()
    assert g.c.byte("index") == 2
    g.press(PAD_RIGHT)              # there is no fourth
    g.run(4)
    assert g.state == STATE_VIEW and g.c.byte("index") == 2
    g.press(PAD_LEFT)
    g.run_until(lambda: g.state == STATE_INFO)
    info_is_up(g, 2, 3)
    g.shown()
    assert g.c.byte("index") == 1


def test_b_goes_back_to_the_search_with_the_font_and_its_colours(gallery, rom):
    g = gallery()
    g.search()
    g.shown()
    g.press(PAD_B)
    g.run(4)
    assert g.state == STATE_SEARCH and g.c.ctrl & 3 == 1
    with open(rom[2] + "/chr.bin", "rb") as handle:
        assert bytes(g.c.vram[0:0x1000]) == handle.read()
    assert bytes(g.c.vram[0x3F00:0x3F04]) == bytes((layout.BACKDROP,) + layout.PALETTES[0])
    assert all(g.c.oam[4 * n] >= 0xEF for n in range(64))


def test_select_does_nothing_by_itself(gallery):
    g = gallery()
    g.search()
    g.shown()
    g.press(PAD_SELECT)
    g.run(4)
    assert g.state == STATE_VIEW


def test_a_picture_that_fails_says_why_on_its_page(gallery):
    g = gallery(pictures=2, failing={1})
    g.search()
    g.run_until(lambda: g.line(0, layout.INFO_STATUS_ROW) != "LOADING...")
    assert g.line(0, layout.INFO_STATUS_ROW) == "THE SITE SAID 404"
    g.press(PAD_RIGHT)              # the next is there
    g.shown()
    assert g.c.byte("index") == 1


def test_a_search_with_nothing_found_says_so(gallery):
    g = gallery(pictures=0)
    g.run_until(lambda: g.c.byte("query_len") > 0)
    g.press(PAD_START)
    g.run_until(lambda: g.state == STATE_SEARCH)
    g.run(8)
    assert g.line(1, layout.STATUS_ROW) == "NO PICTURES FOUND"


def test_the_keyboards_arrows_go_from_picture_to_picture(gallery):
    g = gallery(pictures=2)
    g.stick.kbd_paired(b"MX KEYS S")
    g.stick.kbd_state = p.NESP_KEYBOARD_CONNECTED
    g.run(30)
    g.stick.kbd_type(b"x")
    g.run(10)
    g.stick.kbd_type(bytes((p.NESP_KEY_ENTER,)))
    g.run_until(lambda: g.state == STATE_VIEW)
    g.run(3)
    assert g.served[0].find("gsrsearch=x+") > 0
    g.stick.kbd_type(bytes((p.NESP_KEY_RIGHT,)))
    g.run_until(lambda: g.state == STATE_INFO)
    info_is_up(g, 2, 2)
    g.shown()
    g.stick.kbd_type(bytes((p.NESP_KEY_ESCAPE,)))
    g.run_until(lambda: g.state == STATE_SEARCH)


def test_the_picture_fixture_is_the_nesp32s():
    assert fixture("commons_tower.jpg")[:2] == b"\xff\xd8"
