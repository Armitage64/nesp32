"""The cartridge on a simulated console with an MMC1: the file, the menu,
each program started from it with the firmware's own link and services on
the line, and reset.

The programs are not this tree's but the setup ROM, and are tested where
they come from. What is asked here is that each one is on the cartridge as
it was built, starts, and can be left.
"""

import os

import gen_cart as cart_layout
import gen_screen as layout
import pytest
from console import (BANK_SIZE, CHR_SIZE, INES_HEADER, PAD_A, PAD_DOWN, PAD_START, PAD_UP,
                     PPUCTRL_NMI)
from nesp import Stick
from wire import link

PROGRAMS = cart_layout.PROGRAMS
ROMS = {"jukebox": ("cart", "jukebox", "jukebox_link.nes"),
        "wiki": ("cart", "wiki", "nespedia_link.nes"),
        "drmario": ("cart", "drmario", "drmario_net.nes"),
        "throughput": ("cart", "throughput", "linktest.nes"),
        "setup": ("setup.nes",)}
# What each says it is in its hello. Dr. Mario's is said from its own menu,
# a few screens in.
APPS = {"jukebox": b"JUKE", "wiki": b"WIKI", "throughput": b"THRU", "setup": b"SETP"}
RAM_END = 0x0800
LAUNCH_WRITES = 15              # three registers, five writes each
STUB = cart_layout.RESET_STUB & (BANK_SIZE - 1)
VECTOR = cart_layout.RESET_VECTOR & (BANK_SIZE - 1)
COMMON = cart_layout.DRMARIO_COMMON & (BANK_SIZE - 1)


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
    return image.control, 2 * image.program.page, image.program.bank


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


def test_the_menu_has_dr_marios_first_bytes_where_that_game_has_them(rom, images, menu):
    last = rom[INES_HEADER + 15 * BANK_SIZE:][:BANK_SIZE]
    size = cart_layout.DRMARIO_COMMON_SIZE
    drmario = next(image for image in images if image.program.mapper)
    assert last[COMMON:COMMON + size] == drmario.prg[BANK_SIZE + COMMON:][:size]
    assert last[:COMMON] == menu[:COMMON]
    assert last[COMMON + size:] == menu[COMMON + size:]


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
    for index, name in enumerate(("Jukebox", "NESpedia", "Dr. Mario", "Throughput Test",
                                  "NESP32 Setup")):
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
    for index in (1, 2, 3, 4, 0):
        c.press(PAD_DOWN)
        assert c.byte("choice") == index
        assert c.sprite() and c.sprite()[:2] == cart_layout.arrow(index)
    for index in (4, 3):
        c.press(PAD_UP)
        assert c.byte("choice") == index
        assert c.sprite()[:2] == cart_layout.arrow(index)
    c.run(22, pad=PAD_UP)               # the press, and held, one repeat
    assert c.byte("choice") == 1
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

    if key == "drmario":
        # Its reset code has reset the mapper, run on in the menu's bank,
        # and come back to its own; its title is up, on its own tiles.
        c.run(150)
        assert (c.mapper[0], c.mapper[3]) == (cart_layout.CONTROL_DRMARIO, 0)
        assert c.mapper[1] < 8 and c.mapper[2] < 8
        assert c.ctrl & PPUCTRL_NMI and any(c.vram[0x2000:0x23C0])
    else:
        assert (c.mapper[0], c.mapper[1], c.mapper[3]) == registers(image)
        if key == "wiki":
            c.run(60)
            c.press(PAD_START)          # its hello is with its first search
        c.run_until(lambda: stick.hellos, 300)
        assert stick.app[0] == APPS[key]
        c.run(30)
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
    if images[other].program.mapper:
        c.run(10)
        assert c.mapper[0] == cart_layout.CONTROL_DRMARIO
    else:
        assert (c.mapper[0], c.mapper[1], c.mapper[3]) == registers(images[other])
