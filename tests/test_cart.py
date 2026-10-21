"""The cartridge on a simulated console with an MMC1: the file, the menu,
each program started from it with the firmware's own link and services on
the line, and reset.

The programs are not this tree's but the setup ROM, and are tested where
they come from. What is asked here is that each one is on the cartridge as
it was built, starts, and can be left; and of NES Radar, the one that
writes to the mapper, that it asks it for its own tiles and nothing else.
"""

import os

import gen_cart as cart_layout
import gen_screen as layout
import pytest
from console import (BANK_SIZE, CHR_SIZE, INES_HEADER, PAD_A, PAD_B, PAD_DOWN, PAD_SELECT,
                     PAD_START, PAD_UP, PPUCTRL_NMI)
from nesp import Stick
from test_juke import ONE
from wire import link

PROGRAMS = cart_layout.PROGRAMS
ROMS = {"jukebox": ("cart", "jukebox", "jukebox_link.nes"),
        "wiki": ("cart", "wiki", "nespedia_link.nes"),
        "throughput": ("cart", "throughput", "linktest.nes"),
        "radar": ("cart", "radar", "nes_radar_cart.nes"),
        "npr": ("cart", "npr", "npr.nes"),
        "weather": ("cart", "weather", "weather.nes"),
        "bluesky": ("cart", "bluesky", "bluesky.nes"),
        "setup": ("setup.nes",)}
# What each says it is in its hello.
APPS = {"jukebox": b"JUKE", "wiki": b"WIKI", "throughput": b"THRU", "radar": b"RADR",
        "npr": b"NPR ", "weather": b"WTHR", "bluesky": b"BSKY", "setup": b"SETP"}
MMC1_CHR0 = 1                   # the mapper's registers, as the console numbers them
CHR_WRITES = 5                  # to set one
RAM_END = 0x0800
LAUNCH_WRITES = 15              # three registers, five writes each
STUB = cart_layout.RESET_STUB & (BANK_SIZE - 1)
VECTOR = cart_layout.RESET_VECTOR & (BANK_SIZE - 1)


@pytest.fixture(scope="session")
def images(cart_build):
    return [cart_layout.Image(program, os.path.join(cart_build, *ROMS[program.key]))
            for program in PROGRAMS]


@pytest.fixture(scope="session")
def menu(cart_build):
    with open(os.path.join(cart_build, "cart", "menu.prg"), "rb") as handle:
        return handle.read()


@pytest.fixture(scope="session")
def rom(cart_build):
    with open(os.path.join(cart_build, "nesp32.nes"), "rb") as handle:
        return handle.read()


def choose(c, index):
    """Bring the menu's arrow to a program."""
    while c.byte("choice") != index:
        c.press(PAD_DOWN)


def start(c, index, button=PAD_A):
    """Run a program from the menu. The console is then as lenient as the
    program needs."""
    choose(c, index)
    c.press(button, release=0)
    c.strict = False
    c.run(2, pad=0)


def registers(image):
    """The mapper's control, CHR and PRG registers as the menu leaves them
    for a program."""
    return image.control, cart_layout.mapper_page(image.program), image.program.bank


def at_menu(c):
    return (c.home and c.ctrl & PPUCTRL_NMI
            and bytes(c.vram[0x2000:0x23C0]) == bytes(cart_layout.build_screen().names))


# --- the file ----------------------------------------------------------------------

def test_the_file_is_an_mmc1_with_no_memory(rom):
    assert len(rom) == INES_HEADER + 16 * BANK_SIZE + 16 * CHR_SIZE
    assert rom[:INES_HEADER] == b"NES\x1a\x10\x10\x10\x08" + bytes(8)


