import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "firmware", "stick"))
sys.path.insert(0, HERE)


@pytest.fixture(scope="session")
def build(tmp_path_factory):
    """A directory with the ROM and everything made on the way, built from
    this tree."""
    if not (shutil.which("ca65") and shutil.which("ld65")):
        pytest.skip("cc65 not installed")
    out = tmp_path_factory.mktemp("build")
    subprocess.run(["make", "-s", "BUILD=%s" % out], cwd=ROOT, check=True)
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
