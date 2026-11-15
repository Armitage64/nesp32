"""tools/mesen_run.py: its button specs and the Lua it writes, with no Mesen."""

import argparse
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))

import mesen_run  # noqa: E402


def test_press():
    assert mesen_run.press("200:down") == (200, 1, ["down"])
    assert mesen_run.press("10:A+Start:3") == (10, 3, ["a", "start"])
    for bad in ("200", "200:jump", "x:a"):
        with pytest.raises((argparse.ArgumentTypeError, ValueError)):
            mesen_run.press(bad)


def test_lua_holds_each_frame():
    lua = mesen_run.lua_script(30, [(10, 2, ["a"]), (11, 1, ["b"])], [30], [12], "/o")
    assert "[10] = {a=true}," in lua
    assert "[11] = {a=true, b=true}," in lua
    assert "[12]" not in lua.split("local shots")[0]
    assert "local shots = {[30]=true}" in lua
    assert "local rams = {[12]=true}" in lua
    assert "local last = 30" in lua


def test_png_diff_round_trip(tmp_path):
    import png_diff
    a = [[(x, y, 0) for x in range(5)] for y in range(4)]
    b = [row[:] for row in a]
    b[2][3] = (9, 9, 9)
    pa, pb = str(tmp_path / "a.png"), str(tmp_path / "b.png")
    png_diff.save(pa, 5, 4, a)
    png_diff.save(pb, 5, 4, b)
    assert png_diff.load(pa) == (5, 4, a)
    assert png_diff.diff(png_diff.load(pa), png_diff.load(pb)) == [(3, 2)]


def test_lua_bridge():
    lua = mesen_run.lua_script(10, [], [10], [], "/o", port=12345)
    assert 'BRIDGE_PORT = 12345' in lua
    assert lua.index("nesp32.lua") < lua.index("local OUT")
    assert os.path.exists(mesen_run.NESP32_LUA)
    with open(mesen_run.NESP32_LUA) as f:
        assert "local BRIDGE_PORT = 7878" in f.read()   # what the gsub replaces
    assert "BRIDGE_PORT" not in mesen_run.lua_script(10, [], [10], [], "/o")