def test_every_program_is_there_as_it_was_built(rom, images):
    prg = rom[INES_HEADER:INES_HEADER + 16 * BANK_SIZE]
    tiles = rom[INES_HEADER + 16 * BANK_SIZE:]
    stub = prg[-BANK_SIZE:][STUB:STUB + cart_layout.STUB_SIZE]
    for image in images:
        program = image.program
        there = prg[program.bank * BANK_SIZE:][:len(image.prg)]
        changed = {offset for offset in range(len(there)) if there[offset] != image.prg[offset]}
        expected = set()
        for top in image.tops():
            start_of_top = top - BANK_SIZE
            expected |= set(range(start_of_top + STUB, start_of_top + STUB + len(stub)))
            expected |= {start_of_top + VECTOR, start_of_top + VECTOR + 1}
            assert there[start_of_top + STUB:][:len(stub)] == stub
            assert there[start_of_top + VECTOR:][:2] == bytes((0xDA, 0xFF))
        assert changed <= expected, program.name
        assert tiles[program.page * CHR_SIZE:][:len(image.chr)] == image.chr, program.name


def test_the_menu_is_the_last_bank_as_it_was_built(rom, menu):
    assert rom[INES_HEADER + 15 * BANK_SIZE:][:BANK_SIZE] == menu


def test_a_program_with_no_room_for_the_stub_is_refused(images, menu, cart_build):
    with open(os.path.join(cart_build, "cart", "chr.bin"), "rb") as handle:
        tiles = handle.read()
    cart_layout.build_rom(menu, tiles, images)
    setup = images[-1]
    built = setup.prg
    try:
        used = bytearray(built)
        used[len(used) - BANK_SIZE + STUB] = 0x60
        setup.prg = bytes(used)
        with pytest.raises(ValueError, match="FFDA"):
            cart_layout.build_rom(menu, tiles, images)
    finally:
        setup.prg = built


# --- the menu ----------------------------------------------------------------------

