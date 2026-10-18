"""The Bluesky ROM against nesp32's firmware, on a simulated console."""

import os

import gen_screen as layout
import nesp_proto as p
from reader import (NOT_FOUND, PAD_A, PAD_B, PAD_DOWN, PAD_LEFT, PAD_RIGHT, PAD_SELECT,
                    PAD_START, PAD_UP, PAGE, SCREEN_APP, SCREEN_POST, cards, slots)

DEFAULTS = ["levimaaia.com", "andyreitano.com", "adriansdigitalbasement.com",
            "jeriellsworth.bsky.social"]
VIEW_SPLASH, VIEW_LIST, VIEW_FORM, VIEW_POST = range(4)


def test_the_layout_is_the_nesp32s():
    assert (layout.POST_COLUMNS, layout.POST_LINES) == (p.NESP_BSKY_COLUMNS, p.NESP_BSKY_ROWS)
    assert (layout.HANDLE_MAX, layout.FAVORITES) == (p.NESP_BSKY_HANDLE_MAX,
                                                     p.NESP_BSKY_FAVORITES)
    assert set(layout.SIGNS) == {p.NESP_BSKY_REPLY, p.NESP_BSKY_REPOST, p.NESP_BSKY_LIKE}
    assert layout.OTHER_ROW < layout.ROWS
    assert layout.LETTERS[0] == " " and len(set(layout.LETTERS)) == len(layout.LETTERS)
    assert len(layout.POST_SLOT_ROWS) == 8 and layout.TEXT_SLOTS == 6     # hers


def test_her_page_is_as_she_made_it_but_for_tiles_that_were_empty():
    data = layout.chr_data(layout.build_screen(), PAGE)
    for code in range(0x21, 0x7F):
        assert any(data[16 * code:16 * code + 16])          # the app's font
    hers = layout.read("ascii.chr")[layout.PAGE:]
    ours = data[layout.PAGE:]
    changed = [number for number in range(256)
               if ours[16 * number:][:16] != hers[16 * number:][:16]]
    assert len(changed) == len(layout.GROUND_CHARS) + len(layout.SIGNS)
    assert all(not any(hers[16 * number:16 * number + 16]) for number in changed)
    for char in layout.GROUND_CHARS:
        assert PAGE.ground[char] in changed
    for code in layout.SIGN_CODES:
        assert PAGE.font[chr(code)] in changed


def test_with_no_nesp32_the_splash_waits(sky):
    s = sky(attached=False)
    s.c.run(40)
    assert s.view == VIEW_SPLASH
    assert s.status == "Looking for the nesp32..."
    s.c.press(PAD_START)            # and Start does nothing
    s.c.run(20)
    assert s.view == VIEW_SPLASH
    s.writes_were_in_time()


def test_the_splash_is_connectednes_with_its_words(sky):
    s = sky()
    s.splash_is_up()
    assert s.c.ctrl & 0x10          # her page of tiles
    ours = bytearray(layout.splash(PAGE))
    start = 32 * layout.SPLASH_STATUS_ROW + layout.HER_COLUMN
    ours[start:start + layout.HER_STATUS_WIDTH] = layout.her_status("Press Start", page=PAGE)
    assert bytes(s.c.vram[0x2000:0x2400]) == bytes(ours)
    assert bytes(s.c.vram[0x3F00:0x3F20]) == layout.read("test.pal")
    assert s.c.sprite() is None
    s.writes_were_in_time()


def test_start_brings_up_the_favorites_a_nesp32_begins_with(sky):
    s = sky()
    assert s.go() == DEFAULTS
    assert s.screen == SCREEN_APP and not s.c.ctrl & 0x10
    assert bytes(s.c.vram[0x3F00:0x3F20]) == layout.palette_data()
    header = layout.build_screen().nametable()
    width = 32 * layout.HEADER_ROWS
    assert bytes(s.c.vram[0x2000:0x2000 + width]) == header[:width]
    assert s.arrow == layout.LIST_ROW and s.status == ""
    assert s.foot == layout.FOOT_LIST           # by itself, Select has no menu to go to
    assert s.asked(p.NESP_BSKY_FAVORITE) == [bytes((number,)) for number in range(4)]
    s.writes_were_in_time()


