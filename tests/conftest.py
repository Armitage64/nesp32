"""Build everything the tests need, from this tree, before any are collected.

The generated protocol module and the host library go to a directory of
their own, so a test run never reads something stale from build/. The
modules that load them (host/nesp.py) find it through NESP_BUILD.
"""

import atexit
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
BUILD = tempfile.mkdtemp(prefix="nesp32-build-")
atexit.register(shutil.rmtree, BUILD, ignore_errors=True)

subprocess.run(["make", "-s", "BUILD=%s" % BUILD, "proto", "host"], cwd=ROOT, check=True)
os.environ["NESP_BUILD"] = BUILD
sys.path.insert(0, BUILD)
sys.path.insert(0, os.path.join(ROOT, "host"))
sys.path.insert(0, os.path.join(ROOT, "nes", "lib"))
sys.path.insert(0, os.path.join(ROOT, "nes", "setup"))
sys.path.insert(0, os.path.join(ROOT, "nes", "cart"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, HERE)


@pytest.fixture(scope="session")
def build():
    """The build directory, with the setup ROM in it."""
    if not (shutil.which("ca65") and shutil.which("ld65")):
        pytest.skip("cc65 not installed")
    subprocess.run(["make", "-s", "BUILD=%s" % BUILD, "verify", "timeout-rom"], cwd=ROOT,
                   check=True)
    return BUILD


@pytest.fixture(scope="session")
def cart_build(build):
    """The build directory, with the cartridge in it. The other programs on
    it are built from apps/."""
    for name in ("jukebox", "wiki", "drmario"):
        if not os.path.isdir(os.path.join(ROOT, "apps", name)):
            pytest.skip("apps/%s is not here" % name)
    if not os.path.isfile(os.path.join(ROOT, "third_party", "NES-Games-Disassembly",
                                       "Dr. Mario", "bank_FF.asm")):
        pytest.skip("Dr. Mario's disassembly is not here: git submodule update --init")
    subprocess.run(["make", "-s", "BUILD=%s" % BUILD, "verify-cart"], cwd=ROOT, check=True)
    return BUILD


@pytest.fixture
def cart(cart_build):
    """Make a Console on the cartridge, with the menu's labels."""
    from console import Console

    def make(**kwargs):
        return Console(os.path.join(cart_build, "nesp32.nes"),
                       os.path.join(cart_build, "cart", "menu.labels"), **kwargs)
    return make


@pytest.fixture
def stick():
    """A Stick with no console: ask() is a request and its reply."""
    from nesp import Stick

    return Stick()


@pytest.fixture
def console(build):
    """Make a Console on the setup ROM."""
    from console import Console

    def make(**kwargs):
        return Console(os.path.join(build, "setup.nes"), os.path.join(build, "setup.labels"),
                       **kwargs)
    return make


@pytest.fixture
def timeout_console(build):
    """Make a Console on the setup ROM built with the receiver that gives up
    by counting."""
    from console import Console

    def make(**kwargs):
        return Console(os.path.join(build, "setup_timeout.nes"),
                       os.path.join(build, "setup_timeout.labels"), **kwargs)
    return make


@pytest.fixture
def linked(console):
    """A console on the setup ROM and a Stick, joined by the line and past
    their hello: linked(**port_options) returns (console, stick, port)."""
    from nesp import Stick
    from wire import link

    def make(**port_options):
        c = console()
        stick, port = link(c, Stick, **port_options)
        c.run_until(lambda: c.byte("linked"), 200)
        return c, stick, port
    return make