def test_power_on_is_the_menu(cart):
    c = cart()
    c.run(4)
    assert at_menu(c)
    assert c.mapper[:2] == [0x0E, 2 * cart_layout.MENU_PAGE]
    for index, name in enumerate(("Jukebox", "NESpedia", "NES Radar",
                                  "National Public Radio", "Weather", "Bluesky",
                                  "Throughput Test", "Setup")):
        assert c.line(cart_layout.LIST_ROW + cart_layout.LIST_STEP * index) == name
    assert c.line(layout.HELP_ROW) == "A:RUN"
    assert c.sprite() == cart_layout.arrow(0) + (c.chr.index(
        layout.tile_bytes(layout.picture_tile(layout.PICTURES["ARROW"]))) // 16,)


def test_the_header_says_main_menu(cart):
    c = cart()
    c.run(4)
    title = layout.cut_tiles(layout.font_text("MAIN MENU", 256, layout.CREDIT_COLOR))
    for dy, tiles in enumerate(title):
        for column, tile in enumerate(tiles):
            number = c.tiles(layout.TITLE_ROW + dy, column, 1)[0]
            assert c.chr[16 * number:16 * number + 16] == layout.tile_bytes(tile)


def test_up_and_down_move_the_arrow_and_go_round(cart):
    c = cart()
    c.run(4)
    last = len(PROGRAMS) - 1
    for index in list(range(1, last + 1)) + [0]:
        c.press(PAD_DOWN)
        assert c.byte("choice") == index
        assert c.sprite() and c.sprite()[:2] == cart_layout.arrow(index)
    for index in range(last, 1, -1):
        c.press(PAD_UP)
        assert c.byte("choice") == index
        assert c.sprite()[:2] == cart_layout.arrow(index)
    c.run(22, pad=PAD_UP)               # the press, and held, one repeat
    assert c.byte("choice") == 0
    assert at_menu(c)


def test_a_button_held_at_reset_starts_nothing(cart):
    c = cart()
    c.run(4)
    c.pad = PAD_A
    c.reset()
    c.run(20)
    assert at_menu(c)
    c.run(2, pad=0)
    c.press(PAD_A, release=0)
    c.run(2, pad=0)
    assert not c.home


# --- the programs ------------------------------------------------------------------

@pytest.mark.parametrize("index", range(len(PROGRAMS)), ids=[p.key for p in PROGRAMS])
def test_a_program_starts_and_reset_is_the_menu_again(cart, images, index):
    image = images[index]
    key = image.program.key
    c = cart()
    stick, _ = link(c, Stick)
    c.run(4)
    before = len(c.mapper_writes)
    start(c, index, PAD_START if index % 2 else PAD_A)
    writes = c.mapper_writes[before:]
    assert len(writes) >= LAUNCH_WRITES
    assert all(pc < RAM_END for pc, _, _ in writes[:LAUNCH_WRITES])     # the menu's, from RAM
    assert not c.home

    assert (c.mapper[0], c.mapper[1], c.mapper[3]) == registers(image)
    if key == "wiki":
        c.run(60)
        c.press(PAD_START)              # its hello is with its first search
    c.run_until(lambda: stick.hellos, 300)
    assert stick.app[0] == APPS[key]
    c.run(30)
    if image.program.mapper:
        # Built for the cartridge: it has asked the mapper for its tiles,
        # whole registers at a time, and for nothing else.
        own = c.mapper_writes[before + LAUNCH_WRITES:]
        assert own and len(own) % CHR_WRITES == 0
        assert {address >> 13 & 3 for _, address, _ in own} == {MMC1_CHR0}
        assert all(value < 0x80 for _, _, value in own)
        assert (c.mapper[0], c.mapper[3]) == (image.control, image.program.bank)
    else:
        # An NROM's program, which the mapper has heard nothing from: one
        # write would have changed the banks under it.
        assert len(c.mapper_writes) == before + LAUNCH_WRITES
        assert (c.mapper[0], c.mapper[1], c.mapper[3]) == registers(image)

    c.reset()
    c.strict = True
    c.run(6)
    assert at_menu(c)
    assert c.byte("choice") == 0
    other = (index + 1) % len(images)
    start(c, other)
    assert not c.home
    assert (c.mapper[0], c.mapper[1], c.mapper[3]) == registers(images[other])


@pytest.mark.parametrize("with_stick", (True, False), ids=("stick", "no-stick"))
def test_setups_quit_is_the_menu_again(cart, images, with_stick):
    index = next(index for index, image in enumerate(images) if image.program.key == "setup")
    c = cart()
    if with_stick:
        stick, _ = link(c, Stick)
    c.run(4)
    start(c, index)
    if with_stick:
        c.run_until(lambda: stick.hellos, 300)
    c.run(30)
    row = layout.BODY_ROW + 9 + 4               # the status screen's menu, its last
    assert c.text(row, layout.LEFT + 2, 4) == "QUIT"    # on the cartridge, there is one
    for _ in range(4):
        c.press(PAD_DOWN)
    c.press(PAD_A)
    c.strict = True
    c.run(6)
    assert at_menu(c)
    assert c.byte("choice") == 0
    start(c, index)                             # and it can be run again
    assert not c.home
    assert (c.mapper[0], c.mapper[1], c.mapper[3]) == registers(images[index])


def test_nes_radar_has_its_splash_and_then_its_scopes_tiles(cart, images):
    index = next(index for index, image in enumerate(images) if image.program.key == "radar")
    image = images[index]
    splash, scope = image.chr[:CHR_SIZE], image.chr[CHR_SIZE:]
    assert splash != scope
    c = cart()
    stick, _ = link(c, Stick)
    c.run(4)
    start(c, index)
    c.run(20)
    first = cart_layout.mapper_page(image.program)
    assert c.mapper[1] == first and c.chr == splash
    c.run_until(lambda: stick.hellos, 300)      # the splash is over: its editor is next
    c.run(10)
    assert c.mapper[1] == first + 2 and c.chr == scope
    # Nothing of another program's is under it, whatever it asks for.
    assert not any(c.rom_chr[page * CHR_SIZE:][:CHR_SIZE] in (splash, scope)
                   for page in range(16) if page not in (image.program.page,
                                                         image.program.page + 1))
    c.reset()
    c.strict = True
    c.run(6)
    assert at_menu(c) and c.mapper[1] == 2 * cart_layout.MENU_PAGE


def test_nes_radars_splash_is_not_skipped_by_the_start_that_chose_it(cart, images):
    index = next(index for index, image in enumerate(images) if image.program.key == "radar")
    image = images[index]
    splash = image.chr[:CHR_SIZE]
    c = cart()
    stick, _ = link(c, Stick)
    c.run(4)
    choose(c, index)
    c.run(2, pad=PAD_START)             # Start chooses it, and is held
    c.strict = False
    c.run(88)
    assert not c.home and c.chr == splash and not stick.hellos
    c.run(10, pad=0)
    assert c.chr == splash and not stick.hellos
    c.run_until(lambda: stick.hellos, 120)      # and the splash's two seconds end it


def test_select_in_nes_radars_editor_is_the_menu_again(cart, images):
    index = next(index for index, image in enumerate(images) if image.program.key == "radar")
    c = cart()
    stick, _ = link(c, Stick)          # with no Wi-Fi: Start comes back to the editor
    c.run(4)
    start(c, index)
    c.run_until(lambda: stick.hellos, 300)      # the splash is over: its editor is next
    c.run(30)
    assert not c.home
    # Select held from before the editor came back is not a press of it.
    c.run(4, pad=PAD_START | PAD_SELECT)
    c.run(120, pad=PAD_SELECT)
    c.run(10, pad=0)
    assert not c.home
    c.press(PAD_SELECT)
    c.strict = True
    c.run(6)
    assert at_menu(c) and c.mapper[1] == 2 * cart_layout.MENU_PAGE
    assert c.byte("choice") == 0
    start(c, index)
    assert not c.home


def test_two_programs_cannot_have_the_same_tiles(images, menu, cart_build):
    with open(os.path.join(cart_build, "cart", "chr.bin"), "rb") as handle:
        tiles = handle.read()
    radar = next(image for image in images if image.program.key == "radar")
    was = radar.program.page
    try:
        radar.program.page = 3          # its second page is the menu's
        with pytest.raises(ValueError, match="tiles"):
            cart_layout.build_rom(menu, tiles, images)
        radar.program.page = 2          # and here its first is the jukebox's
        with pytest.raises(ValueError, match="tiles"):
            cart_layout.build_rom(menu, tiles, images)
    finally:
        radar.program.page = was


def test_select_in_bluesky_s_favorites_is_the_menu_again(cart, images):
    index = next(index for index, image in enumerate(images) if image.program.key == "bluesky")
    c = cart()
    stick, _ = link(c, Stick)
    c.run(4)
    start(c, index)
    c.run_until(lambda: stick.hellos, 300)
    c.run(10)
    c.press(PAD_START)                  # past the splash, to the favorites
    c.run(30)
    assert not c.home
    c.press(PAD_SELECT)
    c.strict = True
    c.run(6)
    assert at_menu(c)
    assert c.byte("choice") == 0


def test_b_in_weathers_form_is_the_menu_again(cart, images):
    index = next(index for index, image in enumerate(images) if image.program.key == "weather")
    c = cart()
    stick, _ = link(c, Stick)
    c.run(4)
    start(c, index)
    c.run_until(lambda: stick.hellos, 300)
    c.run(60)                           # the form, all of it
    assert not c.home
    assert c.line(26) == "A : SUBMIT   B : QUIT"   # on the cartridge, there is a menu
    c.press(PAD_B)
    c.strict = True
    c.run(6)
    assert at_menu(c)
    assert c.byte("choice") == 0


def test_the_jukebox_waits_for_a_start_of_its_own(cart, images):
    index = next(index for index, image in enumerate(images) if image.program.key == "jukebox")
    c = cart()
    stick, _ = link(c, Stick)
    stick.add_track(ONE)
    c.run(4)
    choose(c, index)
    c.run(2, pad=PAD_A)                 # A chooses it, and is held
    c.strict = False
    c.run_until(lambda: stick.hellos, 300)
    c.run(60, pad=PAD_A)
    assert c.line(16) == "> First"      # nothing plays: that A was the menu's
    c.run(10, pad=0)                    # nor once it is let go
    assert c.line(16) == "> First" and c.line(13) == ""
    c.press(PAD_START)                  # and a Start of its own plays
    c.run_until(lambda: c.line(13).startswith("0:01"), 300)


# How each looks while it waits for a Start: NPR's status line has nothing
# on it, under its menu.
WAITING = {"npr": lambda c: c.line(8) == "" and "A : SELECT" in c.screen(),
           "throughput": lambda c: "PRESS START" in c.screen()}


@pytest.mark.parametrize("button", (PAD_A, PAD_START), ids=("a", "start"))
@pytest.mark.parametrize("key", ("npr", "throughput"))
def test_the_press_that_chose_a_program_does_not_start_it(cart, images, key, button):
    index = next(index for index, image in enumerate(images) if image.program.key == key)
    c = cart()
    stick, _ = link(c, Stick)
    c.run(4)
    choose(c, index)
    c.run(2, pad=button)                # it chooses the program, and is held
    c.strict = False
    c.run_until(lambda: stick.hellos, 300)
    c.run(60, pad=button)
    waiting = WAITING[key]
    assert waiting(c)
    c.run(30, pad=0)                    # nor once it is let go
    assert waiting(c)
    c.press(PAD_START)                  # and a Start of its own starts it
    c.run_until(lambda: not waiting(c), 120)


def test_b_in_nprs_menu_is_the_menu_again(cart, images):
    index = next(index for index, image in enumerate(images) if image.program.key == "npr")
    c = cart()
    stick, _ = link(c, Stick)
    c.run(4)
    start(c, index)
    c.run_until(lambda: stick.hellos, 300)
    c.run(30)
    assert not c.home
    assert c.text(26).strip().endswith("B : QUIT")     # on the cartridge, there is a menu
    c.press(PAD_B)
    c.strict = True
    c.run(6)
    assert at_menu(c)
    assert c.byte("choice") == 0


def test_b_in_the_jukeboxs_menu_is_the_menu_again(cart, images):
    index = next(index for index, image in enumerate(images) if image.program.key == "jukebox")
    c = cart()
    stick, _ = link(c, Stick)
    stick.add_track(ONE)
    c.run(4)
    start(c, index)
    c.run_until(lambda: stick.hellos, 300)
    c.run(40)
    assert not c.home
    assert c.line(16) == "> First" and c.line(26) == "A : SELECT   B : QUIT"
    c.press(PAD_B)
    c.strict = True
    c.run(6)
    assert at_menu(c)
    assert c.byte("choice") == 0


def test_b_in_the_throughput_test_is_the_menu_again(cart, images):
    index = next(index for index, image in enumerate(images)
                 if image.program.key == "throughput")
    c = cart()
    stick, _ = link(c, Stick)
    c.run(4)
    start(c, index)
    c.run_until(lambda: stick.hellos, 300)
    c.run_until(lambda: "PRESS START" in c.line(26), 120)   # at the foot
    assert not c.home
    c.press(PAD_B)
    c.strict = True
    c.run(6)
    assert at_menu(c)
    assert c.byte("choice") == 0


def test_select_in_nespedias_search_is_the_menu_again(cart, images):
    index = next(index for index, image in enumerate(images) if image.program.key == "wiki")
    c = cart()
    link(c, Stick)
    c.run(4)
    start(c, index)
    c.run(60)                           # it says hello only with its first search
    assert not c.home
    help_row = bytes(c.vram[0x2400 + 32 * 28:0x2400 + 32 * 29])     # its search is in nametable 1
    assert help_row.strip(b"\0 ") == b"START : SEARCH   SELECT : QUIT"   # on the cartridge, a menu
    c.press(PAD_SELECT)
    c.strict = True
    c.run(6)
    assert at_menu(c)
    assert c.byte("choice") == 0
