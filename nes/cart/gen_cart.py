#!/usr/bin/env python3
"""Put the eight programs and a menu on one cartridge.

    nes/cart/gen_cart.py tables build/cart --jukebox J.nes --wiki W.nes ...
    nes/cart/gen_cart.py rom build/nesp32.nes --menu menu.prg --chr chr.bin
                                              --jukebox J.nes --wiki W.nes ...
    nes/cart/gen_cart.py page radar

The cartridge is an MMC1 with 256 KB of PRG and 128 KB of CHR ROM, and no
memory of its own. Seven of the programs are NROM, and the MMC1 set to 32
KB of PRG and 8 KB of CHR is an NROM to a program that never writes to it,
so each goes in as it was built: nothing is linked again, and the serial
routines keep their pages and their timing.

    PRG, 16 KB banks            CHR, 8 KB banks
    0-1    setup                0     setup
    2-3    NESpedia             1     NESpedia
    4-5    jukebox              2     jukebox
    6-7    throughput test      3     throughput test
    8-9    NES Radar            4     the menu
    10-11  NPR                  5-6   NES Radar
    12-13  Weather              7     NPR
    14     Bluesky              8     Weather
    15     the menu             9     Bluesky
                                10-15 nothing

Bluesky is an NROM-128, 16 KB of PRG, in the one bank there was room for.
An NROM-128 has its bank at $C000 (and again at $8000, which Bluesky does
not use), so for it the MMC1 is set to 16 KB banks with the first fixed at
$8000 and its own at $C000: the setup ROM's first bank is under $C000, and
nothing reads it.

NES Radar has two pages of tiles, one for its splash and one for its
scope, and is the one program that writes to the mapper: to its CHR
register and no other, for the page it wants. It is built for that
(apps/nes-radar, `make cart`), and has to know where on the cartridge its
pages are, which `page` prints as the mapper counts them.

The menu is last because the last bank is the one an MMC1 has at $C000
when the power comes on.

`tables` writes what the menu is assembled from:

    chr.bin       8 KB of tiles: the setup ROM's, with this header's
    screen.bin    the menu's screen, 960 tiles and their 64 attributes
    menu.inc      where things are, and what starts each program

`rom` puts the file together. Two things in it are not as they were built,
and each is checked against what it replaces: six bytes at RESET_STUB in
every program's top bank, where each has padding, and its reset vector
pointed at them. They are the menu's own: an `inc` that resets the mapper,
which puts the menu's bank at $C000 under it, and a jump to the menu. So
reset is the menu, whatever the mapper held.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "apps", "setup", "tools"))

import gen_screen as layout  # noqa: E402

BANK = 0x4000                       # of PRG
PAGE = 0x2000                       # of CHR
PRG_BANKS = 16
CHR_PAGES = 16
INES_HEADER = 16
HEADER = b"NES\x1a" + bytes((PRG_BANKS, CHR_PAGES, 0x10, 0x08)) + bytes(8)   # NES 2.0, mapper 1
MENU_BANK = PRG_BANKS - 1
MENU_PAGE = 4
PRG_START = 0x8000
TOP = 0xC000                        # where a 32 KB program's second bank is

# The mapper's control register: 32 KB of PRG and 8 KB of CHR, and the
# mirroring an NROM's header asked for. For an NROM-128, 16 KB banks with
# the first fixed at $8000 and the one asked for at $C000.
CONTROL_VERTICAL = 0x02
CONTROL_HORIZONTAL = 0x03
CONTROL_16K_AT_C000 = 0x08

RESET_STUB = 0xFFDA
STUB_SIZE = 6
INC_ABS, JMP_ABS = 0xEE, 0x4C
RESET_VECTOR = 0xFFFC


MAPPER_NROM, MAPPER_MMC1 = 0, 1


class Program:
    def __init__(self, key, name, bank, page, pages=1, mapper=MAPPER_NROM, banks=2):
        self.key = key              # the option that names its ROM
        self.name = name            # as the menu has it
        self.bank = bank
        self.page = page
        self.pages = pages          # of CHR: an NROM has one
        self.mapper = mapper        # what its header says: the MMC1 for one built for it
        self.banks = banks          # of PRG: 2 for 32 KB, 1 for an NROM-128


# In the menu's order.
PROGRAMS = (
    Program("jukebox", "Jukebox", 4, 2),
    Program("wiki", "NESpedia", 2, 1),
    Program("radar", "NES Radar", 8, 5, pages=2, mapper=MAPPER_MMC1),
    Program("npr", "National Public Radio", 10, 7),
    Program("weather", "Weather", 12, 8),
    Program("bluesky", "Bluesky", 14, 9, banks=1),
    Program("throughput", "Throughput Test", 6, 3),
    Program("setup", "Setup", 0, 0),
)


def mapper_page(program):
    """Where a program's tiles begin, as the mapper's CHR register counts:
    in halves of a page."""
    return 2 * program.page

# --- the menu's screen, in tiles ------------------------------------------------

TITLE_TEXT = "MAIN MENU"
LIST_ROW = layout.HEADING_ROW + 1    # right under the title
LIST_STEP = 2                       # rows from a name to the next
LIST_COLUMN = layout.LEFT + 2       # after the arrow


class Image:
    """A program's ROM file."""

    def __init__(self, program, path):
        with open(path, "rb") as handle:
            data = handle.read()
        self.program = program
        self.path = path
        mapper = data[6] >> 4 | data[7] & 0xF0
        size = INES_HEADER + program.banks * BANK + program.pages * PAGE
        if (data[:4] != HEADER[:4] or data[4] != program.banks or data[5] != program.pages
                or mapper != program.mapper or len(data) != size):
            raise ValueError("%s is not %s with %d KB of PRG and %d of CHR"
                             % (path, "the cartridge's part" if program.mapper else "an NROM",
                                program.banks * 16, program.pages * 8))
        self.vertical = data[6] & 1
        self.prg = data[INES_HEADER:INES_HEADER + program.banks * BANK]
        self.chr = data[INES_HEADER + program.banks * BANK:]

    def tops(self):
        """Where in the PRG each of its 32 KB ends, or its 16 KB: every one
        has vectors."""
        return range(min(2 * BANK, len(self.prg)), len(self.prg) + 1, 2 * BANK)

    def resets(self):
        return {self.prg[top - 4] | self.prg[top - 3] << 8 for top in self.tops()}

    @property
    def entry(self):
        """Where it starts: its reset vector, as it was built."""
        resets = self.resets()
        if len(resets) != 1:
            raise ValueError("%s has banks that start in different places" % self.path)
        return resets.pop()

    @property
    def control(self):
        mirroring = CONTROL_VERTICAL if self.vertical else CONTROL_HORIZONTAL
        return mirroring | (CONTROL_16K_AT_C000 if self.program.banks == 1 else 0)