def test_a_post_is_on_her_screen_as_a_tweet_was(sky, feed):
    s = sky()
    s.go()
    s.press(PAD_A)
    expected = cards(feed)
    assert s.post_is_up() == slots(expected[0])
    assert s.screen == SCREEN_POST and s.c.ctrl & 0x10
    assert bytes(s.c.vram[0x3F00:0x3F20]) == layout.read("test.pal")
    assert s.status == "POST 1 OF 8 PAGE 1/3"
    assert s.served == ["levimaaia.com"]
    assert s.asked(p.NESP_BSKY_FEED)[0] == b"\x01levimaaia.com"
    # Her picture is under the lines' spaces: the slope at the end of her
    # last line is as she drew it.
    post = layout.post_screen(PAGE)
    row = layout.POST_SLOT_ROWS[-1]
    assert bytes(s.c.vram[0x2000 + 32 * row + 24:0x2000 + 32 * row + 28]) == \
        post[32 * row + 24:32 * row + 28]
    s.writes_were_in_time()


def test_up_and_down_go_through_a_post_s_text(sky, feed):
    s = sky()
    s.go()
    s.press(PAD_A)
    expected = cards(feed)[0]
    s.post_is_up()
    s.press(PAD_DOWN)
    assert s.post_is_up() == slots(expected, 6) and s.status == "POST 1 OF 8 PAGE 2/3"
    s.press(PAD_DOWN)
    assert s.post_is_up() == slots(expected, 12) and s.status == "POST 1 OF 8 PAGE 3/3"
    s.press(PAD_DOWN)               # no further than the last
    assert s.post_is_up() == slots(expected, 12)
    s.press(PAD_UP)
    assert s.post_is_up() == slots(expected, 6) and s.status == "POST 1 OF 8 PAGE 2/3"


def test_left_and_right_go_through_the_posts(sky, feed):
    s = sky()
    s.go()
    s.press(PAD_A)
    expected = cards(feed)
    s.post_is_up()
    s.press(PAD_DOWN)
    s.press(PAD_RIGHT)              # from the top of the next
    assert s.post_is_up() == slots(expected[1]) and s.status == "POST 2 OF 8 PAGE 1/3"
    for _ in range(10):             # and no further than the last
        s.press(PAD_RIGHT)
    assert s.post_is_up() == slots(expected[7]) and s.status == "POST 8 OF 8 PAGE 1/3"
    s.press(PAD_LEFT)
    assert s.post_is_up() == slots(expected[6]) and s.status == "POST 7 OF 8"
    s.press(PAD_B)
    assert s.list_is_up() == DEFAULTS
    assert s.screen == SCREEN_APP and s.arrow == layout.LIST_ROW
    s.writes_were_in_time()


def test_the_arrow_goes_round(sky):
    s = sky()
    s.go()
    s.press(PAD_UP)
    s.settle()
    assert s.arrow == layout.OTHER_ROW
    s.press(PAD_DOWN)
    s.press(PAD_DOWN)
    s.press(PAD_DOWN)
    s.settle()
    assert s.arrow == layout.LIST_ROW + 2
    s.press(PAD_A)
    s.post_is_up()
    assert s.served == ["adriansdigitalbasement.com"]


def test_start_twice_takes_a_favorite_off_and_the_nesp32_keeps_that(sky):
    s = sky()
    s.go()
    s.press(PAD_DOWN)
    s.press(PAD_START)
    s.settle()
    assert s.status == "START AGAIN TO REMOVE"
    s.press(PAD_DOWN)               # anything else calls it off
    s.settle()
    assert s.status == ""
    s.press(PAD_UP)
    s.press(PAD_START)
    s.press(PAD_START)
    s.run(20)
    assert s.list_is_up() == [DEFAULTS[0]] + DEFAULTS[2:]
    assert s.status == "REMOVED FROM FAVORITES"
    assert s.stick.favorites == [handle.encode() for handle in [DEFAULTS[0]] + DEFAULTS[2:]]
    assert s.asked(p.NESP_BSKY_REMOVE) == [b"\x01"]


def test_select_does_nothing_by_itself(sky):
    s = sky()
    s.go()
    s.press(PAD_SELECT)
    s.run(10)
    assert s.view == VIEW_LIST and s.list_is_up() == DEFAULTS


