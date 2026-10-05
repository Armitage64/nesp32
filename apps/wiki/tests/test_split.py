"""The header's split, and what the NMI costs.

The split's last write must land in the hblank before the article's first
scanline, whichever of its looks at PPUSTATUS sees the sprite 0 hit. A
frame is 29780.5 cycles, so the phase between the ROM's polling and the
picture is different every frame, and a few hundred frames try them all.
"""

import gen_screen
from console import PAD_A, PAD_DOWN, VBLANK_CYCLES
from drive import HBLANK, HEADER_SCROLL, SPLIT_LINE, open_reader

MARGIN = 12                     # dots to spare each side: what the model may be out by


def test_the_last_write_lands_in_the_hblank_above_the_article(console):
    dots = []
    for delay in range(2 * gen_screen.SPLIT_POLL):  # every phase of the polling, twice
        c = console(nmi_delay=delay)
        open_reader(c)
        since = len(c.frames)
        c.run(30, pad=PAD_DOWN)
        c.run(1, pad=PAD_A)
        c.run(30, pad=0)
        frames = c.frames[since:]
        assert all(frame.split_line == SPLIT_LINE for frame in frames)
        assert all(frame.hit_at is not None and frame.header == HEADER_SCROLL for frame in frames)
        dots += [frame.split_dot for frame in frames]
    assert HBLANK[0] + MARGIN <= min(dots) and max(dots) <= HBLANK[-1] - MARGIN, (min(dots), max(dots))
    # Looks come 11 cycles apart, 33 dots, or 15 when the loop's counter
    # wraps: the spread is between the two.
    assert 3 * gen_screen.SPLIT_POLL - 3 <= max(dots) - min(dots) <= 3 * gen_screen.SPLIT_POLL_SLOW


def test_stepping_the_waits_lands_where_skipping_them_does(console):
    """The harness skips the split's polling loops. Stepped a look at a
    time instead, the write lands on the same dot of the same frame."""
    for delay in (0, 4, 9):
        stepped = console(skip_waits=False, nmi_delay=delay)
        skipped = console(nmi_delay=delay)
        for c in (stepped, skipped):
            open_reader(c)
            c.run(30, pad=PAD_DOWN)
        assert len(stepped.frames) == len(skipped.frames)
        for slow, fast in zip(stepped.frames[-30:], skipped.frames[-30:]):
            assert (slow.split_line, slow.split, slow.top, slow.fine) == (
                fast.split_line, fast.split, fast.top, fast.fine)
            assert slow.split_dot == fast.split_dot


def test_sprite_0_sits_on_a_pixel_of_the_credit_line(console, build):
    c = console()
    c.run(3)
    x, y = gen_screen.sprite0_position()
    assert c.oam[0:4] == bytes((y - 1, gen_screen.TILE_SPRITE0, 0, x))
    assert c.background_pixel(HEADER_SCROLL, x, y) == gen_screen.CREDIT_COLOR
    assert y < 8 * gen_screen.HEADER_ROWS - 4      # lines to spare for the delay
    # Its colour is the credit line's, so it does not show.
    assert gen_screen.SPRITE_PALETTE[0] == gen_screen.PALETTES[gen_screen.PALETTE_LOGO][
        gen_screen.CREDIT_COLOR - 1]
    assert c.vram[0x3F11] == c.vram[0x3F0E]         # sprite colour 1, logo colour 2


def test_no_split_on_the_search_screen(console):
    c = console()
    c.run(20)
    assert all(frame.split is None and frame.header == HEADER_SCROLL for frame in c.frames[5:])


def test_a_missing_hit_costs_a_frame_and_not_a_hang(console):
    c = console()
    open_reader(c)
    c.memory[0x0200] = 0xF0         # sprite 0 off the screen
    c.run(5)
    assert all(frame.split is None for frame in c.frames[-3:])
    frames = len(c.frames)
    c.memory[0x0200] = gen_screen.sprite0_position()[1] - 1
    c.run(4)
    assert len(c.frames) == frames + 4 and c.frames[-1].split is not None


def test_the_nmi_is_done_well_inside_the_vblank(console):
    c = console()
    open_reader(c)
    c.run(120, pad=PAD_DOWN)
    frames = c.frames[5:]
    assert max(frame.last_write for frame in frames) < VBLANK_CYCLES - 600
    # OAM, a row of tiles, the scroll and the controller.
    assert max(frame.nmi_cycles for frame in frames) < 1400