def load(args):
    return [Image(program, getattr(args, program.key)) for program in PROGRAMS]


def build_screen():
    screen = layout.build_screen(TITLE_TEXT)
    for index, program in enumerate(PROGRAMS):
        if len(program.name) > layout.LEFT + layout.WIDTH - LIST_COLUMN:
            raise ValueError("%r is too long for the menu" % program.name)
        for offset, char in enumerate(program.name):
            screen.put(LIST_COLUMN + offset, LIST_ROW + LIST_STEP * index, ord(char))
    return screen


def attributes():
    """The logo's palette over the header's rows, the text's under them."""
    if layout.HEADER_ROWS % 4:
        raise ValueError("the header must end where a row of attributes does")
    rows = layout.HEADER_ROWS // 4
    logo = layout.PALETTE_LOGO * 0x55
    return bytes([logo] * (8 * rows) + [0] * (64 - 8 * rows))


def arrow(index=0):
    """Where the arrow's sprite is beside a name, as (x, y) on the picture."""
    return 8 * layout.LEFT, 8 * (LIST_ROW + LIST_STEP * index)


def include(screen, images):
    lines = ["; Generated by nes/cart/gen_cart.py. Do not edit.", ""]

    def constant(name, value, note=""):
        lines.append("%-20s = %-6s%s" % (name, value, ("  ; " + note) if note else ""))

    def table(name, values, note):
        lines.append("%-15s .byte %s  ; %s"
                     % (name + ":", ", ".join("$%02X" % value for value in values), note))

    constant("ENTRIES", len(images))
    constant("LIST_STEP", LIST_STEP, "rows from a name to the next")
    constant("ARROW_X", arrow()[0])
    constant("ARROW_Y", arrow()[1], "beside the first name")
    constant("TILE_ARROW", "$%02X" % screen.named["ARROW"])
    constant("MENU_CHR", "$%02X" % (2 * MENU_PAGE), "the menu's tiles, as the mapper counts")
    constant("RESET_STUB", "$%04X" % RESET_STUB)
    lines += ["", "; The programs, in the menu's order: " + ", ".join(
        image.program.name for image in images) + "."]
    table("entry_control", [image.control for image in images], "the mapper's control register")
    table("entry_chr", [mapper_page(image.program) for image in images], "its tiles")
    table("entry_prg", [image.program.bank for image in images], "its code")
    table("entry_lo", [image.entry & 0xFF for image in images], "where it starts")
    table("entry_hi", [image.entry >> 8 for image in images], "")
    lines += ["", "palette_data:"]
    for palette in layout.PALETTES + (layout.SPRITE_PALETTE,) * 4:
        lines.append("    .byte " + ", ".join("$%02X" % color
                                              for color in (layout.BACKDROP,) + palette))
    return "\n".join(line.rstrip() for line in lines) + "\n"


