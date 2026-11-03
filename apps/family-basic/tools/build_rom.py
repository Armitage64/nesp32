"""The ROM: Family BASIC V3 and nesp32's keyboard, on an MMC1.

    tools/build_rom.py baserom.nes build/fbkbd.bin build/fbkbd.labels build/fbasic.nes

The PRG is 64 KB: the game's 32 KB, with the few bytes that call
nes/fbkbd.s changed (fbasic.PATCH_SITES), and then fbkbd.s's 32 KB, whose
last 16 KB the MMC1 has at $C000 at power-on. The CHR is the game's. The
cartridge has 8 KB of memory at $6000, kept by a battery as the game's 4
KB was; the iNES header says so.
"""

import sys

import fbasic

JMP, JSR = 0x4C, 0x20
MAPPER_MMC1 = 1
FLAGS6 = MAPPER_MMC1 << 4 | 0x02 | 0x01     # battery, vertical mirroring
PRG_BANKS = 4                               # of 16 KB
CHR_BANKS = 1                               # of 8 KB
PRG_RAM_BANKS = 1                           # of 8 KB (iNES byte 8)


def load_labels(path):
    labels = {}
    with open(path) as handle:
        for line in handle:
            _, address, name = line.split()
            labels[name.lstrip(".")] = int(address, 16)
    return labels


def word(address):
    return bytes((address & 0xFF, address >> 8))


def patch(rom, labels, ours):
    for site, (address, original) in fbasic.PATCH_SITES.items():
        if rom.read(address, len(original)) != original:
            raise ValueError("the game's bytes at $%04X are not as expected" % address)
    nmi = labels["fb_nmi"]
    address, _ = fbasic.PATCH_SITES["nmi"]
    rom.write(address + 1, bytes((nmi & 0xFF,)))
    rom.write(address + 5, bytes((nmi >> 8,)))
    rom.write(fbasic.PATCH_SITES["stop"][0], bytes((JMP,)) + word(labels["fb_stop"]))
    rom.write(fbasic.PATCH_SITES["pad"][0], bytes((JMP,)) + word(labels["fb_pad"]))
    rom.write(fbasic.PATCH_SITES["scan"][0], bytes((JSR,)) + word(labels["fb_scan"])
              + bytes((JMP,)) + word(fbasic.SCAN_DECODE))
    # reset_stub's bytes, from where they are in ours.
    stub, room = fbasic.PATCH_SITES["stub"]
    assert labels["reset_stub"] == stub
    start = stub - fbasic.PRG_START
    rom.write(stub, ours[start:start + len(room)])
    rom.write(fbasic.PATCH_SITES["reset_vector"][0], word(stub))


def main(argv):
    rom = fbasic.Rom(argv[1])
    with open(argv[2], "rb") as handle:
        ours = handle.read()
    assert len(ours) == fbasic.PRG_SIZE
    patch(rom, load_labels(argv[3]), ours)
    header = b"NES\x1a" + bytes((PRG_BANKS, CHR_BANKS, FLAGS6, 0, PRG_RAM_BANKS)) + bytes(7)
    with open(argv[4], "wb") as handle:
        handle.write(header + bytes(rom.prg) + ours + rom.chr)


if __name__ == "__main__":
    main(sys.argv)
