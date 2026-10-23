import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)

NESP32 = os.path.abspath(os.environ.get("NESP32", os.path.join(ROOT, "..", "..")))
# The game's code, which is not here: cyneprepou4uk's disassembly, a submodule.
CF_SRC = os.environ.get("CF_SRC", os.path.join(
    NESP32, "third_party", "NES-Games-Disassembly", "Contra Force"))


@pytest.fixture(scope="session")
def build(tmp_path_factory):
    """A directory with both ROMs and everything made on the way, built
    from this tree."""
    if not (shutil.which("ca65") and shutil.which("ld65")):
        pytest.skip("cc65 not installed")
    if not os.path.isfile(os.path.join(CF_SRC, "bank_FF.asm")):
        pytest.skip("no disassembly at %s: git submodule update --init" % CF_SRC)
    out = tmp_path_factory.mktemp("build")
    subprocess.run(["make", "-s", "BUILD=%s" % out, "NESP32=%s" % NESP32, "verify", "all"],
                   cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    return out


@pytest.fixture
def console(build):
    """Make a Console on the original."""
    from console import Console

    def make(**kwargs):
        return Console(str(build / "contraforce.nes"), str(build / "contraforce.dbg"), **kwargs)
    return make


@pytest.fixture
def fast_console(build):
    """Make a Console on the faster ROM."""
    from console import Console

    def make(**kwargs):
        return Console(str(build / "contraforce_fast.nes"), str(build / "contraforce_fast.dbg"),
                       **kwargs)
    return make