def tables(args):
    images = load(args)
    screen = build_screen()
    os.makedirs(args.out, exist_ok=True)
    for name, data in (("chr.bin", screen.chr()),
                       ("screen.bin", bytes(screen.names) + attributes()),
                       ("menu.inc", include(screen, images).encode("ascii"))):
        layout.write_if_changed(os.path.join(args.out, name), data)
    if args.preview:
        sprite = arrow() + (screen.named["ARROW"],)
        layout.write_png(args.preview, layout.render(screen.chr(), screen.names,
                                                     sprites=[sprite]))
    return 0


# --- the file --------------------------------------------------------------------

def expect(what, found, wanted):
    if bytes(found) != bytes(wanted):
        raise ValueError("%s: %s where %s was expected"
                         % (what, bytes(found).hex(), bytes(wanted).hex()))


def build_rom(menu, tiles, images):
    """The cartridge's file from the menu's bank, its tiles and the
    programs."""
    if len(menu) != BANK or len(tiles) != PAGE:
        raise ValueError("the menu is one bank of PRG and one page of CHR")
    prg = bytearray(b"\xFF" * (PRG_BANKS * BANK))
    chr_rom = bytearray(CHR_PAGES * PAGE)
    menu_at = MENU_BANK * BANK
    prg[menu_at:] = menu
    chr_rom[MENU_PAGE * PAGE:(MENU_PAGE + 1) * PAGE] = tiles

    # The menu's stub, which every program's reset will come to.
    stub_at = RESET_STUB - TOP
    stub = bytes(menu[stub_at:stub_at + STUB_SIZE])
    expect("the menu's reset stub", stub[:4],
           (INC_ABS, RESET_STUB & 0xFF, RESET_STUB >> 8, JMP_ABS))
    vector = bytes((RESET_STUB & 0xFF, RESET_STUB >> 8))
    expect("the menu's reset vector", menu[RESET_VECTOR - TOP:][:2], vector)

    for image in images:
        program = image.program
        start = program.bank * BANK
        if prg[start:start + len(image.prg)].strip(b"\xFF"):
            raise ValueError("%s is where another program is" % image.path)
        prg[start:start + len(image.prg)] = image.prg
        tiles_at = program.page * PAGE
        if tiles_at <= MENU_PAGE * PAGE < tiles_at + len(image.chr) or any(
                chr_rom[tiles_at:tiles_at + len(image.chr)]):
            raise ValueError("%s has its tiles where others are" % image.path)
        chr_rom[tiles_at:tiles_at + len(image.chr)] = image.chr
        for top in image.tops():
            at = start + top - (0x10000 - RESET_STUB)
            expect("%s at $%04X" % (image.path, RESET_STUB), prg[at:at + STUB_SIZE],
                   b"\xFF" * STUB_SIZE)
            prg[at:at + STUB_SIZE] = stub
            prg[start + top - 4:start + top - 2] = vector

    return HEADER + bytes(prg) + bytes(chr_rom)


def rom(args):
    with open(args.menu, "rb") as handle:
        menu = handle.read()
    with open(args.chr, "rb") as handle:
        tiles = handle.read()
    data = build_rom(menu, tiles, load(args))
    with open(args.out, "wb") as handle:
        handle.write(data)
    return 0


def page(args):
    print(mapper_page(next(program for program in PROGRAMS if program.key == args.program)))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    steps = parser.add_subparsers(dest="step", required=True)
    step = steps.add_parser("page")
    step.set_defaults(run=page)
    step.add_argument("program", choices=[program.key for program in PROGRAMS])
    for name, run, out in (("tables", tables, "directory for chr.bin, screen.bin and menu.inc"),
                           ("rom", rom, "the cartridge's file")):
        step = steps.add_parser(name)
        step.set_defaults(run=run)
        step.add_argument("out", help=out)
        for program in PROGRAMS:
            step.add_argument("--" + program.key, required=True, metavar="ROM",
                              help="%s's ROM" % program.name)
        if name == "tables":
            step.add_argument("--preview", help="also write the menu as a PNG")
        else:
            step.add_argument("--menu", required=True, help="the menu's bank")
            step.add_argument("--chr", required=True, help="the menu's tiles")
    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except ValueError as error:
        sys.exit("gen_cart.py: %s" % error)


if __name__ == "__main__":
    sys.exit(main())
