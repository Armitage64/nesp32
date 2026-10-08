import atexit
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "..", "tools"))
sys.path.insert(0, os.path.join(ROOT, "..", "tests"))   # the line model, wire.py
sys.path.insert(0, HERE)

# The ROM's host is a nesp32, whose firmware is at the top of this
# repository. Its link and services are built for this computer, into a
# directory of their own, and the tests run the ROM against them.
NESP32 = os.path.abspath(os.environ.get("NESP32", os.path.join(ROOT, "..", "..", "..")))
NESP_BUILD = tempfile.mkdtemp(prefix="nes-throughput-nesp32-")
atexit.register(shutil.rmtree, NESP_BUILD, ignore_errors=True)
HAVE_NESP32 = os.path.isdir(NESP32)
if HAVE_NESP32:
    subprocess.run(["make", "-s", "BUILD=%s" % NESP_BUILD, "proto", "host"], cwd=NESP32,
                   check=True)
    os.environ["NESP_BUILD"] = NESP_BUILD
    sys.path.insert(0, NESP_BUILD)
    sys.path.insert(0, os.path.join(NESP32, "host"))


@pytest.fixture(scope="session")
def rom(tmp_path_factory):
    """(ROM path, labels path), built from this tree."""
    if not (shutil.which("ca65") and shutil.which("ld65")):
        pytest.skip("cc65 not installed")
    if not HAVE_NESP32:
        pytest.skip("no nesp32 checkout at %s" % NESP32)
    build = tmp_path_factory.mktemp("thru_build")
    subprocess.run(["make", "-s", "BUILD=%s" % build, "NESP32=%s" % NESP32,
                    "NESP_BUILD=%s" % NESP_BUILD, "verify"], cwd=ROOT, check=True)
    return str(build / "linktest.nes"), str(build / "linktest.labels")
