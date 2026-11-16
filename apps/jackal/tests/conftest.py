import atexit
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)

# The netplay ROM's link is nesp32's, at the top of this repository.
# Its link and services are built for this computer, into
# a directory of their own, and the netplay ROM's tests run against them.
NESP32 = os.path.abspath(os.environ.get("NESP32", os.path.join(ROOT, "..", "..")))
NESP_BUILD = tempfile.mkdtemp(prefix="nes-jackal-nesp32-")
atexit.register(shutil.rmtree, NESP_BUILD, ignore_errors=True)
HAVE_NESP32 = os.path.isdir(NESP32)
# The game's code, which is not here: RayofJay's disassembly, a submodule.
DISASSEMBLY = os.path.join(NESP32, "third_party", "NES-Jackal_Disassembly_Fully_Commented",
                           "ASM Source")
if HAVE_NESP32:
    subprocess.run(["make", "-s", "BUILD=%s" % NESP_BUILD, "proto", "host"], cwd=NESP32,
                   check=True)
    os.environ["NESP_BUILD"] = NESP_BUILD
    sys.path.insert(0, NESP_BUILD)
    sys.path.insert(0, os.path.join(NESP32, "host"))


@pytest.fixture(scope="session")
def build(tmp_path_factory):
    """A directory with the ROMs and everything made on the way, built from
    this tree."""
    if not (shutil.which("ca65") and shutil.which("ld65")):
        pytest.skip("cc65 not installed")
    if not os.path.isfile(os.path.join(ROOT, "baserom.nes")):
        pytest.skip("no baserom.nes")
    if not HAVE_NESP32:
        pytest.skip("no nesp32 checkout at %s" % NESP32)
    if not os.path.isfile(os.path.join(DISASSEMBLY, "MAIN.asm")):
        pytest.skip("no disassembly at %s: git submodule update --init" % DISASSEMBLY)
    out = tmp_path_factory.mktemp("build")
    subprocess.run(["make", "-s", "BUILD=%s" % out, "NESP32=%s" % NESP32,
                    "NESP_BUILD=%s" % NESP_BUILD, "PYTHON=%s" % sys.executable,
                    "verify", "all"], cwd=ROOT, check=True)
    return out


def _maker(build, name):
    from console import Console

    def make(**kwargs):
        return Console(str(build / (name + ".nes")), str(build / (name + ".dbg")), **kwargs)
    return make


@pytest.fixture
def console(build):
    """Make a Console on the original ROM."""
    return _maker(build, "jackal")


@pytest.fixture
def net_console(build):
    """Make a Console on the netplay ROM."""
    return _maker(build, "jackal_net")


@pytest.fixture
def slow_console(build):
    """Make a Console on the netplay ROM with the game's own routines where
    the netplay has faster ways."""
    return _maker(build, "jackal_net_slow")
