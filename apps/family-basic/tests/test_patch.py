"""dist/fbasic.bps, which players apply to their own copy of the game: it
makes the ROM as it is built from this tree, and holds none of the game."""

import os
import sys

import pytest

from conftest import BASEROM, NESP32, ROOT

import fbasic

sys.path.insert(0, os.path.join(NESP32, "tools"))
import gen_patch  # noqa: E402

DIST = os.path.join(ROOT, "dist")
CHR_FROM = fbasic.INES_HEADER + fbasic.PRG_SIZE         # in the game's file
CHR_TO = fbasic.INES_HEADER + 2 * fbasic.PRG_SIZE       # and in ours


def read(path):
    with open(path, "rb") as handle:
        return handle.read()


@pytest.fixture
def roms(rom):
    return read(BASEROM), read(rom[0])


def patch():
    path = os.path.join(DIST, "fbasic.bps")
    if not os.path.isfile(path):
        pytest.skip("no %s: make bps" % path)
    return read(path)


def test_the_patch_makes_the_rom(roms):
    """`make bps` has been run since the ROM last changed."""
    game, built = roms
    assert gen_patch.apply_bps(game, patch()) == built


def test_the_patch_refuses_another_rom(roms):
    game, _ = roms
    other = bytearray(game)
    other[0x10] ^= 0xFF
    with pytest.raises(ValueError):
        gen_patch.apply_bps(bytes(other), patch())


def test_the_patch_holds_none_of_the_game(roms):
    """The game's PRG stays where it is, and its CHR is copied from the
    player's ROM: what the patch carries is the build's own."""
    game, built = roms
    assert built[CHR_TO:CHR_TO + fbasic.CHR_SIZE] == game[CHR_FROM:CHR_FROM + fbasic.CHR_SIZE]
    runs = gen_patch.carried(patch())
    assert runs
    assert gen_patch.borrowed(game, runs) == []
    assert not any(at < CHR_TO + fbasic.CHR_SIZE and at + len(data) > CHR_TO for at, data in runs)