def test_a_handle_typed_in_the_form(sky):
    s = sky()
    s.go()
    s.press(PAD_UP)                 # the last line: the way to the form
    s.press(PAD_A)
    s.settle()
    assert s.view == VIEW_FORM and s.foot == layout.FOOT_FORM
    assert s.rows() == layout.form_rows()
    s.type("bsky.app")
    sprite = s.c.sprite()
    s.run(16)
    assert (sprite is None) != (s.c.sprite() is None)      # the mark blinks
    s.press(PAD_A)
    s.post_is_up()
    assert s.served == ["bsky.app"]
    assert s.asked(p.NESP_BSKY_FEED)[-1][1:] == b"bsky.app"
    s.press(PAD_START)              # and saved to the favorites
    s.run(30)
    assert s.status == "SAVED TO FAVORITES"
    assert s.stick.favorites[-1] == b"bsky.app"
    s.press(PAD_B)
    assert s.list_is_up() == DEFAULTS + ["bsky.app"]


def test_start_in_the_form_saves_and_goes_to_the_favorites(sky):
    s = sky()
    s.go()
    s.press(PAD_UP)
    s.press(PAD_A)
    s.settle()
    s.type("jay")
    s.press(PAD_START)
    assert s.list_is_up() == DEFAULTS + ["jay.bsky.social"]
    assert s.status == "SAVED TO FAVORITES"
    assert s.served == []


def test_an_empty_form_asks_nothing(sky):
    s = sky()
    s.go()
    s.press(PAD_UP)
    s.press(PAD_A)
    s.settle()
    s.press(PAD_A)
    s.settle()
    assert s.status == "TYPE A HANDLE FIRST" and s.view == VIEW_FORM
    assert s.asked(p.NESP_BSKY_FEED) == []


def test_what_is_not_a_handle_goes_back_to_the_form(sky):
    s = sky()
    s.go()
    s.press(PAD_UP)
    s.press(PAD_A)
    s.settle()
    s.type(".")
    s.press(PAD_A)
    s.run_until(lambda: s.status == "THAT IS NOT A HANDLE")
    s.settle()
    assert s.view == VIEW_FORM and s.typed == "."


def test_a_handle_no_one_has(sky):
    s = sky(feeds={"levimaaia.com": NOT_FOUND})
    s.go()
    s.press(PAD_A)
    s.run_until(lambda: s.status == "NO ONE HAS THAT HANDLE")
    blank = layout.post_screen(PAGE)
    for row in layout.POST_SLOT_ROWS:
        assert bytes(s.c.vram[0x2000 + 32 * row:][:32]) == blank[32 * row:32 * row + 32]


def test_a_fetch_that_fails_says_why(sky):
    s = sky(feeds={"levimaaia.com": (False, b"THE SITE SAID 503")})
    s.go()
    s.press(PAD_A)
    s.run_until(lambda: s.status == "THE SITE SAID 503")


def test_an_account_with_no_posts(sky):
    s = sky(feeds={"levimaaia.com": b'{"feed":[]}'})
    s.go()
    s.press(PAD_A)
    s.run_until(lambda: s.status == "NO POSTS YET")


def test_the_status_line_says_it_is_fetching(sky, feed):
    s = sky()
    s.go()
    s.hold = True
    s.press(PAD_A)
    s.run_until(lambda: s.stick.fetching)
    s.run(10)
    assert s.status == "FETCHING POSTS"
    s.hold = False
    assert s.post_is_up() == slots(cards(feed)[0])


def test_a_nesp32_switched_off_and_on_is_greeted_again(sky, feed):
    s = sky()
    s.go()
    s.press(PAD_A)
    s.post_is_up()
    s.plug_in()                     # a new nesp32, which has no posts
    s.press(PAD_RIGHT)
    assert s.post_is_up(1200) == slots(cards(feed)[1])
    assert s.served == ["levimaaia.com", "levimaaia.com"]


def test_kept_favorites_are_the_list(sky):
    s = sky(kept=[b"one.bsky.social", b"two.example"])
    assert s.go() == ["one.bsky.social", "two.example"]
    s.press(PAD_DOWN)
    s.press(PAD_DOWN)
    s.settle()
    assert s.arrow == layout.OTHER_ROW


def test_no_favorites_at_all(sky):
    s = sky(kept=[])
    assert s.go() == []
    assert s.arrow == layout.OTHER_ROW
    s.press(PAD_START)              # there is nothing to remove
    s.run(10)
    assert s.status == ""


def test_the_previews_are_up_to_date(tmp_path):
    """docs/ has what `make preview` makes."""
    docs = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs")
    layout.main([str(tmp_path), "--preview", str(tmp_path / "screen.png")])
    for name in ("screen.png", "screen-list.png", "screen-form.png", "screen-splash.png"):
        with open(os.path.join(docs, name), "rb") as ours, open(tmp_path / name, "rb") as made:
            assert ours.read() == made.read(), name
