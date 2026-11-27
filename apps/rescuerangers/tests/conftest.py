import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)


@pytest.fixture(scope="session")
def build(tmp_path_factory):
    """A directory with the original ROM and everything made on the way,
    built from this tree. (No netplay ROM yet: README.md, "Not done".)"""
    if not (shutil.which("ca65") and shutil.which("ld65")):
        pytest.skip("cc65 not installed")
    if not os.path.isfile(os.path.join(ROOT, "baserom.nes")):
        pytest.skip("no baserom.nes")
    out = tmp_path_factory.mktemp("build")
    subprocess.run(["make", "-s", "BUILD=%s" % out, "PYTHON=%s" % sys.executable,
                    "verify", "all"], cwd=ROOT, check=True)
    return out


@pytest.fixture
def console(build):
    """Make a Console on the original ROM."""
    from console import Console

    def make(**kwargs):
        return Console(str(build / "rescuerangers.nes"), str(build / "rescuerangers.dbg"),
                       **kwargs)
    return make
