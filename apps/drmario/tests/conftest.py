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
NESP_BUILD = tempfile.mkdtemp(prefix="nes-drmario-nesp32-")
atexit.register(shutil.rmtree, NESP_BUILD, ignore_errors=True)
HAVE_NESP32 = os.path.isdir(NESP32)
if HAVE_NESP32:
    subprocess.run(["make", "-s", "BUILD=%s" % NESP_BUILD, "proto", "host"], cwd=NESP32,
                   check=True)
    os.environ["NESP_BUILD"] = NESP_BUILD
    sys.path.insert(0, NESP_BUILD)
    sys.path.insert(0, os.path.join(NESP32, "host"))


@pytest.fixture(scope="session")
def build(tmp_path_factory):
    """A directory with both ROMs and everything made on the way, built
    from this tree."""
    if not (shutil.which("ca65") and shutil.which("ld65")):
        pytest.skip("cc65 not installed")
    if not HAVE_NESP32:
        pytest.skip("no nesp32 checkout at %s" % NESP32)
    out = tmp_path_factory.mktemp("build")
    subprocess.run(["make", "-s", "BUILD=%s" % out, "NESP32=%s" % NESP32,
                    "NESP_BUILD=%s" % NESP_BUILD, "verify", "all"], cwd=ROOT, check=True)
    return out


@pytest.fixture
def console(build):
    """Make a Console on the ROM."""
    from console import Console

    def make(**kwargs):
        return Console(str(build / "drmario.nes"), str(build / "drmario.dbg"), **kwargs)
    return make


@pytest.fixture
def net_console(build):
    """Make a Console on the netplay ROM."""
    from console import Console

    def make(**kwargs):
        return Console(str(build / "drmario_net.nes"),
                       [str(build / "drmario_net.dbg"), str(build / "menu.dbg")], **kwargs)
    return make


@pytest.fixture
def banks(build):
    """The names of each bank of the netplay ROM, with their values: the
    game's, and the menu's."""
    from console import load_labels

    return load_labels(str(build / "drmario_net.dbg")), load_labels(str(build / "menu.dbg"))
