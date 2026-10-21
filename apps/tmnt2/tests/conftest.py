import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)

NESP32 = os.path.abspath(os.environ.get("NESP32", os.path.join(ROOT, "..", "..")))
# The game's code, which is not here: Aaron Bottegal's disassembly, a
# submodule.
TMNT2_SRC = os.environ.get("TMNT2_SRC",
                           os.path.join(NESP32, "third_party", "TMNT2-NES-Reverse-Engineered"))


@pytest.fixture(scope="session")
def build(tmp_path_factory):
    """A directory with the ROM and everything made on the way, built from
    this tree."""
    if not (shutil.which("ca65") and shutil.which("ld65")):
        pytest.skip("cc65 not installed")
    if not os.path.isfile(os.path.join(ROOT, "baserom.nes")):
        pytest.skip("no baserom.nes")
    if not os.path.isfile(os.path.join(TMNT2_SRC, "TMNT2.bank31.asm")):
        pytest.skip("no disassembly at %s: git submodule update --init" % TMNT2_SRC)
    out = tmp_path_factory.mktemp("build")
    subprocess.run(["make", "-s", "BUILD=%s" % out, "NESP32=%s" % NESP32,
                    "PYTHON=%s" % sys.executable, "verify", "all"], cwd=ROOT, check=True)
    return out


@pytest.fixture
def console(build):
    """Make a Console on the original ROM."""
    from console import Console

    def make(**kwargs):
        return Console(str(build / "tmnt2.nes"), str(build / "tmnt2.dbg"), **kwargs)
    return make
