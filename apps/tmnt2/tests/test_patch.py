"""dist/'s patches, which players apply to their own copy of the game: they
make the netplay ROM as it is built from this tree, and hold none of the
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
    return read(build / "tmnt2.nes"), read(build / "tmnt2_net.nes")


def dist(name):
    """A patch in dist/, which `make bps` writes."""
    path = os.path.join(DIST, name)
    if not os.path.isfile(path):
        pytest.skip("no %s: make bps" % path)
    return read(path)


def test_the_bps_patch_makes_the_netplay_rom(roms):
    """`make bps` has been run since the netplay last changed."""
    original, netplay = roms
    assert gen_patch.apply_bps(original, dist("tmnt2_net.bps")) == netplay


def test_the_bps_patch_refuses_another_rom(roms):
    original, _ = roms
    other = bytearray(original)
    other[0x10] ^= 0xFF
    with pytest.raises(ValueError):
        gen_patch.apply_bps(bytes(other), dist("tmnt2_net.bps"))


def test_the_ips_patch_makes_the_netplay_rom(roms):
    original, netplay = roms
    patch = dist("tmnt2_net.ips")
    assert patch[:5] == b"PATCH" and patch[-3:] == b"EOF"
    rom = bytearray(original)
    at = 5
    while at < len(patch) - 3:
        offset = int.from_bytes(patch[at:at + 3], "big")
        length = int.from_bytes(patch[at + 3:at + 5], "big")
        rom[offset:offset + length] = patch[at + 5:at + 5 + length]
        at += 5 + length
    assert bytes(rom) == netplay


def test_the_patch_holds_none_of_the_game(roms):
    """Nothing of the game moves in the netplay build, so what differs is
    the netplay's own: no run of its bytes is found in the game."""
    original, netplay = roms
    runs = gen_patch.differing_runs(original, netplay)
    assert runs
    assert gen_patch.borrowed(original, runs) == []
