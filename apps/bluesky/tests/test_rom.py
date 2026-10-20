"""The Bluesky ROM against nesp32's firmware, on a simulated console."""

import os

import gen_screen as layout
import nesp_proto as p
from reader import (NOT_FOUND, PAD_A, PAD_B, PAD_DOWN, PAD_LEFT, PAD_RIGHT, PAD_SELECT,
                    PAD_START, PAD_UP, PAGE, SCREEN_HER, cards, slots)

DEFAULTS = ["levimaaia.com", "andyreitano.com", "adriansdigitalbasement.com",
            "jeriellsworth.bsky.social"]
VIEW_SPLASH, VIEW_LIST, VIEW_FORM, VIEW_POST = range(4)


def test_the_layout_is_the_nesp32s():
    assert (layout.POST_COLUMNS, layout.POST_LINES) == (p.NESP_BSKY_COLUMNS, p.NESP_BSKY_ROWS)
    assert (layout.HANDLE_MAX, layout.FAVORITES) == (p.NESP_BSKY_HANDLE_MAX,
                                                     p.NESP_BSKY_FAVORITES)
    assert set(layout.SIGNS) == {p.NESP_BSKY_REPLY, p.NESP_BSKY_REPOST, p.NESP_BSKY_LIKE}
    assert layout.LETTERS[0] == " " and len(set(layout.LETTERS)) == len(layout.LETTERS)
    assert len(layout.SLOT_ROWS) == 8 and layout.TEXT_SLOTS == 6        # hers
    assert max(len(handle) for handle in DEFAULTS) <= layout.WIDTH        # each whole on a line


def test_her_page_is_as_she_made_it_but_for_tiles_that_were_empty():
    data = layout.chr_data(PAGE)
    sprites = data[:layout.PAGE]
    used = [number for number in range(256) if any(sprites[16 * number:16 * number + 16])]
    assert used == sorted((layout.ARROW_TILE, layout.MARK_TILE))
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
    layout.put(ours, layout.SPLASH_STATUS_ROW,
               layout.status_tiles("Press Start", ground=False, page=PAGE))
    assert bytes(s.c.vram[0x2000:0x2400]) == bytes(ours)
    assert bytes(s.c.vram[0x3F00:0x3F20]) == layout.read("test.pal")
    assert s.c.sprite() is None
    s.writes_were_in_time()


def test_start_brings_up_the_favorites_a_nesp32_begins_with_on_her_screen(sky):
    s = sky()
    assert s.go() == DEFAULTS
    assert s.screen == SCREEN_HER and s.c.ctrl & 0x10
    assert bytes(s.c.vram[0x3F00:0x3F20]) == layout.read("test.pal")
    assert s.lines()[:5] == DEFAULTS + [layout.OTHER_TEXT]
    assert s.arrow == 0 and s.status == "FAVORITES"
    assert s.help == layout.HELP_LIST           # by itself, Select has no menu to go to
    assert s.asked(p.NESP_BSKY_FAVORITE) == [bytes((number,)) for number in range(4)]
    # Her picture is round the lines: nothing of hers is gone but her words.
    blank = layout.blank_screen(PAGE)
    for row in range(30):
        if row not in layout.SLOT_ROWS + (layout.STATUS_ROW, layout.HELP_ROW):
            assert bytes(s.c.vram[0x2000 + 32 * row:][:32]) == blank[32 * row:32 * row + 32]
    s.writes_were_in_time()


def test_a_post_is_on_her_screen_as_a_tweet_was(sky, feed):
    s = sky()
    s.go()
    s.press(PAD_A)
    expected = cards(feed)
    assert s.post_is_up() == slots(expected[0])
    assert s.status == "POST 1 OF 8 PAGE 1/3"
    assert s.served == ["levimaaia.com"]
    assert s.asked(p.NESP_BSKY_FEED)[0] == b"\x01levimaaia.com"
    # Her picture is under the lines' spaces: the slope at the end of her
    # last line is as she drew it.
    blank = layout.blank_screen(PAGE)
    row = layout.SLOT_ROWS[-1]
    assert bytes(s.c.vram[0x2000 + 32 * row + 24:0x2000 + 32 * row + 30]) == \
        blank[32 * row + 24:32 * row + 30]
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
    assert s.arrow == 0 and s.status == "FAVORITES"
    s.writes_were_in_time()


def test_the_arrow_goes_round(sky):
    s = sky()
    s.go()
    s.press(PAD_UP)
    s.settle()
    assert s.arrow == len(DEFAULTS)             # the way to the form
    s.press(PAD_DOWN)
    s.press(PAD_DOWN)
    s.press(PAD_DOWN)
    s.settle()
    assert s.arrow == 2
    s.press(PAD_A)
    s.post_is_up()
    assert s.served == ["adriansdigitalbasement.com"]


def test_ten_favorites_are_eight_lines_at_a_time(sky):
    kept = [b"h%d.example" % number for number in range(p.NESP_BSKY_FAVORITES)]
    s = sky(kept=kept)
    assert s.go() == [handle.decode() for handle in kept]
    assert s.lines() == ["h%d.example" % number for number in range(8)]
    for _ in range(8):
        s.press(PAD_DOWN)
    assert s.list_is_up() and s.arrow == 7 and s.c.byte("list_top") == 1
    assert s.lines()[-1] == "h8.example"
    s.press(PAD_DOWN)
    s.press(PAD_DOWN)
    assert s.list_is_up() and s.arrow == 7 and s.c.byte("list_top") == 3
    assert s.lines()[-1] == layout.OTHER_TEXT
    s.press(PAD_DOWN)               # round to the first
    assert s.list_is_up() and s.arrow == 0 and s.c.byte("list_top") == 0
    s.press(PAD_UP)                 # and back to the last
    assert s.list_is_up() and s.arrow == 7 and s.c.byte("list_top") == 3
    s.press(PAD_A)
    s.settle()
    assert s.c.byte("view") == VIEW_FORM


def test_start_twice_takes_a_favorite_off_and_the_nesp32_keeps_that(sky):
    s = sky()
    s.go()
    s.press(PAD_DOWN)
    s.press(PAD_START)
    s.settle()
    assert s.status == "START AGAIN TO REMOVE"
    s.press(PAD_DOWN)               # anything else calls it off
    s.settle()
    assert s.status == "FAVORITES"
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
    assert s.view == VIEW_FORM and s.help == layout.HELP_FORM
    assert s.lines() == [line.rstrip() for line in layout.form_lines()]
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
    s.run_until(lambda: s.status == "SAVED TO FAVORITES")
    assert s.list_is_up() == DEFAULTS + ["jay.bsky.social"]
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
    s.settle()
    assert s.lines() == [""] * 8


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
    assert s.arrow == 2


def test_no_favorites_at_all(sky):
    s = sky(kept=[])
    assert s.go() == []
    assert s.arrow == 0 and s.lines()[0] == layout.OTHER_TEXT
    s.press(PAD_START)              # there is nothing to remove
    s.run(10)
    assert s.status == "FAVORITES"


def test_the_previews_are_up_to_date(tmp_path):
    """docs/ has what `make preview` makes."""
    docs = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs")
    layout.main([str(tmp_path), "--preview", str(tmp_path / "screen.png")])
    for name in ("screen.png", "screen-list.png", "screen-form.png", "screen-splash.png"):
        with open(os.path.join(docs, name), "rb") as ours, open(tmp_path / name, "rb") as made:
            assert ours.read() == made.read(), name
