"""dist/bubblebobble_net.bps, which players apply to their own copy of the game: it
makes the netplay ROM as it is built from this tree, and holds none of the
game."""

import os
import sys

import pytest

from conftest import NESP32, ROOT

sys.path.insert(0, os.path.join(NESP32, "tools"))
import gen_patch  # noqa: E402

DIST = os.path.join(ROOT, "dist")


def read(path):
    with open(path, "rb") as handle:
        return handle.read()


@pytest.fixture
def roms(build):
    return read(build / "bubblebobble.nes"), read(build / "bubblebobble_net.nes")


def patch():
    path = os.path.join(DIST, "bubblebobble_net.bps")
    if not os.path.isfile(path):
        pytest.skip("no %s: make bps" % path)
    return read(path)


def test_the_patch_makes_the_netplay_rom(roms):
    """`make bps` has been run since the netplay last changed."""
    original, netplay = roms
    assert gen_patch.apply_bps(original, patch()) == netplay


def test_the_patch_refuses_another_rom(roms):
    original, _ = roms
    other = bytearray(original)
    other[0x10] ^= 0xFF
    with pytest.raises(ValueError):
        gen_patch.apply_bps(bytes(other), patch())


def test_the_patch_holds_none_of_the_game(roms):
    """What the game has is copied from the player's own ROM: what the
    patch carries is the netplay's, with no run of it found in the game."""
    original, _ = roms
    runs = gen_patch.carried(patch())
    assert runs
    assert gen_patch.borrowed(original, runs) == []
